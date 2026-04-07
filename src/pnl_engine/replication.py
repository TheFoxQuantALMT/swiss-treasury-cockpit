"""Replication portfolio for NMD behavioral cashflows.

Fits a portfolio of fixed-rate bonds at standard tenors (1Y, 2Y, 3Y, 5Y, 7Y)
to replicate the NMD behavioral decay cashflow profile using least-squares
optimization. This determines the optimal maturity mix for hedging NMD exposure.
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


# Standard replication tenors (years)
REPLICATION_TENORS: list[float] = [1.0, 2.0, 3.0, 5.0, 7.0]


def _constrained_nnls(A: np.ndarray, b: np.ndarray, max_iter: int = 100, tol: float = 1e-8) -> np.ndarray:
    """Non-negative least squares via iterative clip-normalize-resolve.

    Starts from unconstrained solution, then iterates: clip negatives,
    resolve LS on the active (positive) set, normalize. Converges to a
    good non-negative approximation without scipy.

    Falls back to single-step clip-normalize if iteration does not converge.
    """
    n = A.shape[1]

    # Start from unconstrained solution
    ATA = A.T @ A
    ATb = A.T @ b
    try:
        weights = np.linalg.solve(ATA, ATb)
    except np.linalg.LinAlgError:
        weights, _, _, _ = np.linalg.lstsq(A, b, rcond=None)

    for _ in range(max_iter):
        prev = weights.copy()
        # Clip negatives
        weights = np.maximum(weights, 0.0)
        # Identify active set (positive weights)
        active = weights > 0
        if not active.any():
            weights = np.ones(n) / n
            break
        # Re-solve LS on active columns only
        A_active = A[:, active]
        ATA_a = A_active.T @ A_active
        ATb_a = A_active.T @ b
        try:
            w_active = np.linalg.solve(ATA_a, ATb_a)
        except np.linalg.LinAlgError:
            logger.warning("replication NNLS: singular matrix on active set, using clipped weights")
            break
        weights = np.zeros(n)
        weights[active] = w_active
        # Check convergence
        if np.max(np.abs(weights - prev)) < tol:
            break

    # Final clip and normalize
    weights = np.maximum(weights, 0.0)
    s = weights.sum()
    if s > 0:
        weights = weights / s

    return weights


def build_replication_portfolio(
    behavioral_cashflows: np.ndarray,
    day_years: np.ndarray,
    tenors: list[float] | None = None,
    total_nominal: float = 1.0,
) -> dict:
    """Fit a replication portfolio to NMD behavioral cashflows.

    Args:
        behavioral_cashflows: (n_days,) array of decayed cashflows (normalized
            so that cashflow[0] = 1.0 or proportional).
        day_years: (n_days,) array of year fractions from reference date.
        tenors: Replication instrument tenors in years (default: 1,2,3,5,7).
        total_nominal: Total nominal to allocate across tenors.

    Returns:
        Dict with "weights" (per tenor), "fit_r_squared", "residual_norm".
    """
    if behavioral_cashflows is None or len(behavioral_cashflows) == 0:
        return {"has_data": False}

    tenors = tenors or REPLICATION_TENORS
    n = len(behavioral_cashflows)

    # Normalize behavioral cashflows
    cf = behavioral_cashflows.astype(float)
    if cf[0] != 0:
        cf = cf / cf[0]

    # Build basis functions: each tenor is a flat cashflow until maturity, then zero
    # This represents a bullet bond at each tenor
    A = np.zeros((n, len(tenors)))
    for j, tenor in enumerate(tenors):
        A[:, j] = np.where(day_years <= tenor, 1.0, 0.0)

    # Non-negative least squares via projected gradient descent (numpy only)
    weights = _constrained_nnls(A, cf)
    w_sum = weights.sum()
    if w_sum <= 0:
        # Equal allocation fallback
        weights = np.ones(len(tenors)) / len(tenors)

    # Compute fit quality
    fitted = A @ weights  # weights already sum to 1.0 after normalization
    residuals = cf - fitted
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((cf - cf.mean())**2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Weighted average maturity of replication portfolio
    wam = float(np.sum(weights * np.array(tenors)))

    portfolio = []
    for j, tenor in enumerate(tenors):
        portfolio.append({
            "tenor": tenor,
            "tenor_label": f"{int(tenor)}Y" if tenor == int(tenor) else f"{tenor}Y",
            "weight": round(float(weights[j]), 4),
            "nominal": round(float(weights[j] * total_nominal), 0),
        })

    return {
        "has_data": True,
        "tenors": tenors,
        "portfolio": portfolio,
        "weights": [round(float(w), 4) for w in weights],
        "weighted_avg_maturity": round(wam, 2),
        "r_squared": round(r_squared, 4),
        "residual_norm": round(float(np.sqrt(ss_res)), 4),
    }
