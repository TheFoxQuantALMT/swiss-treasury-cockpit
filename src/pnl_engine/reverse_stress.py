"""Reverse stress test — find the shock level that breaches a given limit.

Uses bisection to find the parallel rate shock (in bp) at which NII or
ΔEVE first breaches a threshold. This answers "how large must the shock
be before we fail?" rather than "what is the impact of a given shock?".
"""
from __future__ import annotations

from typing import Callable

import numpy as np


def bisect_breach_shock(
    evaluate_fn: Callable[[float], float],
    threshold: float,
    low_bp: float = 0.0,
    high_bp: float = 500.0,
    tol_bp: float = 1.0,
    max_iter: int = 50,
    direction: str = "below",
) -> dict:
    """Find the shock level at which *evaluate_fn(shock_bp)* crosses *threshold*.

    Args:
        evaluate_fn: Function that takes a shock in bp and returns a metric
            (e.g., NII under that shock). Must be monotonic in the search range.
        threshold: The limit value to breach.
        low_bp: Lower bound of search range (bp).
        high_bp: Upper bound of search range (bp).
        tol_bp: Convergence tolerance (bp).
        max_iter: Maximum iterations.
        direction: "below" means breach when metric < threshold,
                   "above" means breach when metric > threshold.

    Returns:
        Dict with "breach_shock_bp", "breach_value", "converged", "iterations".
    """
    f_low = evaluate_fn(low_bp)
    f_high = evaluate_fn(high_bp)

    def _breached(val: float) -> bool:
        if direction == "below":
            return val < threshold
        return val > threshold

    # Check if breach occurs at all within range
    if not _breached(f_high) and not _breached(f_low):
        return {
            "breach_shock_bp": None,
            "breach_value": None,
            "converged": True,
            "iterations": 0,
            "message": f"No breach within [{low_bp}, {high_bp}] bp range",
        }

    if _breached(f_low):
        return {
            "breach_shock_bp": round(low_bp, 1),
            "breach_value": round(f_low, 0),
            "converged": True,
            "iterations": 0,
            "message": "Already breached at lower bound",
        }

    for i in range(max_iter):
        mid_bp = (low_bp + high_bp) / 2.0
        f_mid = evaluate_fn(mid_bp)

        if _breached(f_mid):
            high_bp = mid_bp
        else:
            low_bp = mid_bp

        if abs(high_bp - low_bp) < tol_bp:
            return {
                "breach_shock_bp": round(high_bp, 1),
                "breach_value": round(evaluate_fn(high_bp), 0),
                "converged": True,
                "iterations": i + 1,
                "message": f"Converged in {i + 1} iterations",
            }

    return {
        "breach_shock_bp": round(high_bp, 1),
        "breach_value": round(evaluate_fn(high_bp), 0),
        "converged": False,
        "iterations": max_iter,
        "message": f"Did not converge within {max_iter} iterations (residual: {abs(high_bp - low_bp):.1f}bp)",
    }


def reverse_stress_nii(
    base_nii: float,
    sensitivity_per_bp: float,
    limit: float,
    **kwargs,
) -> dict:
    """Simplified reverse stress for NII using linear sensitivity.

    Args:
        base_nii: Base case NII.
        sensitivity_per_bp: ΔNII per 1bp parallel shift.
        limit: NII limit (breach when NII drops below this).

    Returns:
        Bisection result dict.
    """
    def eval_fn(shock_bp: float) -> float:
        return base_nii + sensitivity_per_bp * shock_bp

    return bisect_breach_shock(eval_fn, limit, direction="below", **kwargs)


def reverse_stress_eve(
    base_eve: float,
    tier1_capital: float,
    dv01: float,
    threshold_pct: float = 15.0,
    **kwargs,
) -> dict:
    """Simplified reverse stress for ΔEVE/Tier1 using DV01 approximation.

    Finds the shock where |ΔEVE|/Tier1 exceeds threshold_pct.

    Args:
        base_eve: Base EVE.
        tier1_capital: Tier 1 capital.
        dv01: DV01 (EVE change per 1bp).
        threshold_pct: IRRBB outlier threshold (default 15%).

    Returns:
        Bisection result dict.
    """
    if tier1_capital <= 0:
        return {"breach_shock_bp": None, "message": "Tier 1 capital not provided"}

    limit_delta_eve = tier1_capital * threshold_pct / 100.0

    def eval_fn(shock_bp: float) -> float:
        # ΔEVE ≈ DV01 × shock_bp, return the headroom
        return limit_delta_eve - abs(dv01 * shock_bp)

    return bisect_breach_shock(eval_fn, 0.0, direction="below", **kwargs)
