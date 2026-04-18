"""Daily reconciliation (Phase 5): compare prior Synthesis forecast vs today's realized P&L.

Approach B — monthly drift check. For each ``(IAS Book, Category2)`` bucket,
compares today's bank-reported ``PnL_Realized`` against a prorated slice of
the prior-day Synthesis forecast for the same month. Produces a RAG status
per bucket using a per-Category2 tolerance expressed in annualized bps of
bucket notional.

Prorata model
-------------
The prior Synthesis stores one number per month per bucket. Today's expected
daily P&L = month_forecast / days_in_month. This is a naïve uniform split —
fine for the RAG drift signal (detects large deviations) but not suitable
for exact attribution. For strict per-day reconciliation, the engine would
need to expose a daily series (follow-up work).

Output
------
One row per (IAS Book, Category2) bucket, with Forecast / Realized / Delta
and Status ∈ {Green, Amber, Red}. A summary "Total" row is appended.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RECONCILIATION_SHEET_NAME = "Reconciliation"

# Per-Category2 daily P&L tolerance, expressed in annualized bps of bucket
# notional. Accrual-flavoured buckets (BOOK1) hold tighter; MTM-flavoured
# (BOOK2, IRS_FVO) tolerate more daily noise by design.
DEFAULT_TOLERANCES_BPS: dict[str, float] = {
    "OPP_CASH": 5.0,
    "OPP_Bond_ASW": 10.0,
    "OPP_Bond_nASW": 10.0,
    "OPR_FVH": 15.0,
    "OPR_nFVH": 15.0,
    "Other": 20.0,
    "IRS_FVH": 25.0,
    "IRS_FVO": 50.0,
}
FALLBACK_TOLERANCE_BPS: float = 20.0


def _current_month_column(synthesis: pd.DataFrame, position_date: pd.Timestamp) -> Optional[str]:
    """Return the YYYY/MM column name of ``synthesis`` matching ``position_date``.

    Returns None if the Synthesis has no column for that month (e.g. caller
    passed a Synthesis file older than 60 months from the position date).
    """
    label = position_date.strftime("%Y/%m")
    return label if label in synthesis.columns else None


def _status(delta_bps_abs: float, tolerance_bps: float) -> str:
    if delta_bps_abs <= tolerance_bps:
        return "Green"
    if delta_bps_abs <= 2 * tolerance_bps:
        return "Amber"
    return "Red"


def reconcile_daily(
    today_deals: pd.DataFrame,
    prior_synthesis: pd.DataFrame,
    *,
    position_date: pd.Timestamp,
    tolerances_bps: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """Reconcile today's realized P&L against the prior Synthesis forecast.

    Parameters
    ----------
    today_deals
        Bank-native deals frame for the position date. Must carry ``IAS Book``,
        ``Category2``, ``PnL_Realized`` (one day's P&L in CHF), and
        ``Amount_CHF`` (signed notional in CHF).
    prior_synthesis
        DataFrame read from the previous day's Synthesis sheet (wide: rows per
        bucket, one ``YYYY/MM`` column per month).
    position_date
        Today's position date. Selects the current-month column from the
        Synthesis and computes the days-in-month divisor.
    tolerances_bps
        Optional per-Category2 override. Merged over :data:`DEFAULT_TOLERANCES_BPS`.

    Returns
    -------
    pd.DataFrame
        One row per ``(IAS Book, Category2)`` bucket present in ``today_deals``,
        plus a terminal ``Total`` row. Columns:
        ``IAS Book, Category2, Realized_CHF, Forecast_Daily_CHF, Delta_CHF,
         Notional_CHF, Delta_bps_annualized, Tolerance_bps, Status``.
    """
    required = {"IAS Book", "Category2", "PnL_Realized", "Amount_CHF"}
    missing = required - set(today_deals.columns)
    if missing:
        raise ValueError(f"reconcile_daily: today_deals missing columns {sorted(missing)}")
    if not {"IAS Book", "Category2"}.issubset(prior_synthesis.columns):
        raise ValueError("reconcile_daily: prior_synthesis must carry IAS Book and Category2")

    pos = pd.Timestamp(position_date)
    month_col = _current_month_column(prior_synthesis, pos)
    if month_col is None:
        logger.warning("reconcile_daily: no %s column in prior Synthesis — all forecasts 0",
                       pos.strftime("%Y/%m"))

    tol_map = dict(DEFAULT_TOLERANCES_BPS)
    if tolerances_bps:
        tol_map.update(tolerances_bps)

    agg = (
        today_deals
        .groupby(["IAS Book", "Category2"], as_index=False)
        .agg(Realized_CHF=("PnL_Realized", "sum"),
             Notional_CHF=("Amount_CHF", lambda s: s.abs().sum()))
    )

    if month_col is not None:
        forecast_monthly = (
            prior_synthesis[["IAS Book", "Category2", month_col]]
            .rename(columns={month_col: "Forecast_Month_CHF"})
        )
    else:
        forecast_monthly = prior_synthesis[["IAS Book", "Category2"]].assign(Forecast_Month_CHF=0.0)

    merged = agg.merge(forecast_monthly, on=["IAS Book", "Category2"], how="left")
    merged["Forecast_Month_CHF"] = merged["Forecast_Month_CHF"].fillna(0.0)

    days_in_month = pos.days_in_month
    merged["Forecast_Daily_CHF"] = merged["Forecast_Month_CHF"] / days_in_month
    merged["Delta_CHF"] = merged["Realized_CHF"] - merged["Forecast_Daily_CHF"]

    # Annualize daily delta and express as bps of notional
    notional_safe = merged["Notional_CHF"].where(merged["Notional_CHF"] > 0, np.nan)
    merged["Delta_bps_annualized"] = (merged["Delta_CHF"] * 365.0 / notional_safe) * 10_000.0
    merged["Delta_bps_annualized"] = merged["Delta_bps_annualized"].fillna(0.0)

    merged["Tolerance_bps"] = merged["Category2"].map(tol_map).fillna(FALLBACK_TOLERANCE_BPS)
    merged["Status"] = [
        _status(abs(d), t)
        for d, t in zip(merged["Delta_bps_annualized"], merged["Tolerance_bps"])
    ]

    cols = ["IAS Book", "Category2", "Realized_CHF", "Forecast_Daily_CHF", "Delta_CHF",
            "Notional_CHF", "Delta_bps_annualized", "Tolerance_bps", "Status"]
    merged = merged[cols].sort_values(["IAS Book", "Category2"]).reset_index(drop=True)

    total = {
        "IAS Book": "",
        "Category2": "Total",
        "Realized_CHF": merged["Realized_CHF"].sum(),
        "Forecast_Daily_CHF": merged["Forecast_Daily_CHF"].sum(),
        "Delta_CHF": merged["Delta_CHF"].sum(),
        "Notional_CHF": merged["Notional_CHF"].sum(),
        # Total row aggregates bps at portfolio level, not a sum of per-bucket bps
        "Delta_bps_annualized": _portfolio_bps(merged),
        "Tolerance_bps": np.nan,
        "Status": "",
    }
    return pd.concat([merged, pd.DataFrame([total])], ignore_index=True)


def _portfolio_bps(merged: pd.DataFrame) -> float:
    total_delta = merged["Delta_CHF"].sum()
    total_notional = merged["Notional_CHF"].sum()
    if total_notional <= 0:
        return 0.0
    return total_delta * 365.0 / total_notional * 10_000.0


def export_reconciliation(df: pd.DataFrame, path: Path) -> Path:
    """Write a reconciliation DataFrame to ``path`` under sheet ``Reconciliation``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=RECONCILIATION_SHEET_NAME, index=False)
    logger.info("Reconciliation written to %s (%d buckets)", path, len(df) - 1)
    return path


__all__ = [
    "RECONCILIATION_SHEET_NAME",
    "DEFAULT_TOLERANCES_BPS",
    "FALLBACK_TOLERANCE_BPS",
    "reconcile_daily",
    "export_reconciliation",
]
