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

logger = logging.getLogger(__name__)


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
    day_years = np.array([(d - date_run_ts).days / 365.25 for d in days])
    day_years = np.maximum(day_years, 0.0)

    # Normalize profile columns
    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    matched_count = 0
    match_log: list[dict] = []

    for i in range(len(deals)):
        deal = deals.iloc[i]
        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        product = str(deal.get("Product", "")).strip().upper()
        currency = str(deal.get("Currency", "")).strip().upper()
        direction = str(deal.get("Direction", "")).strip().upper()

        # Match against NMD profiles
        mask = pd.Series([True] * len(profiles))
        if "product" in profiles.columns:
            mask &= profiles["product"] == product
        if "currency" in profiles.columns:
            mask &= profiles["currency"] == currency
        if "direction" in profiles.columns:
            mask &= profiles["direction"] == direction

        matched = profiles[mask]
        if matched.empty:
            continue

        # Use the first matching profile (could be core/volatile — use weighted if multiple)
        profile = matched.iloc[0]
        tier = str(profile.get("tier", "unknown"))
        decay_rate = float(profile.get("decay_rate", 0.0))
        deposit_beta = float(profile.get("deposit_beta", 1.0))
        floor_rate = float(profile.get("floor_rate", 0.0))
        behavioral_maturity = float(profile.get("behavioral_maturity_years", 0.0))

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

        # Apply exponential decay
        decayed = initial_nominal * np.exp(-decay_rate * day_years)

        # Only apply where deal is alive (non-zero in original)
        alive = nominal_daily[i] != 0
        result[i] = np.where(alive, np.sign(nominal_daily[i]) * np.abs(decayed), 0.0)
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
) -> np.ndarray:
    """Adjust client rates for deposit beta.

    Effective client rate = floor_rate + beta × max(0, OIS - floor_rate)

    For deposits with beta < 1.0, rate passthrough is partial:
    when OIS rises by 100bp, client rate only rises by beta × 100bp.

    Args:
        rate_matrix: (n_deals, n_days) original client rate matrix.
        deals: Deal metadata.
        nmd_profiles: NMD profile definitions.
        ois_matrix: (n_deals, n_days) OIS forward rates.

    Returns:
        Modified rate_matrix with beta-adjusted rates for NMD deals.
    """
    if nmd_profiles is None or nmd_profiles.empty:
        return rate_matrix

    result = rate_matrix.copy()

    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    for i in range(len(deals)):
        product = str(deals.iloc[i].get("Product", "")).strip().upper()
        currency = str(deals.iloc[i].get("Currency", "")).strip().upper()
        direction = str(deals.iloc[i].get("Direction", "")).strip().upper()

        mask = pd.Series([True] * len(profiles))
        if "product" in profiles.columns:
            mask &= profiles["product"] == product
        if "currency" in profiles.columns:
            mask &= profiles["currency"] == currency
        if "direction" in profiles.columns:
            mask &= profiles["direction"] == direction

        matched = profiles[mask]
        if matched.empty:
            continue

        profile = matched.iloc[0]
        beta = float(profile.get("deposit_beta", 1.0))
        floor_rate = float(profile.get("floor_rate", 0.0))

        if beta >= 1.0:
            continue  # No adjustment needed

        # Effective rate = floor + beta × max(0, OIS - floor)
        result[i] = floor_rate + beta * np.maximum(0, ois_matrix[i] - floor_rate)

    return result


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

    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    result = pd.Series([np.nan] * len(deals), index=deals.index)

    for i in range(len(deals)):
        product = str(deals.iloc[i].get("Product", "")).strip().upper()
        currency = str(deals.iloc[i].get("Currency", "")).strip().upper()
        direction = str(deals.iloc[i].get("Direction", "")).strip().upper()

        mask = pd.Series([True] * len(profiles))
        if "product" in profiles.columns:
            mask &= profiles["product"] == product
        if "currency" in profiles.columns:
            mask &= profiles["currency"] == currency
        if "direction" in profiles.columns:
            mask &= profiles["direction"] == direction

        matched = profiles[mask]
        if not matched.empty:
            result.iloc[i] = float(matched.iloc[0].get("behavioral_maturity_years", np.nan))

    return result
