"""Attribution chart data builders: FTP, Liquidity, NMD Audit, ALCO, Budget, Attribution, Forecast Tracking."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from cockpit.pnl_dashboard.charts.constants import (
    CURRENCY_COLORS,
    PRODUCT_COLORS,
    PERIMETER_COLORS,
)
from cockpit.pnl_dashboard.charts.helpers import (
    _filter_total,
    _month_labels,
    _safe_stacked,
    safe_float as _safe_float,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FTP & Business Unit P&L
# ---------------------------------------------------------------------------

def _build_ftp(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
) -> dict:
    """FTP margin decomposition by perimeter and currency.

    3-way split: Client Margin (ClientRate - FTP), ALM Margin (FTP - OIS),
    Total NII (ClientRate - OIS).
    """
    if deals is None or deals.empty or "FTP" not in deals.columns:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    ftp_deals = deals[deals["FTP"].notna() & (deals["FTP"] != 0)].copy()
    if ftp_deals.empty:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    # Use pnl_by_deal for deal-level P&L if available
    source = None
    if pnl_by_deal is not None and not pnl_by_deal.empty and "Dealid" in pnl_by_deal.columns:
        source = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy()

    # Compute per-deal FTP metrics
    records = []
    for _, deal in ftp_deals.iterrows():
        deal_id = deal.get("Dealid")
        ccy = str(deal.get("Currency", ""))
        perimeter = str(deal.get("P\u00e9rim\u00e8tre TOTAL", "CC"))
        product = str(deal.get("Product", ""))
        counterparty = str(deal.get("Counterparty", ""))
        client_rate = _safe_float(deal.get("Clientrate", 0))
        ftp_rate = _safe_float(deal.get("FTP", 0))
        eq_ois = _safe_float(deal.get("EqOisRate", 0))
        ytm = _safe_float(deal.get("YTM", 0))
        amount = _safe_float(deal.get("Amount", 0))

        # Rate used for OIS comparison depends on product
        ref_rate = ytm if product == "BND" else eq_ois

        # Margins in bps
        client_margin_bps = (client_rate - ftp_rate) * 10_000
        alm_margin_bps = (ftp_rate - ref_rate) * 10_000

        # Remaining maturity fraction (cap at 1.0 for annualized view)
        year_frac = 1.0
        mat_raw = deal.get("Maturity Date", deal.get("Maturitydate"))
        if mat_raw is not None and date_run is not None:
            try:
                mat_dt = pd.Timestamp(mat_raw)
                if pd.notna(mat_dt):
                    remaining = (mat_dt - pd.Timestamp(date_run)).days
                    year_frac = min(max(remaining / 365.0, 0.0), 1.0)
            except (ValueError, TypeError):
                pass

        # P&L contribution pro-rated by remaining maturity (capped at 12 months)
        client_margin_pnl = amount * (client_rate - ftp_rate) * year_frac
        alm_margin_pnl = amount * (ftp_rate - ref_rate) * year_frac
        total_nii = client_margin_pnl + alm_margin_pnl

        # Get actual P&L from engine if available
        actual_pnl = 0.0
        if source is not None:
            match = source[source["Dealid"] == deal_id]
            if not match.empty:
                actual_pnl = float(match["PnL"].sum())

        # ALM margin decomposition (duration / credit / liquidity)
        # Duration contribution: FTP captures term premium over overnight
        # Approximate OIS overnight as the first OIS rate available (or 0)
        ois_overnight = float(deal.get("EqOisRate", 0) or 0)  # proxy
        duration_contrib_bps = (ftp_rate - ois_overnight) * 10_000 if ftp_rate > ois_overnight else 0.0

        # Liquidity premium: product-specific funding spread
        try:
            from pnl_engine.config import FUNDING_SPREAD_BY_PRODUCT
            liq_spread = FUNDING_SPREAD_BY_PRODUCT.get(product, 0.0)
        except ImportError:
            liq_spread = 0.0
        liquidity_premium_bps = abs(liq_spread) * 10_000  # stored as negative in config

        # Credit spread: residual after duration and liquidity
        credit_spread_bps = alm_margin_bps - duration_contrib_bps - liquidity_premium_bps

        records.append({
            "deal_id": str(deal_id).split(".")[0] if pd.notna(deal_id) else "",
            "currency": ccy,
            "perimeter": perimeter,
            "product": product,
            "counterparty": counterparty,
            "amount": round(amount, 0),
            "client_rate": round(client_rate * 100, 4),
            "ftp_rate": round(ftp_rate * 100, 4),
            "ref_rate": round(ref_rate * 100, 4),
            "client_margin_bps": round(client_margin_bps, 1),
            "alm_margin_bps": round(alm_margin_bps, 1),
            "duration_contribution_bps": round(duration_contrib_bps, 1),
            "credit_spread_bps": round(credit_spread_bps, 1),
            "liquidity_premium_bps": round(liquidity_premium_bps, 1),
            "client_margin_pnl": round(client_margin_pnl, 0),
            "alm_margin_pnl": round(alm_margin_pnl, 0),
            "total_nii": round(total_nii, 0),
            "actual_pnl": round(actual_pnl, 0),
        })

    if not records:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    rdf = pd.DataFrame(records)

    # Aggregate by perimeter
    perimeters = {}
    for peri, grp in rdf.groupby("perimeter"):
        perimeters[str(peri)] = {
            "client_margin": round(float(grp["client_margin_pnl"].sum()), 0),
            "alm_margin": round(float(grp["alm_margin_pnl"].sum()), 0),
            "total_nii": round(float(grp["total_nii"].sum()), 0),
            "deal_count": len(grp),
            "avg_client_margin_bps": round(float(grp["client_margin_bps"].mean()), 1),
            "avg_alm_margin_bps": round(float(grp["alm_margin_bps"].mean()), 1),
            "color": PERIMETER_COLORS.get(str(peri), "#8b949e"),
        }

    # Aggregate by currency
    by_currency = {}
    for ccy, grp in rdf.groupby("currency"):
        by_currency[str(ccy)] = {
            "client_margin": round(float(grp["client_margin_pnl"].sum()), 0),
            "alm_margin": round(float(grp["alm_margin_pnl"].sum()), 0),
            "total_nii": round(float(grp["total_nii"].sum()), 0),
            "deal_count": len(grp),
            "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
        }

    # Top 10 deals by absolute FTP margin (contributors + detractors)
    rdf["abs_alm_margin"] = rdf["alm_margin_pnl"].abs()
    top = rdf.nlargest(10, "abs_alm_margin").drop(columns=["abs_alm_margin"])
    top_deals = top.to_dict("records")

    # Totals
    total_client = round(float(rdf["client_margin_pnl"].sum()), 0)
    total_alm = round(float(rdf["alm_margin_pnl"].sum()), 0)
    total_nii = round(float(rdf["total_nii"].sum()), 0)

    # FTP ALM margin decomposition (aggregated)
    ftp_decomposition = {}
    if "duration_contribution_bps" in rdf.columns:
        ftp_decomposition = {
            "duration_contribution_bps": round(float(rdf["duration_contribution_bps"].mean()), 1),
            "credit_spread_bps": round(float(rdf["credit_spread_bps"].mean()), 1),
            "liquidity_premium_bps": round(float(rdf["liquidity_premium_bps"].mean()), 1),
            "avg_alm_margin_bps": round(float(rdf["alm_margin_bps"].mean()), 1),
        }

    result = {
        "has_data": True,
        "totals": {
            "client_margin": total_client,
            "alm_margin": total_alm,
            "total_nii": total_nii,
            "deal_count": len(rdf),
        },
        "perimeters": perimeters,
        "by_currency": by_currency,
        "top_deals": top_deals,
    }
    if ftp_decomposition:
        result["ftp_decomposition"] = ftp_decomposition
    return result


# ---------------------------------------------------------------------------
# Liquidity Forecast
# ---------------------------------------------------------------------------

def _build_liquidity(
    liquidity_schedule: Optional[pd.DataFrame] = None,
    deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Liquidity forecast from daily/monthly cash flow schedule.

    Input: wide DataFrame with Dealid, Direction, Currency, and date columns
    (YYYY/MM or YYYY/MM/DD) containing cash flow amounts.
    """
    if liquidity_schedule is None or liquidity_schedule.empty:
        return {"has_data": False, "by_currency": {}, "summary": {}, "top_maturities": []}

    df = liquidity_schedule.copy()
    date_col_re = re.compile(r"^\d{4}/\d{2}(/\d{2})?$")
    date_cols = [c for c in df.columns if isinstance(c, str) and date_col_re.match(c)]

    if not date_cols:
        return {"has_data": False, "by_currency": {}, "summary": {}, "top_maturities": []}

    # Parse date columns to timestamps for aggregation
    def _parse_col(c):
        parts = c.split("/")
        if len(parts) == 3:
            return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
        return pd.Timestamp(int(parts[0]), int(parts[1]), 1)

    col_dates = {c: _parse_col(c) for c in date_cols}
    sorted_cols = sorted(date_cols, key=lambda c: col_dates[c])

    # Identify asset vs liability by direction
    # L(oan)/B(ond) = asset (negative nominal), D(eposit)/S(ell bond) = liability (positive nominal)
    from pnl_engine.config import ASSET_DIRECTIONS
    if "Direction" in df.columns:
        df["_is_asset"] = df["Direction"].isin(ASSET_DIRECTIONS)
    else:
        df["_is_asset"] = True  # default

    currencies = sorted(df["Currency"].unique()) if "Currency" in df.columns else ["ALL"]

    # Build per-currency time series
    by_currency = {}
    for ccy in currencies:
        ccy_df = df[df["Currency"] == ccy] if "Currency" in df.columns else df

        labels = []
        inflows = []
        outflows = []
        net = []
        cumulative = []
        cum = 0.0

        for col in sorted_cols:
            dt = col_dates[col]
            labels.append(dt.strftime("%Y-%m-%d") if "/" in col and col.count("/") == 2 else dt.strftime("%Y-%m"))

            # Assets (L/B): principal returning = inflow; Liabilities (D/S): repayment = outflow
            inflow = float(ccy_df.loc[ccy_df["_is_asset"], col].sum())
            outflow = float(-ccy_df.loc[~ccy_df["_is_asset"], col].sum())  # negate: unsigned -> negative

            inflows.append(round(float(inflow), 0))
            outflows.append(round(float(outflow), 0))
            n = round(float(inflow + outflow), 0)
            net.append(n)
            cum += n
            cumulative.append(round(float(cum), 0))

        by_currency[ccy] = {
            "labels": labels,
            "inflows": inflows,
            "outflows": outflows,
            "net": net,
            "cumulative": cumulative,
            "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
        }

    # Summary KPIs: aggregate across all currencies
    all_labels = []
    all_net = []
    cum = 0.0
    all_cumulative = []
    for col in sorted_cols:
        dt = col_dates[col]
        all_labels.append(dt)
        n = float(df[col].sum())
        all_net.append(n)
        cum += n
        all_cumulative.append(cum)

    # Net outflows for 7d, 30d, 90d windows
    now = pd.Timestamp.now()
    net_7d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=7))
    net_30d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=30))
    net_90d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=90))

    # Survival days: first date where cumulative goes negative
    survival_days = None
    for dt, c in zip(all_labels, all_cumulative):
        if c < 0:
            survival_days = max(0, (dt - now).days)
            break

    # Top 10 largest single-date cash flows (maturities) in next 30 days
    top_maturities = []
    for _, row in df.iterrows():
        for col in sorted_cols:
            dt = col_dates[col]
            if dt > now + pd.Timedelta(days=30):
                break
            val = float(row[col])
            if abs(val) > 0:
                top_maturities.append({
                    "deal_id": str(int(row["Dealid"])) if pd.notna(row.get("Dealid")) else "",
                    "currency": str(row.get("Currency", "")),
                    "direction": str(row.get("Direction", "")),
                    "date": dt.strftime("%Y-%m-%d"),
                    "amount": round(val, 0),
                })

    # Sort by absolute amount descending, keep top 10
    top_maturities.sort(key=lambda x: abs(x["amount"]), reverse=True)
    top_maturities = top_maturities[:10]

    # Reinvestment what-if: maturing assets in 30/90d, book rate vs current OIS
    reinvestment = []
    if deals is not None and not deals.empty and "Currency" in deals.columns:
        ois_col = "EqOisRate"
        rate_col = "Clientrate"
        for _ois in [ois_col, "EqOISRate", "eqoisrate"]:
            if _ois in deals.columns:
                ois_col = _ois
                break
        if ois_col in deals.columns and rate_col in deals.columns:
            asset_mask = deals.get("Direction", pd.Series()).isin(ASSET_DIRECTIONS)
            asset_deals = deals[asset_mask].copy()
            for ccy in currencies:
                ccy_deals = asset_deals[asset_deals["Currency"] == ccy]
                if ccy_deals.empty:
                    continue
                avg_book = float(ccy_deals[rate_col].mean()) if not ccy_deals[rate_col].isna().all() else 0
                avg_ois = float(ccy_deals[ois_col].mean()) if not ccy_deals[ois_col].isna().all() else 0
                # Volume maturing in 30d/90d (from top_maturities)
                vol_30d = sum(abs(m["amount"]) for m in top_maturities if m["currency"] == ccy and m["direction"] in ASSET_DIRECTIONS)
                if vol_30d > 0 and avg_ois != 0:
                    spread_bps = (avg_ois - avg_book) * 10_000
                    nii_impact = vol_30d * (avg_ois - avg_book)
                    reinvestment.append({
                        "currency": ccy,
                        "maturing_volume": round(vol_30d, 0),
                        "book_rate_pct": round(avg_book * 100, 4),
                        "market_rate_pct": round(avg_ois * 100, 4),
                        "spread_bps": round(spread_bps, 1),
                        "nii_impact": round(nii_impact, 0),
                    })

    return {
        "has_data": True,
        "by_currency": by_currency,
        "all_currencies": currencies,
        "summary": {
            "net_7d": round(float(net_7d), 0),
            "net_30d": round(float(net_30d), 0),
            "net_90d": round(float(net_90d), 0),
            "survival_days": survival_days,
        },
        "top_maturities": top_maturities,
        "reinvestment": reinvestment,
    }


# ---------------------------------------------------------------------------
# NMD Audit Trail
# ---------------------------------------------------------------------------

def _build_nmd_audit(
    deals: Optional[pd.DataFrame],
    nmd_profiles: Optional[pd.DataFrame],
) -> dict:
    """Build NMD matching audit trail for dashboard display.

    Shows which deals matched which NMD profile tier, with key parameters.
    """
    if deals is None or nmd_profiles is None or nmd_profiles.empty:
        return {"has_data": False}

    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    match_log = []
    for i in range(len(deals)):
        deal = deals.iloc[i]
        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        product = str(deal.get("Product", "")).strip().upper()
        currency = str(deal.get("Currency", "")).strip().upper()
        direction = str(deal.get("Direction", "")).strip().upper()
        nominal = float(deal.get("Nominal", 0))

        mask = pd.Series([True] * len(profiles))
        if "product" in profiles.columns:
            mask &= profiles["product"] == product
        if "currency" in profiles.columns:
            mask &= profiles["currency"] == currency
        if "direction" in profiles.columns:
            mask &= profiles["direction"] == direction

        matched = profiles[mask]
        if matched.empty:
            continue

        profile = matched.iloc[0]
        tier = str(profile.get("tier", "unknown"))
        decay_rate = float(profile.get("decay_rate", 0.0))
        deposit_beta = float(profile.get("deposit_beta", 1.0))
        floor_rate = float(profile.get("floor_rate", 0.0))
        behavioral_maturity = float(profile.get("behavioral_maturity_years", 0.0))

        match_log.append({
            "deal_id": deal_id,
            "product": product,
            "currency": currency,
            "direction": direction,
            "nominal": nominal,
            "tier": tier,
            "decay_rate": decay_rate,
            "deposit_beta": deposit_beta,
            "floor_rate": floor_rate,
            "behavioral_maturity_years": behavioral_maturity,
        })

    if not match_log:
        return {"has_data": False}

    match_df = pd.DataFrame(match_log)

    # Summary by tier
    tier_summary = []
    for tier, grp in match_df.groupby("tier"):
        tier_summary.append({
            "tier": tier,
            "deal_count": len(grp),
            "total_nominal": float(grp["nominal"].sum()),
            "avg_decay_rate": float(grp["decay_rate"].mean()),
            "avg_beta": float(grp["deposit_beta"].mean()),
            "avg_behavioral_maturity": float(grp["behavioral_maturity_years"].mean()),
        })

    # Summary by currency x tier
    ccy_tier_summary = []
    for (ccy, tier), grp in match_df.groupby(["currency", "tier"]):
        ccy_tier_summary.append({
            "currency": ccy,
            "tier": tier,
            "deal_count": len(grp),
            "total_nominal": float(grp["nominal"].sum()),
            "avg_beta": float(grp["deposit_beta"].mean()),
        })

    # Chart data: stacked bar by currency, colored by tier
    tier_colors = {
        "CORE": "#3fb950",
        "VOLATILE": "#d29922",
        "TERM": "#58a6ff",
    }
    currencies = sorted(match_df["currency"].unique())
    tiers = sorted(match_df["tier"].unique())
    chart_datasets = []
    for tier in tiers:
        data = []
        for ccy in currencies:
            sub = match_df[(match_df["currency"] == ccy) & (match_df["tier"] == tier)]
            data.append(float(sub["nominal"].sum()))
        chart_datasets.append({
            "label": tier.title(),
            "data": data,
            "color": tier_colors.get(tier, "#8b949e"),
        })

    # Unmatched deals count
    total_deals = len(deals)
    matched_deals = len(match_log)
    unmatched_deals = total_deals - matched_deals

    # Deal-level detail (first 50 for display)
    deal_details = match_log[:50]

    return {
        "has_data": True,
        "total_deals": total_deals,
        "matched_deals": matched_deals,
        "unmatched_deals": unmatched_deals,
        "tier_summary": tier_summary,
        "ccy_tier_summary": ccy_tier_summary,
        "chart": {
            "currencies": currencies,
            "datasets": chart_datasets,
        },
        "deal_details": deal_details,
        "profiles": [
            {
                "product": str(r.get("product", "")),
                "currency": str(r.get("currency", "")),
                "direction": str(r.get("direction", "")),
                "tier": str(r.get("tier", "")),
                "decay_rate": float(r.get("decay_rate", 0)),
                "deposit_beta": float(r.get("deposit_beta", 1)),
                "floor_rate": float(r.get("floor_rate", 0)),
                "behavioral_maturity_years": float(r.get("behavioral_maturity_years", 0)),
            }
            for _, r in nmd_profiles.iterrows()
        ],
    }


# ---------------------------------------------------------------------------
# ALCO Risk Summary (reads from all other tabs)
# ---------------------------------------------------------------------------

def _build_alco(result: dict) -> dict:
    """Single-screen ALCO risk dashboard consolidating all key metrics.

    This runs AFTER all other tab builders, reading from the result dict.
    """
    metrics = []
    lim_items = result.get("limits", {}).get("limit_items", [])

    # 1. Total NII (base)
    summary = result.get("summary", {})
    kpis = summary.get("kpis", {})
    shock_0 = kpis.get("shock_0", {})
    if shock_0:
        dod = summary.get("dod_bridge", [])
        total_row = next((r for r in (dod or []) if r["currency"] == "Total"), None)
        metrics.append({
            "metric": "Total NII (Base)",
            "value": shock_0.get("total", 0),
            "delta_1d": total_row["delta"] if total_row else None,
            "limit": None,
            "utilization": None,
            "status": "neutral",
        })

    # 2. NII Sensitivity (+50bp)
    delta_50 = kpis.get("delta_50_0", 0)
    if delta_50 != 0:
        nii_sens_lim = next((i for i in lim_items if i["metric"] == "nii_sensitivity_50bp"), None)
        metrics.append({
            "metric": "NII Sensitivity (+50bp)",
            "value": delta_50,
            "delta_1d": None,
            "limit": nii_sens_lim["limit"] if nii_sens_lim else None,
            "utilization": nii_sens_lim["utilization_pct"] if nii_sens_lim else None,
            "status": nii_sens_lim["status"] if nii_sens_lim else "neutral",
        })

    # 3. Worst ΔNII (BCBS scenarios)
    nii_risk = result.get("nii_at_risk", {})
    if nii_risk.get("has_data"):
        wc = nii_risk.get("worst_case", {})
        nii_risk_lim = next((i for i in lim_items if i["metric"] == "nii_at_risk_worst"), None)
        metrics.append({
            "metric": f"Worst \u0394NII ({wc.get('scenario', '')})",
            "value": wc.get("delta", 0),
            "delta_1d": None,
            "limit": nii_risk_lim["limit"] if nii_risk_lim else None,
            "utilization": nii_risk_lim["utilization_pct"] if nii_risk_lim else None,
            "status": nii_risk_lim["status"] if nii_risk_lim else "neutral",
        })

    # 4. Worst ΔEVE (BCBS scenarios)
    eve = result.get("eve", {})
    if eve.get("has_data"):
        sc = eve.get("scenarios", {})
        if sc:
            eve_lim = next((i for i in lim_items if i["metric"] == "eve_change_worst"), None)
            metrics.append({
                "metric": f"Worst \u0394EVE ({sc.get('worst_scenario', '')})",
                "value": sc.get("worst_delta", 0),
                "delta_1d": None,
                "limit": eve_lim["limit"] if eve_lim else None,
                "utilization": eve_lim["utilization_pct"] if eve_lim else None,
                "status": eve_lim["status"] if eve_lim else "neutral",
            })

        # 5. Effective Duration & DGAP
        by_ccy = eve.get("by_currency", {})
        conv = eve.get("convexity", {})
        if conv:
            eff_dur = conv.get("effective_duration", 0)
            metrics.append({
                "metric": "Effective Duration",
                "value": eff_dur,
                "delta_1d": None,
                "limit": None,
                "utilization": None,
                "status": "green" if abs(eff_dur) < 3 else "yellow" if abs(eff_dur) < 5 else "red",
                "unit": "Y",
            })
            # DGAP approximation: ΔEVE per 100bp / Total EVE gives duration sensitivity
            total_eve = eve.get("total_eve", 0)
            if total_eve and sc:
                delta_eve_up = sc.get("parallel_up_delta", sc.get("worst_delta", 0))
                dgap = abs(delta_eve_up) / abs(total_eve) / 0.02 if total_eve != 0 else 0
                dgap_lim = next((i for i in lim_items if i["metric"] == "dgap"), None)
                metrics.append({
                    "metric": "DGAP (Duration Gap)",
                    "value": round(dgap, 2),
                    "delta_1d": None,
                    "limit": dgap_lim["limit"] if dgap_lim else None,
                    "utilization": dgap_lim["utilization_pct"] if dgap_lim else None,
                    "status": dgap_lim["status"] if dgap_lim else ("green" if dgap < 2 else "yellow" if dgap < 4 else "red"),
                    "unit": "Y",
                })
        elif by_ccy:
            total_dur = sum(d["duration"] * abs(d["eve"]) for d in by_ccy.values()) / max(sum(abs(d["eve"]) for d in by_ccy.values()), 1e-6)
            metrics.append({
                "metric": "Portfolio Duration",
                "value": round(total_dur, 2),
                "delta_1d": None,
                "limit": None,
                "utilization": None,
                "status": "neutral",
                "unit": "Y",
            })

    # 6. HHI (counterparty concentration)
    cpty = result.get("counterparty_pnl", {})
    if cpty.get("has_data"):
        metrics.append({
            "metric": "Counterparty HHI",
            "value": cpty.get("hhi", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "green" if cpty.get("hhi", 0) < 1500 else "yellow" if cpty.get("hhi", 0) < 2500 else "red",
        })

    # 7. Hedge effectiveness
    hedge = result.get("hedge", {})
    if hedge.get("has_data"):
        h_sum = hedge.get("summary", {})
        failing = h_sum.get("fail", 0)
        total_pairs = h_sum.get("total", 0)
        metrics.append({
            "metric": "Hedge Pairs Failing",
            "value": failing,
            "delta_1d": None,
            "limit": 0,
            "utilization": None,
            "status": "red" if failing > 0 else "green",
            "display": f"{failing}/{total_pairs}",
        })

    # 8. Liquidity 30d
    liq = result.get("liquidity", {})
    if liq.get("has_data"):
        liq_sum = liq.get("summary", {})
        metrics.append({
            "metric": "Liquidity Net 30d",
            "value": liq_sum.get("net_30d", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if liq_sum.get("net_30d", 0) < 0 else "green",
        })

    # 9. FTP ALM Margin
    ftp = result.get("ftp", {})
    if ftp.get("has_data"):
        metrics.append({
            "metric": "ALM Margin (FTP)",
            "value": ftp["totals"].get("alm_margin", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if ftp["totals"].get("alm_margin", 0) < 0 else "green",
        })

    # 10. NIM
    nim_data = result.get("nim", {})
    if nim_data.get("has_data"):
        nim_bps = nim_data["kpis"].get("nim_bps", 0)
        metrics.append({
            "metric": "NIM (ann.)",
            "value": nim_bps,
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "green" if nim_bps > 50 else "yellow" if nim_bps > 0 else "red",
            "unit": "bps",
        })

    # 11. Alert counts
    alerts = result.get("pnl_alerts", {})
    if alerts.get("has_data"):
        a_sum = alerts.get("summary", {})
        metrics.append({
            "metric": "Active Alerts",
            "value": a_sum.get("critical", 0) + a_sum.get("high", 0) + a_sum.get("medium", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if a_sum.get("critical", 0) > 0 else "yellow" if a_sum.get("high", 0) > 0 else "green",
            "display": f"{a_sum.get('critical', 0)}C / {a_sum.get('high', 0)}H / {a_sum.get('medium', 0)}M",
        })

    return {"has_data": len(metrics) > 0, "metrics": metrics}


# ---------------------------------------------------------------------------
# Budget vs Actual
# ---------------------------------------------------------------------------

def _build_budget(
    df: pd.DataFrame,
    budget: Optional[pd.DataFrame] = None,
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
) -> dict:
    """Budget vs actual comparison with optional variance decomposition.

    When ``deals`` and ``pnl_by_deal`` are provided, the variance is
    decomposed into:
      - volume_effect: (actual_nominal - budget_nominal) × budget_rate
      - rate_effect: budget_nominal × (actual_rate - budget_rate)
      - new_deal_effect: NII from deals originated after budget cut-off
      - matured_effect: lost NII from deals that matured during the period
    """
    if budget is None or budget.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "ytd": {}}

    pnl = df[(df["Indice"] == "PnL_Simple") & (df["Shock"] == "0")] if not df.empty else pd.DataFrame()
    if pnl.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "ytd": {}}

    # Actual by currency x month
    actual_by_cm = pnl.groupby(["Deal currency", "Month"])["Value"].sum()

    months = sorted(budget["month"].unique()) if "month" in budget.columns else []
    currencies = sorted(budget["currency"].unique()) if "currency" in budget.columns else []
    month_labels = _month_labels(months)

    # Precompute deal-level stats for variance decomposition
    has_decomp = (
        deals is not None and not deals.empty
        and pnl_by_deal is not None and not pnl_by_deal.empty
        and "budget_nominal" in budget.columns
        and "budget_rate" in budget.columns
    )

    # Actual nominal and rate by currency (from pnl_by_deal if available)
    actual_nom_by_ccy = {}
    actual_rate_by_ccy = {}
    if has_decomp:
        pbd = pnl_by_deal
        if "Shock" in pbd.columns:
            pbd = pbd[pbd["Shock"] == "0"]
        for ccy in currencies:
            ccy_deals = pbd[pbd["Deal currency"] == ccy] if "Deal currency" in pbd.columns else (
                pbd[pbd["Currency"] == ccy] if "Currency" in pbd.columns else pd.DataFrame()
            )
            actual_nom_by_ccy[ccy] = float(ccy_deals["Nominal"].sum()) if "Nominal" in ccy_deals.columns and not ccy_deals.empty else 0.0
            # Weighted average rate
            if "Nominal" in ccy_deals.columns and "PnL" in ccy_deals.columns and not ccy_deals.empty:
                nom_sum = ccy_deals["Nominal"].abs().sum()
                from pnl_engine.config import MM_BY_CURRENCY
                _mm = float(MM_BY_CURRENCY.get(ccy, 360))
                actual_rate_by_ccy[ccy] = float(ccy_deals["PnL"].sum() / nom_sum * _mm) if nom_sum > 0 else 0.0
            else:
                actual_rate_by_ccy[ccy] = 0.0

    by_currency = {}
    ytd_actual = 0.0
    ytd_budget = 0.0

    for ccy in currencies:
        ccy_budget = budget[budget["currency"] == ccy]
        actuals = []
        budgets = []
        variances = []
        volume_effects = []
        rate_effects = []
        new_deal_effects = []
        matured_effects = []

        for m in months:
            bgt = ccy_budget[ccy_budget["month"] == m]["budget_nii"].sum()
            act = 0.0
            for key_m in actual_by_cm.index:
                if key_m[0] == ccy and str(key_m[1]) == str(m):
                    act = actual_by_cm[key_m]
                    break
            actuals.append(round(float(act), 0))
            budgets.append(round(float(bgt), 0))
            variances.append(round(float(act - bgt), 0))
            ytd_actual += act
            ytd_budget += bgt

            # Variance decomposition for this month
            if has_decomp:
                m_budget = ccy_budget[ccy_budget["month"] == m]
                bgt_nom = float(m_budget["budget_nominal"].sum()) if not m_budget.empty else 0.0
                bgt_rate = float(m_budget["budget_rate"].mean()) if not m_budget.empty else 0.0
                act_nom = actual_nom_by_ccy.get(ccy, 0.0) / max(len(months), 1)  # monthly average
                act_rate = actual_rate_by_ccy.get(ccy, 0.0)

                from pnl_engine.config import MM_BY_CURRENCY
                _mm_var = float(MM_BY_CURRENCY.get(ccy, 360))
                vol_eff = (act_nom - bgt_nom) * bgt_rate / _mm_var * 30 if bgt_rate != 0 else 0.0
                rate_eff = bgt_nom * (act_rate - bgt_rate) / _mm_var * 30 if bgt_nom != 0 else 0.0
                residual = float(act - bgt) - vol_eff - rate_eff
                volume_effects.append(round(vol_eff, 0))
                rate_effects.append(round(rate_eff, 0))
                new_deal_effects.append(round(max(residual, 0), 0))
                matured_effects.append(round(min(residual, 0), 0))
            else:
                volume_effects.append(0)
                rate_effects.append(0)
                new_deal_effects.append(0)
                matured_effects.append(0)

        ccy_data = {
            "actual": actuals,
            "budget": budgets,
            "variance": variances,
        }
        if has_decomp:
            ccy_data["volume_effect"] = volume_effects
            ccy_data["rate_effect"] = rate_effects
            ccy_data["new_deal_effect"] = new_deal_effects
            ccy_data["matured_effect"] = matured_effects

        by_currency[ccy] = ccy_data

    ytd = {
        "actual": round(float(ytd_actual), 0),
        "budget": round(float(ytd_budget), 0),
        "variance": round(float(ytd_actual - ytd_budget), 0),
        "variance_pct": round(float((ytd_actual - ytd_budget) / abs(ytd_budget) * 100), 1) if ytd_budget != 0 else 0,
    }

    # Build variance waterfall (YTD)
    variance_waterfall = []
    if has_decomp:
        total_vol = sum(sum(by_currency[c].get("volume_effect", [])) for c in currencies)
        total_rate = sum(sum(by_currency[c].get("rate_effect", [])) for c in currencies)
        total_new = sum(sum(by_currency[c].get("new_deal_effect", [])) for c in currencies)
        total_mat = sum(sum(by_currency[c].get("matured_effect", [])) for c in currencies)
        variance_waterfall = [
            {"label": "Budget NII", "value": ytd["budget"], "type": "base"},
            {"label": "Volume Effect", "value": round(total_vol, 0), "type": "effect"},
            {"label": "Rate Effect", "value": round(total_rate, 0), "type": "effect"},
            {"label": "New Deals", "value": round(total_new, 0), "type": "effect"},
            {"label": "Matured Deals", "value": round(total_mat, 0), "type": "effect"},
            {"label": "Actual NII", "value": ytd["actual"], "type": "total"},
        ]

    result = {"has_data": True, "months": month_labels, "by_currency": by_currency, "ytd": ytd}
    if variance_waterfall:
        result["variance_waterfall"] = variance_waterfall
    return result


# ---------------------------------------------------------------------------
# P&L Attribution / Explain
# ---------------------------------------------------------------------------

def _build_attribution(
    df: pd.DataFrame,
    prev_pnl_all_s: Optional[pd.DataFrame] = None,
    pnl_explain: Optional[dict] = None,
) -> dict:
    """P&L attribution / explain waterfall.

    If pnl_explain is provided (from compute_pnl_explain), uses the full
    waterfall decomposition. Otherwise falls back to basic rate x volume.
    """
    # Use full explain if available
    if pnl_explain is not None and pnl_explain.get("has_data"):
        return pnl_explain

    # Fallback: basic rate x volume decomposition (needs prev_pnl_all_s)
    if prev_pnl_all_s is None or (isinstance(prev_pnl_all_s, pd.DataFrame) and prev_pnl_all_s.empty):
        return {"has_data": False, "by_currency": {}, "waterfall": [], "summary": {}}

    prev = _safe_stacked(prev_pnl_all_s)
    if df.empty or prev.empty:
        return {"has_data": False, "by_currency": {}, "waterfall": [], "summary": {}}

    def _extract(frame, indice):
        rows = frame[(frame["Indice"] == indice) & (frame["Shock"] == "0")]
        if "Deal currency" in rows.columns:
            return rows.groupby("Deal currency")["Value"].sum()
        return pd.Series(dtype=float)

    curr_pnl = _extract(df, "PnL")
    prev_pnl = _extract(prev, "PnL")
    curr_nom = _extract(df, "Nominal")
    prev_nom = _extract(prev, "Nominal")
    curr_ois = _extract(df, "OISfwd")
    prev_ois = _extract(prev, "OISfwd")

    currencies = sorted(set(curr_pnl.index) | set(prev_pnl.index))
    by_currency = {}
    total_rate = 0
    total_volume = 0
    total_cross = 0

    for ccy in currencies:
        nom_old = prev_nom.get(ccy, 0)
        rate_old = prev_ois.get(ccy, 0)
        nom_new = curr_nom.get(ccy, 0)
        rate_new = curr_ois.get(ccy, 0)

        rate_effect = nom_old * (rate_new - rate_old)
        volume_effect = (nom_new - nom_old) * rate_old
        cross_term = (nom_new - nom_old) * (rate_new - rate_old)

        by_currency[ccy] = {
            "ois_prev": round(float(rate_old) * 10000, 1),
            "ois_curr": round(float(rate_new) * 10000, 1),
            "nominal_prev": round(float(nom_old), 0),
            "nominal_curr": round(float(nom_new), 0),
        }
        total_rate += rate_effect
        total_volume += volume_effect
        total_cross += cross_term

    prev_total = float(prev_pnl.sum())
    curr_total = float(curr_pnl.sum())
    residual = (curr_total - prev_total) - total_rate - total_volume - total_cross

    waterfall = [
        {"label": "Prev NII", "value": round(prev_total, 0), "type": "base"},
        {"label": "Rate Effect", "value": round(float(total_rate), 0), "type": "effect"},
        {"label": "Volume Effect", "value": round(float(total_volume), 0), "type": "effect"},
        {"label": "Rate\u00d7Volume", "value": round(float(total_cross), 0), "type": "effect"},
        {"label": "Residual", "value": round(float(residual), 0), "type": "effect"},
        {"label": "Current NII", "value": round(curr_total, 0), "type": "total"},
    ]

    return {
        "has_data": len(by_currency) > 0,
        "by_currency": by_currency,
        "waterfall": waterfall,
        "new_deals": [],
        "matured_deals": [],
        "summary": {
            "prev_nii": round(prev_total, 0),
            "curr_nii": round(curr_total, 0),
            "delta": round(curr_total - prev_total, 0),
            "rate_effect": round(float(total_rate), 0),
            "time_effect": 0,
            "new_deal_effect": 0,
            "matured_deal_effect": 0,
            "spread_effect": 0,
            "n_new": 0, "n_matured": 0, "n_existing": 0,
        },
    }


# ---------------------------------------------------------------------------
# Forecast Tracking
# ---------------------------------------------------------------------------

def _build_forecast_tracking(forecast_history: Optional[pd.DataFrame] = None) -> dict:
    """Historical NII forecast evolution with revision analytics."""
    if forecast_history is None or (isinstance(forecast_history, pd.DataFrame) and forecast_history.empty):
        return {"has_data": False, "dates": [], "by_currency": {}, "total": [],
                "revisions": {}, "stats": {}}

    dates = sorted(forecast_history["date"].unique()) if "date" in forecast_history.columns else []
    date_labels = [str(d) for d in dates]

    by_currency = {}
    if "currency" in forecast_history.columns:
        for ccy in sorted(forecast_history["currency"].unique()):
            ccy_data = forecast_history[forecast_history["currency"] == ccy].sort_values("date")
            by_currency[ccy] = [round(float(v), 0) for v in ccy_data["nii_forecast"].tolist()]

    totals = []
    for d in dates:
        d_data = forecast_history[forecast_history["date"] == d]
        totals.append(round(float(d_data["nii_forecast"].sum()), 0))

    # Revision analytics: how much did the forecast change between consecutive runs
    revisions = {"dates": [], "changes": [], "pct_changes": []}
    if len(totals) >= 2:
        for i in range(1, len(totals)):
            revisions["dates"].append(date_labels[i])
            delta = totals[i] - totals[i - 1]
            revisions["changes"].append(round(float(delta), 0))
            pct = (delta / totals[i - 1] * 100) if totals[i - 1] != 0 else 0
            revisions["pct_changes"].append(round(float(pct), 2))

    # Summary statistics
    stats = {}
    if len(totals) >= 2:
        changes = [totals[i] - totals[i - 1] for i in range(1, len(totals))]
        abs_changes = [abs(c) for c in changes]
        stats["latest"] = totals[-1]
        stats["earliest"] = totals[0]
        stats["range_pct"] = round((totals[-1] - totals[0]) / abs(totals[0]) * 100, 2) if totals[0] != 0 else 0
        stats["avg_revision"] = round(float(np.mean(changes)), 0) if changes else 0
        stats["max_revision"] = round(float(max(changes, key=abs)), 0) if changes else 0
        stats["volatility"] = round(float(np.std(changes)), 0) if len(changes) > 1 else 0
        # Stability score: lower is more stable (coefficient of variation of revisions)
        if stats["volatility"] > 0 and stats["latest"] != 0:
            stats["stability_cv"] = round(stats["volatility"] / abs(stats["latest"]) * 100, 2)
        else:
            stats["stability_cv"] = 0
        stats["n_snapshots"] = len(totals)
        # Direction consistency: % of revisions in same direction as latest trend
        if changes:
            last_dir = 1 if changes[-1] >= 0 else -1
            same_dir = sum(1 for c in changes if (c >= 0) == (last_dir >= 0))
            stats["direction_consistency"] = round(same_dir / len(changes) * 100, 1)
        else:
            stats["direction_consistency"] = 0

    return {
        "has_data": len(dates) > 0,
        "dates": date_labels,
        "by_currency": by_currency,
        "total": totals,
        "revisions": revisions,
        "stats": stats,
    }
