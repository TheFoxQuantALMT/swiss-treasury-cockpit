"""Helper utilities for chart data builders."""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Optional

import pandas as pd


def safe_float(v) -> float:
    """NaN-safe float conversion, returning 0.0 for None/NaN/non-numeric."""
    if v is None:
        return 0.0
    if isinstance(v, float) and math.isnan(v):
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0

from cockpit.engine.pnl.pnl_explain import compute_pnl_explain

logger = logging.getLogger(__name__)


def _safe_stacked(pnl_all_s: pd.DataFrame) -> pd.DataFrame:
    """Reset MultiIndex to flat columns for easier filtering.

    Also coerces ``Value`` to float — the upstream ``pivot_table`` leaves it as
    object dtype, which silently poisons downstream arithmetic: ``.mean()`` on
    object dtype includes all rows raw (no NaN skip), and numpy broadcasting
    against an object array can emit zeros. The Strategy Leg Summary's Avg
    RateRef/OIS = 0 bug was caused by exactly this.
    """
    if pnl_all_s is None or pnl_all_s.empty:
        return pd.DataFrame()
    df = pnl_all_s.copy()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
    if "Value" in df.columns and df["Value"].dtype == object:
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(0.0)
    return df


def _month_labels(months) -> list[str]:
    """Convert Period/str months to display labels (e.g., 'Apr-26')."""
    labels = []
    for m in months:
        try:
            if hasattr(m, 'start_time'):
                labels.append(m.start_time.strftime("%b-%y"))
            else:
                ts = pd.Timestamp(str(m))
                labels.append(ts.strftime("%b-%y"))
        except (ValueError, TypeError):
            labels.append(str(m))
    return labels


def _auto_pnl_explain(
    pnl_by_deal: Optional[pd.DataFrame],
    prev_pnl_by_deal: Optional[pd.DataFrame],
    pnl_all_s: Optional[pd.DataFrame],
    prev_pnl_all_s: Optional[pd.DataFrame],
    deals: Optional[pd.DataFrame],
    date_run: Optional[datetime],
    prev_date_run: Optional[datetime],
) -> Optional[dict]:
    """Auto-trigger compute_pnl_explain when sufficient data is available."""
    if (pnl_by_deal is None or prev_pnl_by_deal is None
            or pnl_all_s is None or prev_pnl_all_s is None
            or date_run is None or prev_date_run is None):
        return None
    if (isinstance(pnl_by_deal, pd.DataFrame) and pnl_by_deal.empty) or \
       (isinstance(prev_pnl_by_deal, pd.DataFrame) and prev_pnl_by_deal.empty):
        return None
    try:
        return compute_pnl_explain(
            curr_pnl_by_deal=pnl_by_deal,
            prev_pnl_by_deal=prev_pnl_by_deal,
            curr_pnl_all_s=pnl_all_s,
            prev_pnl_all_s=prev_pnl_all_s,
            deals=deals if deals is not None else pd.DataFrame(),
            date_run=date_run,
            prev_date_run=prev_date_run,
        )
    except Exception:
        logger.warning("Auto P&L explain failed, falling back to basic attribution", exc_info=True)
        return None


def _filter_total(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse PnL_Type to the row set that sums to the true total.

    The engine emits actual P&L in ``Realized`` (past + current-month slice) and
    ``Forecast`` (future + current-month slice); ``Realized + Forecast = Total``
    across all months by construction. ``Total`` rows carry data only for the
    current month and are zero-filled by the upstream pivot_table for every
    other month — so summing ``Total`` rows truncates to just rates_month, which
    was the bug that made Monthly Series and CoC show only April.
    """
    if "PnL_Type" not in df.columns:
        return df
    split = df[df["PnL_Type"].isin(["Realized", "Forecast"])]
    return split if not split.empty else df
