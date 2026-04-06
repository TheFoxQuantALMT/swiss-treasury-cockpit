"""Locked-in NII metric — NII from fixed-rate deals only.

Calculates the portion of forward-looking NII that is contractually
locked via fixed-rate instruments, providing a floor/certainty measure.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


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
    mm_2d = mm_vector[:, np.newaxis] if mm_vector.ndim == 1 else mm_vector

    # Full NII
    daily_pnl = nominal_daily[:, :n_days] * (ois_matrix[:, :n_days] - rate_matrix[:, :n_days]) / mm_2d[:, :n_days] if mm_2d.ndim == 2 else nominal_daily[:, :n_days] * (ois_matrix[:, :n_days] - rate_matrix[:, :n_days]) / mm_2d
    total_nii = float(np.nansum(daily_pnl))

    # Fixed-rate mask
    is_floating = deals.get("is_floating", pd.Series([False] * len(deals)))
    fixed_mask = ~is_floating.fillna(False).astype(bool)
    fixed_idx = np.where(fixed_mask.values)[0]

    if len(fixed_idx) == 0:
        locked_nii = 0.0
    else:
        locked_nii = float(np.nansum(daily_pnl[fixed_idx]))

    locked_pct = (locked_nii / total_nii * 100) if total_nii != 0 else 0.0

    # Per currency
    by_currency = {}
    if "Currency" in deals.columns:
        for ccy in deals["Currency"].str.strip().str.upper().unique():
            ccy_mask = deals["Currency"].str.strip().str.upper() == ccy
            ccy_idx = np.where(ccy_mask.values)[0]
            ccy_fixed = np.where((ccy_mask & fixed_mask).values)[0]

            ccy_total = float(np.nansum(daily_pnl[ccy_idx])) if len(ccy_idx) > 0 else 0.0
            ccy_locked = float(np.nansum(daily_pnl[ccy_fixed])) if len(ccy_fixed) > 0 else 0.0

            by_currency[ccy] = {
                "total_nii": round(ccy_total, 0),
                "locked_nii": round(ccy_locked, 0),
                "locked_pct": round(ccy_locked / ccy_total * 100, 1) if ccy_total != 0 else 0.0,
            }

    return {
        "has_data": True,
        "total_nii": round(total_nii, 0),
        "locked_nii": round(locked_nii, 0),
        "locked_pct": round(locked_pct, 1),
        "horizon_days": n_days,
        "by_currency": by_currency,
    }
