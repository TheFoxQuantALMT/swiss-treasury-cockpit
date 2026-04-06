"""SARON compounding — ISDA 2021 compounded-in-arrears with lookback.

Swiss market convention for SARON (Swiss Average Rate Overnight):
- Compounded in arrears with a 2-business-day lookback (SNB WG recommendation)
- ISDA 2021 Definitions fallback: daily compounding with observation shift

This module provides utility functions for SARON rate computation that
complement the vectorized engine (which uses pre-built WASP curves).
"""
from __future__ import annotations

import numpy as np


def compound_saron_daily(
    daily_rates: np.ndarray,
    notional: float = 1.0,
    day_count_basis: int = 360,
) -> dict:
    """Compute compounded SARON rate from daily fixings.

    Uses the ISDA 2021 compounding formula:
        CompoundedRate = (∏(1 + r_i × d_i / DCB) - 1) × DCB / D

    where r_i is the daily SARON, d_i is 1 (daily), DCB is 360, and D is
    the total number of calendar days.

    Args:
        daily_rates: Array of daily SARON fixings (annualized, decimal).
        notional: Notional amount (default 1.0 for rate computation).
        day_count_basis: Day count convention (360 for CHF).

    Returns:
        Dict with compounded_rate, accrued_interest, n_days.
    """
    if daily_rates is None or len(daily_rates) == 0:
        return {"compounded_rate": 0.0, "accrued_interest": 0.0, "n_days": 0}

    n = len(daily_rates)
    # Daily accrual factors: 1 + r_i / DCB
    daily_factors = 1.0 + daily_rates / day_count_basis
    # Compounded product
    compound_factor = float(np.prod(daily_factors))
    # Annualized compounded rate
    compounded_rate = (compound_factor - 1.0) * day_count_basis / n

    accrued = notional * (compound_factor - 1.0)

    return {
        "compounded_rate": round(compounded_rate, 8),
        "compound_factor": round(compound_factor, 10),
        "accrued_interest": round(accrued, 2),
        "n_days": n,
    }


def apply_lookback_shift(
    daily_rates: np.ndarray,
    lookback_days: int = 2,
) -> np.ndarray:
    """Apply observation shift (lookback) to daily rate array.

    For a 2-day lookback, the rate applicable to day t is the fixing
    from day t-2. This delays rate observation but preserves the
    number of compounding days.

    Args:
        daily_rates: (n_days,) array of daily SARON fixings.
        lookback_days: Number of business days to shift (default 2 for SARON).

    Returns:
        Shifted rate array of same length.
    """
    if lookback_days <= 0 or len(daily_rates) <= lookback_days:
        return daily_rates.copy()

    shifted = np.empty_like(daily_rates)
    shifted[:lookback_days] = daily_rates[0]  # Flat extrapolation for initial period
    shifted[lookback_days:] = daily_rates[:-lookback_days]
    return shifted


def validate_against_snb(
    computed_rate: float,
    published_rate: float,
    tolerance_bp: float = 0.5,
) -> dict:
    """Validate computed compound SARON against SNB published value.

    Args:
        computed_rate: Our computed compounded SARON rate.
        published_rate: SNB published compound SARON.
        tolerance_bp: Acceptable difference in basis points.

    Returns:
        Dict with match status and difference.
    """
    diff_bp = abs(computed_rate - published_rate) * 10_000
    return {
        "computed": round(computed_rate, 8),
        "published": round(published_rate, 8),
        "diff_bp": round(diff_bp, 2),
        "within_tolerance": diff_bp <= tolerance_bp,
        "tolerance_bp": tolerance_bp,
    }
