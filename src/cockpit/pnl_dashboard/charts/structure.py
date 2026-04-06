"""Structure chart data builders: Maturity Wall, Trends, Regulatory."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from cockpit.pnl_dashboard.charts.constants import (
    CURRENCY_COLORS,
    PRODUCT_COLORS,
)

logger = logging.getLogger(__name__)


def _build_maturity_wall(
    deals: Optional[pd.DataFrame] = None,
    df: Optional[pd.DataFrame] = None,
) -> dict:
    """Maturity wall: maturing volumes by month, colored by reinvestment spread."""
    if deals is None or deals.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {},
                "top_maturities": [], "reinvestment_summary": {}, "kpis": {}}

    d = deals.copy()
    if "Maturitydate" not in d.columns:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {},
                "top_maturities": [], "reinvestment_summary": {}, "kpis": {}}

    d["_mat"] = pd.to_datetime(d["Maturitydate"], errors="coerce")
    d = d[d["_mat"].notna()].copy()
    if d.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {},
                "top_maturities": [], "reinvestment_summary": {}, "kpis": {}}

    # Nominal (use Amount or Nominal)
    nom_col = "Amount" if "Amount" in d.columns else "Nominal" if "Nominal" in d.columns else None
    if nom_col:
        d["_nom"] = pd.to_numeric(d[nom_col], errors="coerce").fillna(0).abs()
    else:
        d["_nom"] = 0.0

    # Rate columns
    rate_col = None
    for c in ["RateRef", "EqOisRate", "Clientrate", "YTM"]:
        if c in d.columns:
            rate_col = c
            break
    if rate_col:
        d["_book_rate"] = pd.to_numeric(d[rate_col], errors="coerce").fillna(0)
    else:
        d["_book_rate"] = 0.0

    # Current OIS by currency from P&L data (weighted avg OIS at shock=0)
    market_rates = {}
    if df is not None and not df.empty:
        ois_rows = df[(df["Indice"] == "OISfwd") & (df["Shock"] == "0")]
        if not ois_rows.empty and "Deal currency" in ois_rows.columns:
            for ccy in ois_rows["Deal currency"].unique():
                market_rates[str(ccy)] = float(ois_rows[ois_rows["Deal currency"] == ccy]["Value"].mean())

    # Month label
    d["_mat_month"] = d["_mat"].dt.to_period("M").astype(str)

    # Sort by maturity and take next 24 months
    d = d.sort_values("_mat")
    months = sorted(d["_mat_month"].unique())[:24]
    d = d[d["_mat_month"].isin(months)]

    if d.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {},
                "top_maturities": [], "reinvestment_summary": {}, "kpis": {}}

    ccy_col = "Currency" if "Currency" in d.columns else "Deal currency" if "Deal currency" in d.columns else None
    prod_col = "Product" if "Product" in d.columns else "Product2BuyBack" if "Product2BuyBack" in d.columns else None

    # By currency x month
    by_currency = {}
    if ccy_col:
        for ccy in sorted(d[ccy_col].dropna().unique()):
            ccy_data = d[d[ccy_col] == ccy]
            volumes = []
            for m in months:
                vol = float(ccy_data[ccy_data["_mat_month"] == m]["_nom"].sum())
                volumes.append(round(vol, 0))
            by_currency[str(ccy)] = {
                "volumes": volumes,
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
                "total": round(float(ccy_data["_nom"].sum()), 0),
            }

    # By product x month
    by_product = {}
    if prod_col:
        for prod in sorted(d[prod_col].dropna().unique()):
            prod_data = d[d[prod_col] == prod]
            volumes = []
            for m in months:
                vol = float(prod_data[prod_data["_mat_month"] == m]["_nom"].sum())
                volumes.append(round(vol, 0))
            by_product[str(prod)] = {
                "volumes": volumes,
                "color": PRODUCT_COLORS.get(str(prod), "#8b949e"),
            }

    # Top 20 upcoming maturities with reinvestment spread
    top = d.head(20).copy()
    top_maturities = []
    for _, row in top.iterrows():
        ccy = str(row.get(ccy_col, "")) if ccy_col else ""
        book_rate = float(row["_book_rate"])
        mkt_rate = market_rates.get(ccy, 0)
        spread_bps = (mkt_rate - book_rate) * 10000
        top_maturities.append({
            "deal_id": str(row.get("Dealid", "")),
            "counterparty": str(row.get("Counterparty", "")),
            "currency": ccy,
            "product": str(row.get(prod_col, "")) if prod_col else "",
            "maturity": str(row["_mat"].strftime("%Y-%m-%d")),
            "nominal": round(float(row["_nom"]), 0),
            "book_rate_pct": round(book_rate * 100, 4),
            "market_rate_pct": round(mkt_rate * 100, 4),
            "spread_bps": round(spread_bps, 1),
        })

    # Reinvestment summary: aggregate by currency
    reinvestment_summary = {}
    if ccy_col:
        for ccy in sorted(d[ccy_col].dropna().unique()):
            ccy_data = d[d[ccy_col] == ccy]
            total_vol = float(ccy_data["_nom"].sum())
            mkt = market_rates.get(str(ccy), 0)
            avg_book = float((ccy_data["_book_rate"] * ccy_data["_nom"]).sum()) / total_vol if total_vol > 0 else 0
            spread = (mkt - avg_book) * 10000
            # NII impact: total_vol x spread / 10000 (annualized)
            nii_impact = total_vol * (mkt - avg_book)
            reinvestment_summary[str(ccy)] = {
                "maturing_volume": round(total_vol, 0),
                "avg_book_rate": round(avg_book * 100, 4),
                "market_rate": round(mkt * 100, 4),
                "spread_bps": round(spread, 1),
                "nii_impact": round(nii_impact, 0),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # KPIs
    total_maturing = float(d["_nom"].sum())
    total_nii_impact = sum(r["nii_impact"] for r in reinvestment_summary.values())
    # Months until next big maturity (>10% of total)
    big_threshold = total_maturing * 0.10
    months_to_cliff = None
    for i, m in enumerate(months):
        m_vol = float(d[d["_mat_month"] == m]["_nom"].sum())
        if m_vol >= big_threshold:
            months_to_cliff = i + 1
            break

    kpis = {
        "total_maturing_24m": round(total_maturing, 0),
        "total_nii_impact": round(total_nii_impact, 0),
        "avg_spread_bps": round(total_nii_impact / total_maturing * 10000, 1) if total_maturing > 0 else 0,
        "months_to_cliff": months_to_cliff,
        "deal_count": len(d),
    }

    return {
        "has_data": True,
        "months": months,
        "by_currency": by_currency,
        "by_product": by_product,
        "top_maturities": top_maturities,
        "reinvestment_summary": reinvestment_summary,
        "kpis": kpis,
    }


def _build_trends(
    kpi_history: Optional[pd.DataFrame] = None,
) -> dict:
    """Historical KPI trends from daily snapshots."""
    if kpi_history is None or (isinstance(kpi_history, pd.DataFrame) and kpi_history.empty):
        return {"has_data": False, "dates": [], "metrics": {}}

    df = kpi_history.copy()
    if "date" not in df.columns:
        return {"has_data": False, "dates": [], "metrics": {}}

    df = df.sort_values("date")
    dates = [str(d) for d in df["date"].unique()]

    # Each metric column becomes a time series
    metric_cols = [c for c in df.columns if c != "date"]
    metrics = {}
    for col in metric_cols:
        values = df.groupby("date")[col].first().reindex(df["date"].unique())
        vals = [round(float(v), 2) if pd.notna(v) else None for v in values]
        if any(v is not None for v in vals):
            # Compute trailing stats
            valid = [v for v in vals if v is not None]
            metrics[col] = {
                "values": vals,
                "latest": valid[-1] if valid else None,
                "min": round(min(valid), 2) if valid else None,
                "max": round(max(valid), 2) if valid else None,
                "mean": round(float(np.mean(valid)), 2) if valid else None,
                "std": round(float(np.std(valid)), 2) if len(valid) > 1 else 0,
                "trend": "up" if len(valid) >= 2 and valid[-1] > valid[0] else
                         "down" if len(valid) >= 2 and valid[-1] < valid[0] else "flat",
            }

    return {
        "has_data": len(dates) > 1 and len(metrics) > 0,
        "dates": dates,
        "metrics": metrics,
    }


def _build_regulatory(result: dict) -> dict:
    """Regulatory compliance scorecard consolidating IRRBB, LCR/NSFR proxies, limits.

    Runs AFTER all other tab builders, reading from the result dict (like _build_alco).
    """
    checks = []

    # 1. IRRBB Outlier Test (BCBS 368: ΔEVE/Tier1 > 15% = outlier)
    eve = result.get("eve", {})
    if eve.get("has_data"):
        outlier = eve.get("outlier_test", {})
        if outlier:
            checks.append({
                "regulation": "IRRBB Outlier Test (BCBS 368)",
                "metric": "Worst \u0394EVE / Tier 1 Capital",
                "value": outlier.get("worst_pct", 0),
                "threshold": 15.0,
                "unit": "%",
                "status": outlier.get("status", "N/A"),
                "detail": f"Worst scenario: {outlier.get('worst_scenario', 'N/A')}",
            })
        else:
            # Derive from scenario data
            sc = eve.get("scenarios", {})
            if sc and sc.get("worst_delta"):
                checks.append({
                    "regulation": "IRRBB Outlier Test (BCBS 368)",
                    "metric": "Worst \u0394EVE",
                    "value": sc.get("worst_delta", 0),
                    "threshold": None,
                    "unit": "abs",
                    "status": "INFO",
                    "detail": f"Scenario: {sc.get('worst_scenario', '')}. Tier 1 capital not provided.",
                })

    # 2. NII Floor (supervisory: NII should not drop below floor under stress)
    nii_risk = result.get("nii_at_risk", {})
    summary = result.get("summary", {})
    base_nii = summary.get("kpis", {}).get("shock_0", {}).get("total", 0)
    if nii_risk.get("has_data"):
        wc = nii_risk.get("worst_case", {})
        worst_nii = base_nii + wc.get("delta", 0)
        checks.append({
            "regulation": "NII Floor (FINMA 2019/2)",
            "metric": "Worst-case NII",
            "value": round(float(worst_nii), 0),
            "threshold": 0,
            "unit": "abs",
            "status": "PASS" if worst_nii > 0 else "FAIL",
            "detail": f"Base NII {base_nii:,.0f} + \u0394NII {wc.get('delta', 0):,.0f} ({wc.get('scenario', '')})",
        })

    # 3. EVE Sensitivity (supervisory: ΔEVE under +/-200bp parallel shock)
    if eve.get("has_data"):
        sc = eve.get("scenarios", {})
        heatmap = sc.get("heatmap", []) if sc else []
        for row in heatmap:
            if row.get("scenario") in ("parallel_up", "parallel_down"):
                checks.append({
                    "regulation": f"EVE Sensitivity ({row['scenario']})",
                    "metric": "\u0394EVE",
                    "value": row.get("total", 0),
                    "threshold": None,
                    "unit": "abs",
                    "status": "INFO",
                    "detail": "BCBS 368 standard shock \u00b1200bp",
                })

    # 4. Duration Gap
    conv = eve.get("convexity", {}) if eve.get("has_data") else {}
    if conv:
        eff_dur = conv.get("effective_duration", 0)
        checks.append({
            "regulation": "Duration Risk",
            "metric": "Effective Duration",
            "value": round(float(eff_dur), 2),
            "threshold": 5.0,
            "unit": "Y",
            "status": "PASS" if abs(eff_dur) < 5 else "WATCH" if abs(eff_dur) < 7 else "FAIL",
            "detail": "Portfolio weighted effective duration",
        })

    # 5. LCR Proxy (HQLA / Net outflows 30d)
    liq = result.get("liquidity", {})
    if liq.get("has_data"):
        liq_sum = liq.get("summary", {})
        net_30d = liq_sum.get("net_30d", 0)
        # LCR = HQLA / max(net_outflows_30d, 0). We don't have HQLA here but
        # can show the net outflow coverage
        if net_30d < 0:
            checks.append({
                "regulation": "LCR Proxy (Liquidity Coverage)",
                "metric": "Net 30d Outflow",
                "value": round(float(net_30d), 0),
                "threshold": 0,
                "unit": "abs",
                "status": "FAIL",
                "detail": f"Net cash outflow of {net_30d:,.0f} in 30 days. Full LCR requires HQLA buffer.",
            })
        else:
            checks.append({
                "regulation": "LCR Proxy (Liquidity Coverage)",
                "metric": "Net 30d Position",
                "value": round(float(net_30d), 0),
                "threshold": 0,
                "unit": "abs",
                "status": "PASS",
                "detail": "Positive net cash position over 30 days",
            })

        # Survival horizon
        surv = liq_sum.get("survival_days")
        if surv is not None:
            checks.append({
                "regulation": "Liquidity Survival",
                "metric": "Days to deficit",
                "value": surv,
                "threshold": 30,
                "unit": "days",
                "status": "FAIL" if surv < 30 else "WATCH" if surv < 90 else "PASS",
                "detail": f"Cumulative gap turns negative at day {surv}",
            })

    # 6. Limit utilization summary
    limits_data = result.get("limits", {})
    if limits_data.get("has_data"):
        breaches = [i for i in limits_data.get("limit_items", []) if i.get("status") == "red"]
        warnings = [i for i in limits_data.get("limit_items", []) if i.get("status") == "yellow"]
        checks.append({
            "regulation": "Board-Approved Limits",
            "metric": "Limit Status",
            "value": len(breaches),
            "threshold": 0,
            "unit": "breaches",
            "status": "FAIL" if breaches else "WATCH" if warnings else "PASS",
            "detail": f"{len(breaches)} breach(es), {len(warnings)} warning(s) of "
                      f"{len(limits_data.get('limit_items', []))} limits",
        })

    # 7. Concentration
    cpty = result.get("counterparty_pnl", {})
    if cpty.get("has_data"):
        hhi = cpty.get("hhi", 0)
        checks.append({
            "regulation": "Concentration Risk",
            "metric": "P&L HHI",
            "value": round(float(hhi), 0),
            "threshold": 2500,
            "unit": "idx",
            "status": "PASS" if hhi < 1500 else "WATCH" if hhi < 2500 else "FAIL",
            "detail": "HHI < 1500 = low, 1500-2500 = moderate, >2500 = high concentration",
        })

    # Summary counts
    pass_count = sum(1 for c in checks if c["status"] == "PASS")
    watch_count = sum(1 for c in checks if c["status"] in ("WATCH", "INFO"))
    fail_count = sum(1 for c in checks if c["status"] in ("FAIL", "OUTLIER"))

    return {
        "has_data": len(checks) > 0,
        "checks": checks,
        "summary": {
            "pass": pass_count,
            "watch": watch_count,
            "fail": fail_count,
            "total": len(checks),
        },
    }
