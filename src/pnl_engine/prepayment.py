"""Conditional Prepayment Rate (CPR) model for fixed-rate mortgages.

Applies a constant annual CPR to fixed-rate mortgage deals, reducing the
nominal schedule to reflect expected prepayments before maturity.

CPR convention: Monthly survival = (1 - CPR)^(1/12)
                 Nominal(t) = Nominal(0) × survival^t_months
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Default CPR by product (Swiss mortgage market convention)
DEFAULT_CPR: dict[str, float] = {
    "IAM/LD": 0.05,  # 5% annual prepayment for fixed-rate mortgages
}


def apply_cpr(
    deals: pd.DataFrame,
    nominal_daily: np.ndarray,
    days: pd.DatetimeIndex,
    cpr_overrides: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[dict]]:
    """Apply CPR-based prepayment to fixed-rate mortgage nominal schedules.

    Only applies to fixed-rate deals (is_floating == False) in products
    with a defined CPR. Floating-rate deals are untouched.

    Args:
        deals: Deal metadata DataFrame.
        nominal_daily: (n_deals, n_days) original nominal schedule.
        days: DatetimeIndex of the date grid.
        cpr_overrides: Optional dict mapping product → CPR rate (0-1).

    Returns:
        Tuple of (modified nominal_daily, prepayment_log).
    """
    cpr_table = {**DEFAULT_CPR, **(cpr_overrides or {})}
    result = nominal_daily.copy()
    log: list[dict] = []

    # Compute month fractions from first day
    if len(days) < 2:
        return result, log

    t0 = days[0]
    month_fracs = np.array([(d - t0).days / 30.4375 for d in days])
    month_fracs = np.maximum(month_fracs, 0.0)

    n_applied = 0
    for i in range(len(deals)):
        deal = deals.iloc[i]
        product = str(deal.get("Product", "")).strip()
        is_floating = bool(deal.get("is_floating", False))

        if is_floating:
            continue

        cpr = cpr_table.get(product)
        if cpr is None or cpr <= 0:
            continue

        # Monthly survival factor
        monthly_survival = (1.0 - cpr) ** (1.0 / 12.0)
        survival_curve = monthly_survival ** month_fracs

        # Apply only where deal is alive
        alive = nominal_daily[i] != 0
        result[i] = np.where(alive, nominal_daily[i] * survival_curve, 0.0)
        n_applied += 1

        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        initial = float(nominal_daily[i, 0]) if nominal_daily[i, 0] != 0 else float(nominal_daily[i][nominal_daily[i] != 0][0]) if np.any(nominal_daily[i] != 0) else 0.0
        final = float(result[i, -1]) if np.any(result[i] != 0) else 0.0

        log.append({
            "deal_id": deal_id,
            "product": product,
            "cpr": cpr,
            "initial_nominal": round(initial, 0),
            "final_nominal": round(final, 0),
            "reduction_pct": round((1 - final / initial) * 100, 1) if initial != 0 else 0.0,
        })

    logger.info("apply_cpr: applied to %d / %d deals", n_applied, len(deals))
    return result, log


def rate_dependent_cpr(
    base_cpr: float,
    deal_rate: float,
    market_rate: float,
    refi_multiplier: float = 2.0,
    refi_threshold: float = 0.005,
) -> float:
    """Compute rate-dependent CPR reflecting refinancing incentive.

    When market rates fall below the deal's fixed rate by more than
    *refi_threshold*, borrowers have incentive to prepay and refinance.
    The CPR increases proportionally to the rate differential.

    Formula:
        incentive = max(0, deal_rate - market_rate - refi_threshold)
        adjusted_cpr = base_cpr × (1 + refi_multiplier × incentive)
        capped at 0.40 (40% annual)

    Args:
        base_cpr: Base annual CPR (e.g., 0.05 = 5%).
        deal_rate: Fixed rate on the deal (decimal).
        market_rate: Current market rate / OIS (decimal).
        refi_multiplier: Sensitivity to refi incentive (default 2.0).
        refi_threshold: Minimum rate gap before refi kicks in (default 50bp).

    Returns:
        Adjusted CPR (annual, decimal). Capped at 0.40.
    """
    incentive = max(0.0, deal_rate - market_rate - refi_threshold)
    adjusted = base_cpr * (1.0 + refi_multiplier * incentive)
    return min(adjusted, 0.40)


def apply_cpr_rate_dependent(
    deals: pd.DataFrame,
    nominal_daily: np.ndarray,
    days: pd.DatetimeIndex,
    ois_matrix: np.ndarray,
    cpr_overrides: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[dict]]:
    """Apply rate-dependent CPR to nominal schedules.

    Unlike ``apply_cpr()`` which uses a constant CPR, this function adjusts
    the prepayment rate based on the relationship between each deal's fixed
    rate and the prevailing OIS rate. When market rates fall below the
    deal rate (refinancing incentive), CPR increases.

    Used primarily for EVE scenario computation where the OIS matrix
    reflects shocked rates.

    Args:
        deals: Deal metadata DataFrame.
        nominal_daily: (n_deals, n_days) original nominal schedule.
        days: DatetimeIndex of the date grid.
        ois_matrix: (n_deals, n_days) OIS rates (may be shocked).
        cpr_overrides: Optional product → base CPR overrides.

    Returns:
        Tuple of (modified nominal_daily, prepayment_log).
    """
    cpr_table = {**DEFAULT_CPR, **(cpr_overrides or {})}
    result = nominal_daily.copy()
    log: list[dict] = []

    if len(days) < 2:
        return result, log

    t0 = days[0]
    day_deltas = np.diff(pd.DatetimeIndex(days).asi8) / (30.4375 * 24 * 3600 * 1e9)  # nanoseconds → month fractions
    day_gaps = np.concatenate(([0.0], day_deltas))

    n_applied = 0
    for i in range(len(deals)):
        deal = deals.iloc[i]
        product = str(deal.get("Product", "")).strip()
        is_floating = bool(deal.get("is_floating", False))

        if is_floating:
            continue

        base_cpr = cpr_table.get(product)
        if base_cpr is None or base_cpr <= 0:
            continue

        # Deal's fixed rate (Clientrate or RateRef)
        deal_rate = float(deal.get("Clientrate", deal.get("RateRef", 0.0)))

        # Per-day adjusted CPR based on OIS level
        alive = nominal_daily[i] != 0
        current_nom = nominal_daily[i, 0]
        if current_nom == 0:
            nonzero = np.nonzero(nominal_daily[i])[0]
            if len(nonzero) == 0:
                continue
            current_nom = nominal_daily[i, nonzero[0]]

        # Vectorized rate-dependent survival via cumulative product
        # Each step's survival depends on that step's CPR (not constant CPR
        # raised to total elapsed time, which is wrong for time-varying CPR).
        market_rates = ois_matrix[i]
        incentive = np.maximum(0.0, deal_rate - market_rates - 0.005)
        cpr_adj = np.minimum(base_cpr * (1.0 + 2.0 * incentive), 0.40)
        per_step_survival = (1.0 - cpr_adj) ** (day_gaps / 12.0)  # day_gaps in months, CPR is annual
        per_step_survival[0] = 1.0  # no decay at t=0
        survival = np.cumprod(per_step_survival)
        result[i] = np.where(alive, abs(current_nom) * survival * np.sign(nominal_daily[i]), 0.0)

        n_applied += 1
        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        final = float(result[i, -1]) if np.any(result[i] != 0) else 0.0

        log.append({
            "deal_id": deal_id,
            "product": product,
            "base_cpr": base_cpr,
            "deal_rate": deal_rate,
            "rate_dependent": True,
            "initial_nominal": round(float(abs(current_nom)), 0),
            "final_nominal": round(abs(final), 0),
            "reduction_pct": round((1 - abs(final) / abs(current_nom)) * 100, 1) if current_nom != 0 else 0.0,
        })

    logger.info("apply_cpr_rate_dependent: applied to %d / %d deals", n_applied, len(deals))
    return result, log
