"""NMD back-test: modeled vs actual deposit runoff comparison.

Compares the exponential decay model predictions against actual historical
deposit balance observations. Computes R-squared and RMSE to validate
the behavioral model assumptions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_nmd_model(
    actual_balances: pd.DataFrame,
    nmd_profiles: pd.DataFrame,
) -> dict:
    """Compare modeled decay with actual deposit balance history.

    Args:
        actual_balances: DataFrame with columns:
            date, product, currency, direction, balance
        nmd_profiles: NMD profile definitions with decay_rate, deposit_beta, etc.

    Returns:
        Dict with per-group back-test metrics (R², RMSE, MAE).
    """
    if actual_balances is None or actual_balances.empty:
        return {"has_data": False, "groups": []}
    if nmd_profiles is None or nmd_profiles.empty:
        return {"has_data": False, "groups": []}

    # Normalize
    ab = actual_balances.copy()
    ab["date"] = pd.to_datetime(ab["date"])
    for col in ["product", "currency", "direction"]:
        if col in ab.columns:
            ab[col] = ab[col].str.strip().str.upper()

    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    groups = []
    group_cols = [c for c in ["product", "currency", "direction"] if c in ab.columns]
    if not group_cols:
        return {"has_data": False, "groups": []}

    for keys, grp in ab.groupby(group_cols):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_dict = dict(zip(group_cols, keys))

        # Find matching profile
        mask = pd.Series([True] * len(profiles), index=profiles.index)
        for col, val in key_dict.items():
            if col in profiles.columns:
                mask &= profiles[col] == val
        matched = profiles[mask]
        if matched.empty:
            continue

        # Use weighted average decay rate
        if len(matched) > 1 and "share" in matched.columns:
            shares = pd.to_numeric(matched["share"], errors="coerce").fillna(0)
            total = shares.sum()
            w = shares / total if total > 0 else pd.Series([1.0 / len(matched)] * len(matched), index=matched.index)
        else:
            w = pd.Series([1.0 / len(matched)] * len(matched), index=matched.index)

        decay_rate = float((pd.to_numeric(matched.get("decay_rate", 0), errors="coerce").fillna(0) * w).sum())
        if decay_rate <= 0:
            continue

        grp = grp.sort_values("date")
        t0 = grp["date"].iloc[0]
        initial_balance = float(grp["balance"].iloc[0])
        if initial_balance == 0:
            continue

        # Compute modeled balances
        t_years = np.array([(d - t0).days / 365.0 for d in grp["date"]])
        modeled = initial_balance * np.exp(-decay_rate * t_years)
        actual = grp["balance"].values.astype(float)

        # Metrics
        residuals = actual - modeled
        ss_res = float(np.sum(residuals**2))
        ss_tot = float(np.sum((actual - actual.mean())**2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        rmse = float(np.sqrt(np.mean(residuals**2)))
        mae = float(np.mean(np.abs(residuals)))

        groups.append({
            **key_dict,
            "decay_rate": decay_rate,
            "initial_balance": round(initial_balance, 0),
            "n_observations": len(grp),
            "r_squared": round(r_squared, 4),
            "rmse": round(rmse, 0),
            "mae": round(mae, 0),
            "modeled_final": round(float(modeled[-1]), 0),
            "actual_final": round(float(actual[-1]), 0),
        })

    return {
        "has_data": len(groups) > 0,
        "groups": groups,
        "n_groups": len(groups),
        "avg_r_squared": round(np.mean([g["r_squared"] for g in groups]), 4) if groups else 0.0,
    }
