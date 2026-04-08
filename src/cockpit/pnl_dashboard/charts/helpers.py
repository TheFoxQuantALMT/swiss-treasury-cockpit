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
    """Reset MultiIndex to flat columns for easier filtering."""
    if pnl_all_s is None or pnl_all_s.empty:
        return pd.DataFrame()
    df = pnl_all_s.copy()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
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
    """Filter for PnL_Type == 'Total', falling back to all rows if no Total rows exist."""
    if "PnL_Type" not in df.columns:
        return df
    total = df[df["PnL_Type"] == "Total"]
    return total if not total.empty else df
