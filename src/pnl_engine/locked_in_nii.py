"""Locked-in NII metric — NII from fixed-rate deals only.

Calculates the portion of forward-looking NII that is contractually
locked via fixed-rate instruments, providing a floor/certainty measure.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.matrices import broadcast_mm


def compute_locked_in_nii(
    deals: Optional[pd.DataFrame],
    nominal_daily: Optional[np.ndarray],
    rate_matrix: Optional[np.ndarray],
    ois_matrix: Optional[np.ndarray],
    mm_vector: Optional[np.ndarray],
    horizon_days: int = 365,
) -> dict:
    """Compute NII from fixed-rate deals for the next N days.

    Args:
        deals: Deal metadata with is_floating column.
        nominal_daily: (n_deals, n_days) nominal schedule.
        rate_matrix: (n_deals, n_days) client rate matrix.
        ois_matrix: (n_deals, n_days) OIS rate matrix.
        mm_vector: (n_deals,) day-count divisor.
        horizon_days: Forward horizon in days (default 365).

    Returns:
        Dict with locked_nii, total_nii, locked_pct, by_currency.
    """
    if deals is None or deals.empty or nominal_daily is None:
        return {"has_data": False}

    n_days = min(horizon_days, nominal_daily.shape[1])
    mm_2d = broadcast_mm(mm_vector)

    # Full NII
    daily_pnl = nominal_daily[:, :n_days] * (ois_matrix[:, :n_days] - rate_matrix[:, :n_days]) / mm_2d[:, :n_days]
    total_nii = float(np.nansum(daily_pnl))

    # Fixed-rate mask
    is_floating = deals["is_floating"] if "is_floating" in deals.columns else pd.Series([False] * len(deals))
    fixed_mask = ~is_floating.fillna(False).astype(bool)
    fixed_idx = np.where(fixed_mask.values)[0]

    if len(fixed_idx) == 0:
        locked_nii = 0.0
    else:
        locked_nii = float(np.nansum(daily_pnl[fixed_idx]))

    # Bounds-check on the raw ratio so display rounding (1 dp) cannot flip the
    # narrative gate at the boundary (e.g. true 100.04% rounds to 100.0).
    raw_pct = locked_nii / total_nii * 100 if total_nii != 0 else 0.0
    pct_meaningful = total_nii > 0 and 0.0 <= raw_pct <= 100.0
    locked_pct = round(raw_pct, 1)

    by_currency = {}
    if "Currency" in deals.columns:
        for ccy in deals["Currency"].str.strip().str.upper().unique():
            ccy_mask = deals["Currency"].str.strip().str.upper() == ccy
            ccy_idx = np.where(ccy_mask.values)[0]
            ccy_fixed = np.where((ccy_mask & fixed_mask).values)[0]

            ccy_total = float(np.nansum(daily_pnl[ccy_idx])) if len(ccy_idx) > 0 else 0.0
            ccy_locked = float(np.nansum(daily_pnl[ccy_fixed])) if len(ccy_fixed) > 0 else 0.0
            ccy_raw_pct = ccy_locked / ccy_total * 100 if ccy_total != 0 else 0.0
            ccy_meaningful = ccy_total > 0 and 0.0 <= ccy_raw_pct <= 100.0
            ccy_pct = round(ccy_raw_pct, 1)

            by_currency[ccy] = {
                "total_nii": round(ccy_total, 0),
                "locked_nii": round(ccy_locked, 0),
                "locked_pct": ccy_pct,
                "pct_meaningful": ccy_meaningful,
            }

    return {
        "has_data": True,
        "total_nii": round(total_nii, 0),
        "locked_nii": round(locked_nii, 0),
        "locked_pct": locked_pct,
        "pct_meaningful": pct_meaningful,
        "horizon_days": n_days,
        "by_currency": by_currency,
    }
