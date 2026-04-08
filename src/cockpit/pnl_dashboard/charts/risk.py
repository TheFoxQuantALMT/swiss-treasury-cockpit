"""Risk chart data builders: Currency Mismatch, Repricing Gap, Counterparty, Alerts, EVE, Limits."""
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
from cockpit.pnl_dashboard.charts.helpers import _filter_total, _month_labels

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tab 8: Currency Mismatch (F9)
# ---------------------------------------------------------------------------

def _build_currency_mismatch(df: pd.DataFrame) -> dict:
    """Asset/liability gap by currency by month."""
    if df.empty:
        return {"has_data": False, "months": [], "by_currency": {}}

    nom_rows = df[(df["Indice"] == "Nominal") & (df["Shock"] == "0")].copy()
    if nom_rows.empty or "Direction" not in nom_rows.columns:
        return {"has_data": False, "months": [], "by_currency": {}}

    # Map direction to asset/liability: L(end)/B(uy) = asset, D(eposit)/S(ell) = liability
    nom_rows["_side"] = nom_rows["Direction"].map({"L": "asset", "B": "asset", "D": "liability", "S": "liability"})
    nom_rows["_side"] = nom_rows["_side"].fillna("asset")

    months = sorted(nom_rows["Month"].unique())
    month_labels = _month_labels(months)
    currencies = sorted(nom_rows["Deal currency"].unique()) if "Deal currency" in nom_rows.columns else []

    by_currency = {}
    for ccy in currencies:
        ccy_data = nom_rows[nom_rows["Deal currency"] == ccy]
        assets_by_month = ccy_data[ccy_data["_side"] == "asset"].groupby("Month")["Value"].sum()
        liab_by_month = ccy_data[ccy_data["_side"] == "liability"].groupby("Month")["Value"].sum()
        assets = [round(float(assets_by_month.get(m, 0)), 0) for m in months]
        liabs = [round(float(liab_by_month.get(m, 0)), 0) for m in months]
        gap = [a - l for a, l in zip(assets, liabs)]
        by_currency[ccy] = {"assets": assets, "liabilities": liabs, "gap": gap}

    # Net across all currencies
    all_assets = [sum(by_currency[c]["assets"][i] for c in currencies) for i in range(len(months))]
    all_liabs = [sum(by_currency[c]["liabilities"][i] for c in currencies) for i in range(len(months))]
    by_currency["All"] = {
        "assets": all_assets,
        "liabilities": all_liabs,
        "gap": [a - l for a, l in zip(all_assets, all_liabs)],
    }

    # Basis risk: OIS forward spread between currencies (e.g., EUR-CHF, USD-CHF)
    basis_risk = {}
    ois_rows = _filter_total(df[(df["Indice"] == "OISfwd") & (df["Shock"] == "0")])
    if not ois_rows.empty and "Deal currency" in ois_rows.columns:
        ois_by_ccy = {}
        for ccy in currencies:
            ccy_ois = ois_rows[ois_rows["Deal currency"] == ccy]
            # Nominal-weighted OIS per month
            nom_ccy = nom_rows[(nom_rows["Deal currency"] == ccy)]
            ois_monthly = ccy_ois.groupby("Month")["Value"].mean()
            ois_by_ccy[ccy] = {m: float(ois_monthly.get(m, 0)) for m in months}

        # Compute spreads relative to CHF (home currency)
        home = "CHF"
        if home in ois_by_ccy:
            for ccy in currencies:
                if ccy == home:
                    continue
                spread = []
                for m in months:
                    s = (ois_by_ccy.get(ccy, {}).get(m, 0) - ois_by_ccy[home].get(m, 0)) * 10_000
                    spread.append(round(s, 1))
                basis_risk[f"{ccy}-{home}"] = {
                    "values": spread,
                    "color": CURRENCY_COLORS.get(ccy, "#8b949e"),
                }

    return {"has_data": True, "months": month_labels, "by_currency": by_currency, "basis_risk": basis_risk}


# ---------------------------------------------------------------------------
# Tab 9: Repricing Gap (F3)
# ---------------------------------------------------------------------------

def _build_repricing_gap(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
) -> dict:
    """Repricing gap profile by bucket and currency."""
    if deals is None or deals.empty:
        return {"has_data": False, "buckets": [], "by_currency": {}}

    try:
        from pnl_engine.repricing import compute_repricing_gap
        gap_df = compute_repricing_gap(deals, pd.DataFrame(), date_run or datetime.now())
    except Exception as e:
        logger.warning(f"Repricing gap computation failed: {e}")
        return {"has_data": False, "buckets": [], "by_currency": {}}

    if gap_df.empty:
        return {"has_data": False, "buckets": [], "by_currency": {}}

    first_ccy = gap_df["currency"].dropna().iloc[0] if gap_df["currency"].notna().any() else None
    if first_ccy is None:
        return {"has_data": False, "buckets": [], "by_currency": {}}
    buckets = gap_df[gap_df["currency"] == first_ccy]["bucket"].tolist()

    by_currency = {}
    for ccy in sorted(gap_df["currency"].unique()):
        ccy_df = gap_df[gap_df["currency"] == ccy].sort_values("bucket_order")
        by_currency[ccy] = {
            "assets": [round(v, 0) for v in ccy_df["assets"].tolist()],
            "liabilities": [round(v, 0) for v in ccy_df["liabilities"].tolist()],
            "gap": [round(v, 0) for v in ccy_df["gap"].tolist()],
            "cumulative_gap": [round(v, 0) for v in ccy_df["cumulative_gap"].tolist()],
        }

    # Aggregate all currencies
    all_assets = [0.0] * len(buckets)
    all_liabs = [0.0] * len(buckets)
    for ccy_data in by_currency.values():
        for i in range(len(buckets)):
            all_assets[i] += ccy_data["assets"][i]
            all_liabs[i] += ccy_data["liabilities"][i]
    all_gap = [a - l for a, l in zip(all_assets, all_liabs)]
    cum = []
    running = 0
    for g in all_gap:
        running += g
        cum.append(round(running, 0))
    by_currency["All"] = {
        "assets": [round(v, 0) for v in all_assets],
        "liabilities": [round(v, 0) for v in all_liabs],
        "gap": [round(v, 0) for v in all_gap],
        "cumulative_gap": cum,
    }

    return {"has_data": True, "buckets": buckets, "by_currency": by_currency}


# ---------------------------------------------------------------------------
# Tab 10: Counterparty P&L Concentration (F8)
# ---------------------------------------------------------------------------

def _build_counterparty_pnl(df: pd.DataFrame, pnl_by_deal: Optional[pd.DataFrame] = None) -> dict:
    """P&L concentration by counterparty.

    Uses pnl_by_deal (deal-level summary) when available, since the aggregated
    pnlAllS drops Counterparty during pivot. Falls back to df if it has Counterparty.
    """
    empty = {"has_data": False, "top_10": [], "hhi": 0, "by_product": {}}

    # Prefer pnl_by_deal which preserves deal-level columns
    source = None
    if pnl_by_deal is not None and not pnl_by_deal.empty and "Counterparty" in pnl_by_deal.columns:
        source = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy()
        pnl_col = "PnL"
        cpty_col = "Counterparty"
        prod_col = "Product2BuyBack" if "Product2BuyBack" in source.columns else "Product"
    elif not df.empty and "Counterparty" in df.columns:
        source = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")].copy()
        pnl_col = "Value"
        cpty_col = "Counterparty"
        prod_col = "Product2BuyBack"
    else:
        return empty

    if source.empty:
        return empty

    # Group by counterparty
    cpty_pnl = source.groupby(cpty_col)[pnl_col].sum().reset_index()
    cpty_pnl.columns = ["Counterparty", "Value"]
    cpty_pnl["abs_val"] = cpty_pnl["Value"].abs()
    total = cpty_pnl["abs_val"].sum()

    if total == 0:
        return empty

    # HHI on PnL shares
    cpty_pnl["share_pct"] = (cpty_pnl["abs_val"] / total) * 100
    hhi = float((cpty_pnl["share_pct"] ** 2).sum())

    # Top 10
    top = cpty_pnl.nlargest(10, "abs_val")
    top_10 = []
    for _, row in top.iterrows():
        top_10.append({
            "counterparty": str(row["Counterparty"]),
            "pnl": round(float(row["Value"]), 0),
            "pct": round(float(row["share_pct"]), 1),
        })

    # Product breakdown
    by_product = {}
    if prod_col in source.columns:
        prod_pnl = source.groupby(prod_col)[pnl_col].sum()
        for prod, val in prod_pnl.items():
            by_product[str(prod)] = {
                "value": round(float(val), 0),
                "color": PRODUCT_COLORS.get(str(prod), "#8b949e"),
            }

    return {"has_data": True, "top_10": top_10, "hhi": round(hhi, 0), "by_product": by_product}


# ---------------------------------------------------------------------------
# Tab 11: P&L Alerts (F7)
# ---------------------------------------------------------------------------

def _build_pnl_alerts(df: pd.DataFrame, alert_thresholds: Optional[dict] = None) -> dict:
    """Generate P&L alerts from data."""
    if df.empty:
        return {"has_data": False, "alerts": [], "summary": {"critical": 0, "high": 0, "medium": 0}}

    from cockpit.engine.alerts.pnl_alerts import check_pnl_alerts

    # Build thresholds dict with per-currency support
    thresholds = None
    if alert_thresholds:
        thresholds = dict(alert_thresholds.get("ALL", {}))
        per_ccy = {k: v for k, v in alert_thresholds.items() if k != "ALL"}
        if per_ccy:
            thresholds["_per_currency"] = per_ccy

    alerts = check_pnl_alerts(df, thresholds)

    summary = {"critical": 0, "high": 0, "medium": 0}
    for a in alerts:
        sev = a.get("severity", "medium")
        if sev in summary:
            summary[sev] += 1

    return {"has_data": len(alerts) > 0, "alerts": alerts, "summary": summary}


# ---------------------------------------------------------------------------
# Tab 17: EVE (Economic Value of Equity)
# ---------------------------------------------------------------------------

def _build_eve(
    eve_results: Optional[pd.DataFrame] = None,
    eve_scenarios: Optional[pd.DataFrame] = None,
    eve_krd: Optional[pd.DataFrame] = None,
    limits: Optional[pd.DataFrame] = None,
) -> dict:
    """Build EVE dashboard data: base EVE, ΔEVE heatmap, duration, KRD, IRRBB outlier test."""
    if eve_results is None or eve_results.empty:
        return {"has_data": False, "total_eve": 0, "by_currency": {},
                "scenarios": {}, "krd": {}, "duration": {}}

    # --- Total EVE and by currency ---
    total_eve = round(float(eve_results["eve"].sum()), 0)
    ccy_col = "Currency" if "Currency" in eve_results.columns else None
    by_currency = {}
    if ccy_col:
        for ccy, grp in eve_results.groupby(ccy_col):
            by_currency[ccy] = {
                "eve": round(float(grp["eve"].sum()), 0),
                "duration": round(float(
                    (grp["duration"].fillna(0) * grp["notional_avg"].fillna(0)).sum() /
                    max(grp["notional_avg"].fillna(0).sum(), 1e-6)
                ), 2),
                "deal_count": len(grp),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # --- Scenario ΔEVE heatmap ---
    scenarios_data = {}
    if eve_scenarios is not None and not eve_scenarios.empty:
        scenario_names = sorted(eve_scenarios["scenario"].unique())
        currencies = sorted(eve_scenarios["currency"].unique())
        heatmap = []
        for sc in scenario_names:
            row = {"scenario": sc}
            sc_data = eve_scenarios[eve_scenarios["scenario"] == sc]
            for ccy in currencies:
                ccy_row = sc_data[sc_data["currency"] == ccy]
                if not ccy_row.empty:
                    row[ccy] = round(float(ccy_row.iloc[0]["delta_eve"]), 0)
                else:
                    row[ccy] = 0
            row["total"] = sum(row.get(c, 0) for c in currencies)
            heatmap.append(row)

        # Worst case
        totals = {sc: sum(
            eve_scenarios.loc[eve_scenarios["scenario"] == sc, "delta_eve"]
        ) for sc in scenario_names}
        worst_sc = min(totals, key=totals.get) if totals else ""
        worst_delta = round(float(totals.get(worst_sc, 0)), 0)

        scenarios_data = {
            "scenario_names": scenario_names,
            "currencies": currencies,
            "heatmap": heatmap,
            "worst_scenario": worst_sc,
            "worst_delta": worst_delta,
            "eve_base_total": total_eve,
        }

    # --- KRD chart data ---
    krd_data = {}
    if eve_krd is not None and not eve_krd.empty:
        tenors = sorted(eve_krd["tenor_years"].unique())
        tenor_labels = []
        for _, row in eve_krd.drop_duplicates("tenor").sort_values("tenor_years").iterrows():
            tenor_labels.append(row["tenor"])
        currencies_krd = sorted(eve_krd["currency"].unique())
        datasets = []
        for ccy in currencies_krd:
            ccy_krd = eve_krd[eve_krd["currency"] == ccy].sort_values("tenor_years")
            datasets.append({
                "label": ccy,
                "data": [round(float(v), 4) for v in ccy_krd["krd"].values],
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            })
        krd_data = {
            "tenors": tenor_labels,
            "datasets": datasets,
        }

    # --- Duration profile ---
    duration_data = {}
    if ccy_col:
        dur_labels = []
        dur_values = []
        dur_colors = []
        for ccy in sorted(by_currency.keys()):
            dur_labels.append(str(ccy))
            dur_values.append(by_currency[ccy]["duration"])
            dur_colors.append(by_currency[ccy]["color"])
        duration_data = {"labels": dur_labels, "values": dur_values, "colors": dur_colors}

    # --- EVE Tenor Ladder (bucket by deal maturity into BCBS tenor bands) ---
    tenor_ladder = {}
    if ccy_col and "duration" in eve_results.columns:
        # BCBS tenor buckets based on modified duration as proxy for maturity
        tenor_buckets = [
            ("O/N", 0, 0.01),
            ("\u22643M", 0.01, 0.25),
            ("3M-6M", 0.25, 0.5),
            ("6M-1Y", 0.5, 1.0),
            ("1Y-2Y", 1.0, 2.0),
            ("2Y-3Y", 2.0, 3.0),
            ("3Y-5Y", 3.0, 5.0),
            ("5Y-10Y", 5.0, 10.0),
            ("10Y-20Y", 10.0, 20.0),
            (">20Y", 20.0, 999.0),
        ]
        bucket_labels = [b[0] for b in tenor_buckets]
        currencies_in_eve = sorted(by_currency.keys())
        datasets = []
        for ccy in currencies_in_eve:
            ccy_deals = eve_results[eve_results[ccy_col] == ccy]
            bucket_values = []
            for _, lo, hi in tenor_buckets:
                mask = (ccy_deals["duration"] >= lo) & (ccy_deals["duration"] < hi)
                bucket_values.append(round(float(ccy_deals.loc[mask, "eve"].sum()), 0))
            datasets.append({
                "label": str(ccy),
                "data": bucket_values,
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            })
        tenor_ladder = {"buckets": bucket_labels, "datasets": datasets}

    # --- IRRBB Outlier Test (BCBS 368: ΔEVE / Tier1 > 15% = outlier) ---
    outlier_test = None
    tier1 = None
    if limits is not None and not limits.empty:
        t1_rows = limits[limits["metric"].str.strip() == "tier1_capital"]
        if not t1_rows.empty:
            tier1 = float(t1_rows.iloc[0]["limit_value"])

    outlier_warning = None
    if tier1 and tier1 > 0 and scenarios_data:
        outlier_rows = []
        worst_pct = 0.0
        is_outlier = False
        for row in scenarios_data.get("heatmap", []):
            delta = abs(float(row.get("total", 0)))
            pct_of_t1 = (delta / tier1) * 100
            passed = pct_of_t1 <= 15.0
            if pct_of_t1 > worst_pct:
                worst_pct = pct_of_t1
            if not passed:
                is_outlier = True
            outlier_rows.append({
                "scenario": row["scenario"],
                "delta_eve": round(float(row.get("total", 0)), 0),
                "pct_of_tier1": round(pct_of_t1, 2),
                "passed": passed,
            })
        outlier_test = {
            "tier1_capital": round(tier1, 0),
            "threshold_pct": 15.0,
            "is_outlier": is_outlier,
            "worst_pct": round(worst_pct, 2),
            "scenarios": outlier_rows,
        }
    elif scenarios_data and scenarios_data.get("heatmap") and (tier1 is None or tier1 <= 0):
        outlier_warning = "IRRBB outlier test skipped: Tier 1 capital not provided in limits.xlsx"

    # --- Convexity / Gamma measurement from parallel scenarios ---
    convexity = None
    if scenarios_data and scenarios_data.get("heatmap"):
        hm = scenarios_data["heatmap"]
        # Find parallel_up and parallel_down scenarios
        up_row = next((r for r in hm if "parallel" in r["scenario"].lower() and "up" in r["scenario"].lower()), None)
        down_row = next((r for r in hm if "parallel" in r["scenario"].lower() and "down" in r["scenario"].lower()), None)
        if up_row and down_row and total_eve != 0:
            delta_r = 0.02  # 200bp standard parallel shock
            delta_eve_up = float(up_row.get("total", 0))
            delta_eve_down = float(down_row.get("total", 0))
            # Duration = -ΔEVE / (EVE x Δr), using average of up/down
            eff_duration = -(delta_eve_up - delta_eve_down) / (2 * total_eve * delta_r)
            # Convexity = (ΔEVE_up + ΔEVE_down) / (EVE x Δr^2)
            eff_convexity = (delta_eve_up + delta_eve_down) / (total_eve * delta_r ** 2)
            # Per-currency convexity
            ccy_convexity = []
            currencies_sc = scenarios_data.get("currencies", [])
            for ccy in currencies_sc:
                ccy_eve = by_currency.get(ccy, {}).get("eve", 0)
                if ccy_eve == 0:
                    continue
                ccy_up = float(up_row.get(ccy, 0))
                ccy_down = float(down_row.get(ccy, 0))
                ccy_dur = -(ccy_up - ccy_down) / (2 * ccy_eve * delta_r)
                ccy_conv = (ccy_up + ccy_down) / (ccy_eve * delta_r ** 2)
                ccy_convexity.append({
                    "currency": ccy,
                    "eve": round(ccy_eve, 0),
                    "delta_eve_up": round(ccy_up, 0),
                    "delta_eve_down": round(ccy_down, 0),
                    "effective_duration": round(ccy_dur, 2),
                    "convexity": round(ccy_conv, 2),
                    "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
                })
            convexity = {
                "delta_eve_up": round(delta_eve_up, 0),
                "delta_eve_down": round(delta_eve_down, 0),
                "effective_duration": round(eff_duration, 2),
                "convexity": round(eff_convexity, 2),
                "by_currency": ccy_convexity,
            }

    # --- DV01/PV01 Ladder (sensitivity per 1bp per tenor bucket) ---
    dv01 = None
    if convexity and total_eve != 0:
        # DV01 = ΔEVE per 1bp = Effective Duration x EVE x 0.0001
        total_dv01 = abs(convexity["effective_duration"]) * abs(total_eve) * 0.0001
        dv01_by_ccy = []
        for cc in (convexity.get("by_currency") or []):
            ccy_dv01 = abs(cc["effective_duration"]) * abs(cc["eve"]) * 0.0001
            dv01_by_ccy.append({
                "currency": cc["currency"],
                "eve": cc["eve"],
                "duration": cc["effective_duration"],
                "dv01": round(ccy_dv01, 0),
                "color": cc.get("color", "#8b949e"),
            })
        dv01 = {
            "total_dv01": round(total_dv01, 0),
            "by_currency": dv01_by_ccy,
        }

    return {
        "has_data": True,
        "total_eve": total_eve,
        "by_currency": by_currency,
        "scenarios": scenarios_data,
        "krd": krd_data,
        "duration": duration_data,
        "outlier_test": outlier_test,
        "outlier_warning": outlier_warning,
        "tenor_ladder": tenor_ladder,
        "convexity": convexity,
        "dv01": dv01,
    }


# ---------------------------------------------------------------------------
# Limit Utilization
# ---------------------------------------------------------------------------

def _build_limit_utilization(
    df: pd.DataFrame,
    limits: Optional[pd.DataFrame] = None,
    eve_data: Optional[dict] = None,
    nii_at_risk_data: Optional[dict] = None,
) -> dict:
    """Compute limit utilization bars for dashboard display.

    Matches actual metric values against board-approved limits.
    """
    if limits is None or limits.empty:
        return {"has_data": False, "limit_items": []}

    items = []

    for _, lim in limits.iterrows():
        metric = str(lim["metric"]).strip()
        currency = str(lim.get("currency", "ALL")).strip().upper()
        limit_value = float(lim["limit_value"]) if pd.notna(lim["limit_value"]) else None
        warning_pct = float(lim.get("warning_pct", 80.0))

        if limit_value is None or limit_value == 0:
            continue

        actual = None
        label = metric.replace("_", " ").title()

        # Calculate actual values based on metric type
        if metric == "nii_sensitivity_50bp" and not df.empty:
            pnl_0 = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")]
            pnl_50 = df[(df["Indice"] == "PnL") & (df["Shock"] == "50")]
            if currency != "ALL":
                pnl_0 = pnl_0[pnl_0["Deal currency"] == currency]
                pnl_50 = pnl_50[pnl_50["Deal currency"] == currency]
            nii_0 = pnl_0["Value"].sum() if not pnl_0.empty else 0
            nii_50 = pnl_50["Value"].sum() if not pnl_50.empty else 0
            actual = abs(nii_50 - nii_0)
            label = f"NII Sensitivity +50bp" + (f" ({currency})" if currency != "ALL" else "")

        elif metric == "nii_at_risk_worst" and nii_at_risk_data:
            wc = nii_at_risk_data.get("worst_case", {})
            actual = abs(float(wc.get("delta", 0)))
            label = "NII-at-Risk (Worst)"

        elif metric == "eve_change_200bp" and eve_data:
            sc = eve_data.get("scenarios", {})
            if sc:
                for row in sc.get("heatmap", []):
                    if "parallel_up" in row.get("scenario", ""):
                        actual = abs(float(row.get("total", 0)))
                        break
            label = "EVE Change +200bp"

        elif metric == "eve_change_worst" and eve_data:
            sc = eve_data.get("scenarios", {})
            actual = abs(float(sc.get("worst_delta", 0))) if sc else None
            label = "EVE Change (Worst)"

        if actual is None:
            continue

        utilization_pct = (actual / abs(limit_value)) * 100
        status = "green"
        if utilization_pct >= 100:
            status = "red"
        elif utilization_pct >= warning_pct:
            status = "yellow"

        items.append({
            "metric": metric,
            "label": label,
            "currency": currency,
            "actual": round(float(actual), 0),
            "limit": round(float(limit_value), 0),
            "utilization_pct": round(float(utilization_pct), 1),
            "warning_pct": warning_pct,
            "status": status,
        })

    # Build breach log: items currently breaching or in warning zone
    breaches = [it for it in items if it["status"] == "red"]
    warnings = [it for it in items if it["status"] == "yellow"]
    breach_log = {
        "breach_count": len(breaches),
        "warning_count": len(warnings),
        "breaches": breaches,
        "warnings": warnings,
    }

    return {"has_data": len(items) > 0, "limit_items": items, "breach_log": breach_log}
