"""P&L-specific alert rules.

Generates alerts from pnlAllS data: NII thresholds, concentration,
month-on-month deltas, negative carry, and shock sensitivity limits.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

DEFAULT_THRESHOLDS = {
    "annual_nii_floor": 0,           # Alert if total NII < this
    "mom_delta_pct": 30.0,           # Month-on-month change > X%
    "ccy_concentration_pct": 70.0,   # Single currency > X% of total
    "negative_coc_alert": True,      # Alert when PnL_Simple < 0
    "shock_sensitivity_limit": None, # Absolute NII delta (50-0); None = skip
}


def check_pnl_alerts(
    pnl_all_s: pd.DataFrame,
    thresholds: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Check P&L data for actionable alerts.

    Args:
        pnl_all_s: Stacked P&L DataFrame (flat columns, not MultiIndex).
        thresholds: Override default alert thresholds.

    Returns:
        List of alert dicts with keys: type, severity, metric, current,
        threshold, message, recommendation.
    """
    if pnl_all_s is None or pnl_all_s.empty:
        return []

    df = pnl_all_s.copy()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()

    t = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    alerts: list[dict[str, Any]] = []

    pnl = df[(df.get("Indice", pd.Series()) == "PnL_Simple") & (df.get("Shock", pd.Series()) == "0")]
    if pnl.empty:
        # Try without Shock filter
        pnl = df[df.get("Indice", pd.Series()) == "PnL_Simple"]
    if pnl.empty:
        return alerts

    # Collapse PnL_Type to avoid triple-counting the current month (engine emits
    # Total + Realized + Forecast for rates_month). Realized + Forecast = Total
    # across all months without double-counting.
    if "PnL_Type" in pnl.columns:
        split = pnl[pnl["PnL_Type"].isin(["Realized", "Forecast"])]
        if not split.empty:
            pnl = split

    pnl = pnl.assign(Value=pd.to_numeric(pnl["Value"], errors="coerce").fillna(0.0))

    # 1. Annual NII floor
    total_nii = float(pnl["Value"].sum())
    if total_nii < t["annual_nii_floor"]:
        alerts.append({
            "type": "nii_floor",
            "severity": "critical",
            "metric": "Total NII (12M)",
            "current": round(float(total_nii), 0),
            "threshold": t["annual_nii_floor"],
            "message": f"Total NII ({total_nii:,.0f}) is below floor ({t['annual_nii_floor']:,.0f})",
            "recommendation": "Review funding strategy and rate positioning",
        })

    # 2. Month-on-month delta
    if "Month" in pnl.columns:
        monthly = pnl.groupby("Month")["Value"].sum().sort_index()
        if len(monthly) >= 2:
            for i in range(1, len(monthly)):
                prev = monthly.iloc[i - 1]
                curr = monthly.iloc[i]
                if abs(prev) > 0:
                    pct_change = abs((curr - prev) / prev) * 100
                    if pct_change > t["mom_delta_pct"]:
                        alerts.append({
                            "type": "mom_delta",
                            "severity": "high",
                            "metric": f"MoM P&L change ({monthly.index[i]})",
                            "current": round(float(pct_change), 1),
                            "threshold": t["mom_delta_pct"],
                            "message": f"P&L changed {pct_change:.1f}% from {monthly.index[i-1]} to {monthly.index[i]}",
                            "recommendation": "Investigate rate or volume drivers for this swing",
                        })

    # 3. Single currency concentration (supports per-currency thresholds).
    # Use Σ|ccy_nii| as the denominator so cross-currency cancellation near zero
    # doesn't blow the ratio up to thousands of percent. A single leg can still
    # dominate on an absolute-contribution basis when others net out.
    if "Deal currency" in pnl.columns:
        ccy_pnl = pnl.groupby("Deal currency")["Value"].sum()
        abs_total = float(ccy_pnl.abs().sum())
        if abs_total > 0:
            for ccy, val in ccy_pnl.items():
                pct = abs(float(val)) / abs_total * 100
                ccy_limit = t["ccy_concentration_pct"]
                if isinstance(t.get("_per_currency"), dict):
                    ccy_limit = t["_per_currency"].get(ccy, {}).get("ccy_concentration_pct", ccy_limit)
                if pct > ccy_limit:
                    alerts.append({
                        "type": "ccy_concentration",
                        "severity": "medium",
                        "metric": f"{ccy} concentration",
                        "current": round(pct, 1),
                        "threshold": ccy_limit,
                        "message": f"{ccy} represents {pct:.1f}% of gross |NII|",
                        "recommendation": f"Consider diversifying {ccy} exposure",
                    })

    # 4. Negative CoC (funding cost exceeds carry)
    if t["negative_coc_alert"]:
        coc_rows = df[(df.get("Indice", pd.Series()) == "PnL_Simple") & (df.get("Shock", pd.Series()) == "0")]
        if not coc_rows.empty and "Deal currency" in coc_rows.columns:
            coc_by_ccy = coc_rows.groupby("Deal currency")["Value"].sum()
            for ccy, val in coc_by_ccy.items():
                if val < 0:
                    alerts.append({
                        "type": "negative_coc",
                        "severity": "high",
                        "metric": f"{ccy} Cost of Carry",
                        "current": round(float(val), 0),
                        "threshold": 0,
                        "message": f"{ccy} CoC is negative ({val:,.0f}): funding cost exceeds carry",
                        "recommendation": f"Review {ccy} funding mix and consider hedging",
                    })

    # 5. Shock sensitivity
    if t["shock_sensitivity_limit"] is not None:
        shock50 = df[(df.get("Indice", pd.Series()) == "PnL_Simple") & (df.get("Shock", pd.Series()) == "50")]
        if not shock50.empty:
            nii_50 = shock50["Value"].sum()
            nii_0 = total_nii
            delta = abs(nii_50 - nii_0)
            if delta > t["shock_sensitivity_limit"]:
                alerts.append({
                    "type": "shock_sensitivity",
                    "severity": "critical",
                    "metric": "NII Sensitivity (+50bp)",
                    "current": round(float(delta), 0),
                    "threshold": t["shock_sensitivity_limit"],
                    "message": f"NII sensitivity to +50bp ({delta:,.0f}) exceeds limit ({t['shock_sensitivity_limit']:,.0f})",
                    "recommendation": "Review rate risk hedging strategy",
                })

    return alerts
