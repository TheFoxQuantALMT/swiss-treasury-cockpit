"""EVE (Economic Value of Equity) computation — BCBS 368 requirement.

Computes present value of future cash flows for each deal by discounting
at OIS forward rates. Supports scenario-based ΔEVE computation.

EVE complements NII (earnings-based) with an economic-value perspective:
  - NII measures interest income over a horizon (typically 12M)
  - EVE measures the present value of ALL future cash flows (full duration)

Key metrics:
  - EVE base: PV of future cash flows at current OIS rates
  - ΔEVE: change in EVE under stressed rate scenarios
  - Modified duration: % change in EVE per 1bp rate shift
  - Key rate duration (KRD): duration at each BCBS tenor point
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.config import CURRENCY_TO_OIS

logger = logging.getLogger(__name__)


def compute_eve(
    nominal_daily: np.ndarray,
    ois_matrix: np.ndarray,
    rate_matrix: np.ndarray,
    mm_vector: np.ndarray,
    days: pd.DatetimeIndex,
    deals: pd.DataFrame,
    date_run: datetime,
) -> pd.DataFrame:
    """Compute Economic Value of Equity per deal.

    EVE per deal = Σ_t [ CashFlow(t) × DiscountFactor(t) ]
    where:
      CashFlow(t) = Nominal(t) × (ClientRate - 0) / MM  (net interest cash flow)
      DiscountFactor(t) = exp(-OIS_fwd(t) × t_years)

    For a simpler and more robust approach: we compute the PV of
    the net interest margin (Nominal × ClientRate / MM) discounted at OIS.

    Args:
        nominal_daily: (n_deals, n_days) nominal schedule.
        ois_matrix: (n_deals, n_days) OIS forward rates.
        rate_matrix: (n_deals, n_days) client/reference rates.
        mm_vector: (n_deals,) day count divisor.
        days: DatetimeIndex of the date grid.
        deals: DataFrame with deal metadata.
        date_run: Reference date.

    Returns:
        DataFrame with columns: deal_idx, currency, direction, product,
        eve, duration, notional_avg, counterparty.
    """
    n_deals, n_days = nominal_daily.shape
    date_run_ts = pd.Timestamp(date_run)

    # Year fractions from date_run for each day
    day_years = np.array([(d - date_run_ts).days / 365.25 for d in days])
    day_years = np.maximum(day_years, 0.0)  # no negative time

    # Discount factors: exp(-OIS × t)
    # Use cumulative average OIS for discounting (term rate approximation)
    discount_factors = np.exp(-ois_matrix * day_years[np.newaxis, :])

    # Daily cash flow: Nominal × Rate / MM (the interest income stream)
    mm_broadcast = mm_vector[:, np.newaxis] * np.ones((1, n_days))
    daily_cf = nominal_daily * rate_matrix / mm_broadcast

    # Also include the notional principal return at maturity
    # Detect maturity: last day where nominal is non-zero
    # Principal CF = nominal change (negative = amortization/return)
    nominal_shift = np.zeros_like(nominal_daily)
    nominal_shift[:, 1:] = nominal_daily[:, 1:] - nominal_daily[:, :-1]
    # At maturity, nominal drops to 0 → negative shift = principal return
    # We discount this too
    total_cf = daily_cf - nominal_shift  # subtract because negative shift = cash inflow

    # PV of all cash flows
    pv_daily = total_cf * discount_factors
    eve_per_deal = pv_daily.sum(axis=1)

    # Modified duration: -1/EVE × dEVE/dr ≈ Σ(t × CF × DF) / EVE
    weighted_time = (total_cf * discount_factors * day_years[np.newaxis, :]).sum(axis=1)
    with np.errstate(divide='ignore', invalid='ignore'):
        duration = np.where(
            np.abs(eve_per_deal) > 1e-6,
            weighted_time / eve_per_deal,
            0.0,
        )

    # Average notional for sizing
    alive_mask = np.abs(nominal_daily) > 0
    notional_sum = np.abs(nominal_daily).sum(axis=1)
    alive_days = alive_mask.sum(axis=1).clip(min=1)
    notional_avg = notional_sum / alive_days

    # Build result
    result = pd.DataFrame({
        "deal_idx": range(n_deals),
        "eve": eve_per_deal,
        "duration": duration,
        "notional_avg": notional_avg,
    })

    # Enrich with metadata
    for col in ["Currency", "Direction", "Product", "Counterparty", "Dealid", "Périmètre TOTAL"]:
        if col in deals.columns:
            result[col] = deals[col].values[:n_deals]

    return result


def compute_eve_scenarios(
    nominal_daily: np.ndarray,
    ois_matrix_base: np.ndarray,
    rate_matrix: np.ndarray,
    mm_vector: np.ndarray,
    days: pd.DatetimeIndex,
    deals: pd.DataFrame,
    date_run: datetime,
    scenarios: pd.DataFrame,
    base_curves: pd.DataFrame,
) -> pd.DataFrame:
    """Compute ΔEVE for each BCBS 368 scenario.

    Args:
        nominal_daily: (n_deals, n_days) nominal schedule.
        ois_matrix_base: (n_deals, n_days) base OIS rates.
        rate_matrix: (n_deals, n_days) client rates.
        mm_vector: (n_deals,) day count divisor.
        days: DatetimeIndex.
        deals: Deal metadata DataFrame.
        date_run: Reference date.
        scenarios: BCBS scenario definitions.
        base_curves: Base OIS forward curves DataFrame.

    Returns:
        DataFrame: scenario, currency, eve_base, eve_shocked, delta_eve, pct_change.
    """
    from pnl_engine.scenarios import interpolate_scenario_shifts, apply_scenario_to_curves
    from pnl_engine.engine import _build_ois_matrix

    # Base EVE
    eve_base = compute_eve(
        nominal_daily, ois_matrix_base, rate_matrix, mm_vector,
        days, deals, date_run,
    )

    scenario_names = sorted(scenarios["scenario"].unique())
    results = []

    for sc_name in scenario_names:
        # Build shifted curves
        shifted_curves = base_curves.copy()
        currencies_in_deals = deals["Currency"].unique() if "Currency" in deals.columns else []

        for ccy in currencies_in_deals:
            ois_indice = CURRENCY_TO_OIS.get(ccy)
            if not ois_indice:
                continue
            shift_array = interpolate_scenario_shifts(
                scenarios, sc_name, ccy, days, date_run,
            )
            shifted_curves = apply_scenario_to_curves(
                shifted_curves, shift_array, ois_indice,
            )

        # Build shocked OIS matrix
        ois_matrix_shocked = _build_ois_matrix(deals, shifted_curves, days)

        # Compute shocked EVE
        eve_shocked = compute_eve(
            nominal_daily, ois_matrix_shocked, rate_matrix, mm_vector,
            days, deals, date_run,
        )

        # Aggregate by currency
        for ccy in currencies_in_deals:
            base_mask = eve_base["Currency"] == ccy if "Currency" in eve_base.columns else pd.Series([True] * len(eve_base))
            shocked_mask = eve_shocked["Currency"] == ccy if "Currency" in eve_shocked.columns else pd.Series([True] * len(eve_shocked))

            eve_b = eve_base.loc[base_mask, "eve"].sum()
            eve_s = eve_shocked.loc[shocked_mask, "eve"].sum()
            delta = eve_s - eve_b
            pct = (delta / eve_b * 100) if abs(eve_b) > 1e-6 else 0.0

            results.append({
                "scenario": sc_name,
                "currency": ccy,
                "eve_base": round(float(eve_b), 0),
                "eve_shocked": round(float(eve_s), 0),
                "delta_eve": round(float(delta), 0),
                "pct_change": round(float(pct), 2),
            })

    return pd.DataFrame(results)


def compute_key_rate_durations(
    nominal_daily: np.ndarray,
    ois_matrix: np.ndarray,
    rate_matrix: np.ndarray,
    mm_vector: np.ndarray,
    days: pd.DatetimeIndex,
    deals: pd.DataFrame,
    date_run: datetime,
    base_curves: pd.DataFrame,
    bump_bps: float = 1.0,
) -> pd.DataFrame:
    """Compute key rate durations at BCBS standard tenor points.

    KRD at tenor T = -(EVE_bumped - EVE_base) / (bump_bps/10000) / EVE_base

    Args:
        bump_bps: Size of the bump in basis points (default 1bp).

    Returns:
        DataFrame: currency, tenor, tenor_years, krd.
    """
    from pnl_engine.scenarios import TENOR_YEARS, apply_scenario_to_curves
    from pnl_engine.engine import _build_ois_matrix

    eve_base = compute_eve(
        nominal_daily, ois_matrix, rate_matrix, mm_vector,
        days, deals, date_run,
    )

    date_run_ts = pd.Timestamp(date_run)
    day_years = np.array([(d - date_run_ts).days / 365.25 for d in days])

    currencies = deals["Currency"].unique() if "Currency" in deals.columns else []
    results = []

    for tenor_label, tenor_yr in sorted(TENOR_YEARS.items(), key=lambda x: x[1]):
        # Create a triangular bump centered at this tenor
        # Width: half distance to neighboring tenors (simplified: ±0.5Y or half gap)
        bump_array = np.zeros(len(days))
        sigma = max(0.25, tenor_yr * 0.2) if tenor_yr > 0 else 0.25
        weights = np.exp(-0.5 * ((day_years - tenor_yr) / sigma) ** 2)
        bump_array = weights * (bump_bps / 10000.0)

        for ccy in currencies:
            ois_indice = CURRENCY_TO_OIS.get(ccy)
            if not ois_indice:
                continue

            bumped_curves = apply_scenario_to_curves(
                base_curves.copy(), bump_array, ois_indice,
            )
            ois_bumped = _build_ois_matrix(deals, bumped_curves, days)
            eve_bumped = compute_eve(
                nominal_daily, ois_bumped, rate_matrix, mm_vector,
                days, deals, date_run,
            )

            ccy_mask = eve_base["Currency"] == ccy if "Currency" in eve_base.columns else pd.Series([True] * len(eve_base))
            eve_b = eve_base.loc[ccy_mask, "eve"].sum()
            eve_s = eve_bumped.loc[ccy_mask, "eve"].sum()

            krd = -(eve_s - eve_b) / (bump_bps / 10000.0) / eve_b if abs(eve_b) > 1e-6 else 0.0

            results.append({
                "currency": ccy,
                "tenor": tenor_label,
                "tenor_years": tenor_yr,
                "krd": round(float(krd), 4),
            })

    return pd.DataFrame(results)
