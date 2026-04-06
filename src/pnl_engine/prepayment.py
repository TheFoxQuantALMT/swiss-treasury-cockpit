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
    month_fracs = np.array([(d - t0).days / 30.44 for d in days])
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
