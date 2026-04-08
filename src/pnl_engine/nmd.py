"""NMD (Non-Maturing Deposits) behavioral model.

Swiss sight deposits (Sichteinlagen) have no contractual maturity but
empirically reprice over 3-7 years. This module replaces contractual
maturity assumptions with behavioral decay profiles.

Standard tiers (SNB/EBA convention):
  - **core**: stable balances, long behavioral maturity (5-7Y), low beta (0.3-0.5)
  - **volatile**: rate-sensitive, short maturity (1-2Y), high beta (0.7-0.9)
  - **term**: contractual maturity, beta=1.0

Key concepts:
  - Decay rate: annual runoff rate — nominal(t) = nominal(0) × exp(-decay × t)
  - Deposit beta: rate passthrough — effective_rate = floor + beta × max(0, OIS - floor)
  - Behavioral maturity: implied repricing horizon (replaces contractual for gap analysis)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.matrices import broadcast_mm, days_to_years

logger = logging.getLogger(__name__)


def _match_profile(profiles: pd.DataFrame, product: str, currency: str, direction: str) -> pd.DataFrame:
    """Match NMD profiles by deal attributes."""
    mask = pd.Series([True] * len(profiles), index=profiles.index)
    if "product" in profiles.columns:
        mask &= profiles["product"] == product
    if "currency" in profiles.columns:
        mask &= profiles["currency"] == currency
    if "direction" in profiles.columns:
        mask &= profiles["direction"] == direction
    return profiles[mask]


def _profile_weights(matched: pd.DataFrame) -> pd.Series:
    """Compute normalized weights for matched NMD profiles."""
    if len(matched) <= 1:
        return pd.Series([1.0], index=matched.index)
    if "share" in matched.columns:
        shares = pd.to_numeric(matched["share"], errors="coerce").fillna(0)
        total = shares.sum()
        if total > 0:
            return shares / total
    return pd.Series([1.0 / len(matched)] * len(matched), index=matched.index)


def _normalize_profiles(nmd_profiles: pd.DataFrame) -> pd.DataFrame:
    """Copy and normalize NMD profile columns (strip/upper)."""
    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()
    return profiles


def compute_stressed_beta(
    beta_base: float,
    shock_bps: float,
    beta_stress: float = 0.1,
    threshold_bps: float = 200.0,
) -> float:
    """Compute stress-adjusted deposit beta.

    Under large rate shocks (>threshold), depositors demand more passthrough.
    Beta increases linearly beyond the threshold.

    Formula:
        beta = beta_base + beta_stress × max(0, |shock| - threshold) / 100
        Capped at 1.0.

    Args:
        beta_base: Base deposit beta (e.g., 0.6).
        shock_bps: Rate shock in basis points (absolute value used).
        beta_stress: Beta increase per 100bp above threshold (default 0.1).
        threshold_bps: Shock level before stress kicks in (default 200bp).

    Returns:
        Stress-adjusted beta, capped at 1.0.
    """
    excess = max(0.0, abs(shock_bps) - threshold_bps)
    adjusted = beta_base + beta_stress * excess / 100.0
    return min(adjusted, 1.0)


def compute_stressed_decay(
    decay_base: float,
    shock_bps: float,
    decay_stress: float = 0.05,
    threshold_bps: float = 200.0,
) -> float:
    """Compute stress-adjusted NMD decay rate.

    Under large rate shocks, deposits run off faster as rate-sensitive
    depositors seek higher returns elsewhere.

    Formula:
        decay = decay_base + decay_stress × max(0, |shock| - threshold) / 100

    Args:
        decay_base: Base annual decay rate (e.g., 0.15).
        shock_bps: Rate shock in basis points (absolute value used).
        decay_stress: Decay increase per 100bp above threshold (default 0.05).
        threshold_bps: Shock level before stress kicks in (default 200bp).

    Returns:
        Stress-adjusted decay rate.
    """
    excess = max(0.0, abs(shock_bps) - threshold_bps)
    return decay_base + decay_stress * excess / 100.0


def apply_nmd_decay(
    deals: pd.DataFrame,
    nmd_profiles: pd.DataFrame,
    nominal_daily: np.ndarray,
    days: pd.DatetimeIndex,
    date_run: datetime,
) -> tuple[np.ndarray, list[dict]]:
    """Replace contractual nominal schedule with behavioral decay profile.

    For NMD deals (matched by product/currency/direction/tier):
        nominal(t) = nominal(0) × exp(-decay_rate × t_years)

    For non-NMD deals or unmatched: unchanged.

    Args:
        deals: Deal metadata DataFrame.
        nmd_profiles: NMD profile definitions with columns:
            product, currency, direction, tier, behavioral_maturity_years,
            decay_rate, deposit_beta, floor_rate.
        nominal_daily: (n_deals, n_days) original nominal schedule.
        days: DatetimeIndex of the date grid.
        date_run: Reference date.

    Returns:
        Tuple of (modified nominal_daily, match_log) where match_log is a list
        of dicts with deal-level NMD matching details for audit trail.
    """
    if nmd_profiles is None or nmd_profiles.empty:
        return nominal_daily, []

    result = nominal_daily.copy()
    date_run_ts = pd.Timestamp(date_run)
    day_years = np.maximum(days_to_years(days, date_run), 0.0)

    profiles = _normalize_profiles(nmd_profiles)

    matched_count = 0
    match_log: list[dict] = []

    for i in range(len(deals)):
        deal = deals.iloc[i]
        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        product = str(deal.get("Product", "")).strip().upper()
        currency = str(deal.get("Currency", "")).strip().upper()
        direction = str(deal.get("Direction", "")).strip().upper()

        # Match against NMD profiles
        matched = _match_profile(profiles, product, currency, direction)
        if matched.empty:
            continue

        # Weighted blend of multiple profiles (e.g., core + volatile tiers)
        weights = _profile_weights(matched)

        decay_rate = float((pd.to_numeric(matched.get("decay_rate", 0), errors="coerce").fillna(0) * weights).sum())
        deposit_beta = float((pd.to_numeric(matched.get("deposit_beta", 1), errors="coerce").fillna(1) * weights).sum())
        floor_rate = float((pd.to_numeric(matched.get("floor_rate", 0), errors="coerce").fillna(0) * weights).sum())
        behavioral_maturity = float((pd.to_numeric(matched.get("behavioral_maturity_years", 0), errors="coerce").fillna(0) * weights).sum())
        tier = "+".join(matched["tier"].astype(str).unique()) if "tier" in matched.columns else "blended"

        if decay_rate <= 0:
            match_log.append({
                "deal_id": deal_id, "product": product, "currency": currency,
                "direction": direction, "tier": tier, "decay_rate": 0.0,
                "deposit_beta": deposit_beta, "floor_rate": floor_rate,
                "behavioral_maturity_years": behavioral_maturity,
                "applied": False, "reason": "decay_rate <= 0",
            })
            continue

        # Get initial nominal (first non-zero value)
        initial_nominal = nominal_daily[i, 0]
        if initial_nominal == 0:
            # Find first non-zero
            nonzero = np.nonzero(nominal_daily[i])[0]
            if len(nonzero) == 0:
                match_log.append({
                    "deal_id": deal_id, "product": product, "currency": currency,
                    "direction": direction, "tier": tier, "decay_rate": decay_rate,
                    "deposit_beta": deposit_beta, "floor_rate": floor_rate,
                    "behavioral_maturity_years": behavioral_maturity,
                    "applied": False, "reason": "zero_nominal",
                })
                continue
            initial_nominal = nominal_daily[i, nonzero[0]]

        # Apply exponential decay at month boundaries (constant within each month)
        month_periods = days.to_period("M")
        unique_months = month_periods.unique()
        alive = nominal_daily[i] != 0
        for m in unique_months:
            month_mask = (month_periods == m)
            if not month_mask.any():
                continue
            m_start_years = max(0.0, (m.start_time - date_run_ts).days / 365)
            m_decay = initial_nominal * np.exp(-decay_rate * m_start_years)
            result[i, month_mask] = np.where(
                alive[month_mask],
                np.sign(nominal_daily[i, month_mask]) * np.abs(m_decay),
                0.0,
            )
        matched_count += 1

        match_log.append({
            "deal_id": deal_id, "product": product, "currency": currency,
            "direction": direction, "tier": tier, "decay_rate": decay_rate,
            "deposit_beta": deposit_beta, "floor_rate": floor_rate,
            "behavioral_maturity_years": behavioral_maturity,
            "initial_nominal": float(initial_nominal),
            "applied": True, "reason": "ok",
        })

    logger.info("apply_nmd_decay: applied to %d / %d deals", matched_count, len(deals))
    return result, match_log


def apply_deposit_beta(
    rate_matrix: np.ndarray,
    deals: pd.DataFrame,
    nmd_profiles: pd.DataFrame,
    ois_matrix: np.ndarray,
    shock_bps: float = 0.0,
) -> np.ndarray:
    """Adjust client rates for deposit beta.

    Effective client rate = floor_rate + beta × max(0, OIS - floor_rate)

    For deposits with beta < 1.0, rate passthrough is partial:
    when OIS rises by 100bp, client rate only rises by beta × 100bp.

    When ``shock_bps`` is provided and exceeds the stress threshold (200bp),
    beta is adjusted upward via ``compute_stressed_beta()`` to reflect
    increased depositor rate sensitivity under large shocks.

    Args:
        rate_matrix: (n_deals, n_days) original client rate matrix.
        deals: Deal metadata.
        nmd_profiles: NMD profile definitions.
        ois_matrix: (n_deals, n_days) OIS forward rates.
        shock_bps: Rate shock in basis points (default 0 = no stress adjustment).

    Returns:
        Modified rate_matrix with beta-adjusted rates for NMD deals.
    """
    if nmd_profiles is None or nmd_profiles.empty:
        return rate_matrix

    result = rate_matrix.copy()

    profiles = _normalize_profiles(nmd_profiles)

    for i in range(len(deals)):
        product = str(deals.iloc[i].get("Product", "")).strip().upper()
        currency = str(deals.iloc[i].get("Currency", "")).strip().upper()
        direction = str(deals.iloc[i].get("Direction", "")).strip().upper()

        matched = _match_profile(profiles, product, currency, direction)
        if matched.empty:
            continue

        # Weighted blend of multiple profiles
        w = _profile_weights(matched)

        beta = float((pd.to_numeric(matched.get("deposit_beta", 1), errors="coerce").fillna(1) * w).sum())
        floor_rate = float((pd.to_numeric(matched.get("floor_rate", 0), errors="coerce").fillna(0) * w).sum())

        # Apply stress adjustment if shock is large
        if shock_bps != 0.0:
            beta = compute_stressed_beta(beta, shock_bps)

        if beta >= 1.0:
            continue  # No adjustment needed

        # Effective rate = floor + beta × max(0, OIS - floor)
        result[i] = floor_rate + beta * np.maximum(0, ois_matrix[i] - floor_rate)

    return result


def compute_nmd_beta_sensitivity(
    deals: pd.DataFrame,
    nmd_profiles: pd.DataFrame,
    rate_matrix: np.ndarray,
    ois_matrix: np.ndarray,
    nominal_daily: np.ndarray,
    mm_vector: np.ndarray,
    delta: float = 0.1,
) -> dict:
    """Estimate NII sensitivity to deposit beta perturbation (±delta).

    Re-runs the NII calculation with beta ± delta for each NMD profile group,
    returning the impact per currency.

    Args:
        deals: Deal metadata DataFrame.
        nmd_profiles: NMD profile definitions.
        rate_matrix: (n_deals, n_days) original rate matrix.
        ois_matrix: (n_deals, n_days) OIS rates.
        nominal_daily: (n_deals, n_days) nominal schedule.
        mm_vector: (n_deals,) day-count divisor per deal.
        delta: Beta perturbation amount (default 0.1).

    Returns:
        Dict with per-currency sensitivity: {"CHF": {"beta_up_nii": ..., "beta_down_nii": ..., "delta_nii": ...}, ...}
    """
    if nmd_profiles is None or nmd_profiles.empty:
        return {}

    def _compute_nii(perturbed_rates: np.ndarray) -> float:
        """Sum daily NII = Nominal × (OIS - Rate) / MM."""
        mm_2d = broadcast_mm(mm_vector)
        daily_pnl = nominal_daily * (ois_matrix - perturbed_rates) / mm_2d
        return float(np.nansum(daily_pnl))

    # Base NII
    base_rates = apply_deposit_beta(rate_matrix, deals, nmd_profiles, ois_matrix)
    base_nii = _compute_nii(base_rates)

    # Create perturbed profiles
    profiles_up = nmd_profiles.copy()
    profiles_down = nmd_profiles.copy()
    if "deposit_beta" in profiles_up.columns:
        betas = pd.to_numeric(profiles_up["deposit_beta"], errors="coerce").fillna(1.0)
        profiles_up["deposit_beta"] = np.minimum(betas + delta, 1.0)
        profiles_down["deposit_beta"] = np.maximum(betas - delta, 0.0)

    up_rates = apply_deposit_beta(rate_matrix, deals, profiles_up, ois_matrix)
    down_rates = apply_deposit_beta(rate_matrix, deals, profiles_down, ois_matrix)

    up_nii = _compute_nii(up_rates)
    down_nii = _compute_nii(down_rates)

    # Per-currency breakdown
    result: dict[str, dict] = {}
    currencies = deals["Currency"].str.strip().str.upper().unique() if "Currency" in deals.columns else []

    for ccy in currencies:
        ccy_mask = deals["Currency"].str.strip().str.upper() == ccy
        idx = np.where(ccy_mask.values)[0]
        if len(idx) == 0:
            continue
        mm_2d = broadcast_mm(mm_vector[idx])
        base_ccy = float(np.nansum(nominal_daily[idx] * (ois_matrix[idx] - base_rates[idx]) / mm_2d))
        up_ccy = float(np.nansum(nominal_daily[idx] * (ois_matrix[idx] - up_rates[idx]) / mm_2d))
        down_ccy = float(np.nansum(nominal_daily[idx] * (ois_matrix[idx] - down_rates[idx]) / mm_2d))

        result[ccy] = {
            "base_nii": round(base_ccy, 0),
            "beta_up_nii": round(up_ccy, 0),
            "beta_down_nii": round(down_ccy, 0),
            "delta_up": round(up_ccy - base_ccy, 0),
            "delta_down": round(down_ccy - base_ccy, 0),
        }

    return {
        "has_data": len(result) > 0,
        "total": {
            "base_nii": round(base_nii, 0),
            "beta_up_nii": round(up_nii, 0),
            "beta_down_nii": round(down_nii, 0),
            "delta_up": round(up_nii - base_nii, 0),
            "delta_down": round(down_nii - base_nii, 0),
        },
        "by_currency": result,
        "delta": delta,
    }


def get_behavioral_maturity(
    deals: pd.DataFrame,
    nmd_profiles: pd.DataFrame,
) -> pd.Series:
    """Get behavioral maturity for each deal (for repricing gap analysis).

    Returns Series of maturity in years. For non-NMD deals, returns NaN
    (caller should fall back to contractual maturity).
    """
    if nmd_profiles is None or nmd_profiles.empty:
        return pd.Series([np.nan] * len(deals), index=deals.index)

    profiles = _normalize_profiles(nmd_profiles)

    result = pd.Series([np.nan] * len(deals), index=deals.index)

    for i in range(len(deals)):
        product = str(deals.iloc[i].get("Product", "")).strip().upper()
        currency = str(deals.iloc[i].get("Currency", "")).strip().upper()
        direction = str(deals.iloc[i].get("Direction", "")).strip().upper()

        matched = _match_profile(profiles, product, currency, direction)
        if not matched.empty:
            bm_values = pd.to_numeric(matched.get("behavioral_maturity_years", np.nan), errors="coerce")
            if len(matched) > 1:
                w = _profile_weights(matched)
                result.iloc[i] = float((bm_values.fillna(0) * w).sum())
            else:
                result.iloc[i] = float(bm_values.iloc[0]) if pd.notna(bm_values.iloc[0]) else np.nan

    return result
