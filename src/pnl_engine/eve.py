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

    # Discount factors: exp(-∫OIS dt) using cumulative forward rates
    # Build cumulative zero rates from instantaneous forwards:
    #   Z(t) = (1/t) × ∫₀ᵗ f(s) ds  ≈  cumsum(f × Δt) / t
    # DF(t) = exp(-Z(t) × t) = exp(-cumsum(f × Δt))
    dt = np.diff(day_years, prepend=0.0)  # time step per day
    cum_integral = np.cumsum(ois_matrix * dt[np.newaxis, :], axis=1)
    discount_factors = np.exp(-cum_integral)

    # Daily cash flow: Nominal × Rate / MM (the interest income stream)
    mm_broadcast = mm_vector[:, np.newaxis] * np.ones((1, n_days))
    daily_cf = nominal_daily * rate_matrix / mm_broadcast

    # Also include the notional principal return at maturity.
    # Only capture the terminal drop (nominal goes from positive to zero),
    # NOT intermediate amortization steps — those are already reflected in
    # declining interest cash flows via the nominal schedule.
    nominal_shift = np.zeros_like(nominal_daily)
    for j in range(1, n_days):
        # Only capture drops to zero (maturity) or from positive to zero
        mask = (nominal_daily[:, j] == 0) & (nominal_daily[:, j - 1] != 0)
        nominal_shift[:, j] = np.where(mask, -nominal_daily[:, j - 1], 0.0)
    total_cf = daily_cf - nominal_shift  # daily_cf already includes interest on remaining balance

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
    nominal_adjuster: Optional[object] = None,
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
        nominal_adjuster: Optional callable(deals, nominal_daily, days, ois_matrix)
            -> np.ndarray. Called per scenario with the shocked OIS matrix to
            adjust nominals (e.g., rate-dependent CPR). If None, nominals are
            unchanged across scenarios.

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

        # Adjust nominals for this scenario (e.g., rate-dependent CPR)
        scenario_nominal = nominal_daily
        if nominal_adjuster is not None:
            try:
                adjusted, _ = nominal_adjuster(deals, nominal_daily, days, ois_matrix_shocked)
                scenario_nominal = adjusted
            except Exception:
                logger.warning("nominal_adjuster failed for scenario %s, using base nominals", sc_name)

        # Compute shocked EVE
        eve_shocked = compute_eve(
            scenario_nominal, ois_matrix_shocked, rate_matrix, mm_vector,
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


def compute_eve_convexity(
    eve_base_by_ccy: dict[str, float],
    eve_up_by_ccy: dict[str, float],
    eve_down_by_ccy: dict[str, float],
    delta_r: float = 0.02,
) -> dict:
    """Compute effective duration and convexity from parallel ±shock EVE.

    Uses second-order finite difference from BCBS 368 parallel_up/down
    scenarios (default ±200bp).

    Formulas:
      effective_duration = -(EVE_up - EVE_down) / (2 × EVE_base × Δr)
      convexity = (EVE_up + EVE_down - 2×EVE_base) / (EVE_base × Δr²)

    Args:
        eve_base_by_ccy: Base EVE by currency {"CHF": 1000000, ...}.
        eve_up_by_ccy: EVE under parallel_up scenario.
        eve_down_by_ccy: EVE under parallel_down scenario.
        delta_r: Shock size in decimal (0.02 = 200bp).

    Returns:
        Dict with "total" and "by_currency" convexity metrics.
    """
    by_currency = {}
    total_base = 0.0
    total_up = 0.0
    total_down = 0.0

    all_ccys = sorted(set(eve_base_by_ccy) | set(eve_up_by_ccy) | set(eve_down_by_ccy))

    for ccy in all_ccys:
        base = eve_base_by_ccy.get(ccy, 0.0)
        up = eve_up_by_ccy.get(ccy, 0.0)
        down = eve_down_by_ccy.get(ccy, 0.0)

        total_base += base
        total_up += up
        total_down += down

        if abs(base) > 1e-6:
            eff_dur = -(up - down) / (2.0 * base * delta_r)
            conv = (up + down - 2.0 * base) / (base * delta_r ** 2)
        else:
            eff_dur = 0.0
            conv = 0.0

        by_currency[ccy] = {
            "eve_base": round(base, 0),
            "eve_up": round(up, 0),
            "eve_down": round(down, 0),
            "effective_duration": round(eff_dur, 4),
            "convexity": round(conv, 4),
            "delta_eve_up": round(up - base, 0),
            "delta_eve_down": round(down - base, 0),
        }

    # Portfolio total
    if abs(total_base) > 1e-6:
        total_dur = -(total_up - total_down) / (2.0 * total_base * delta_r)
        total_conv = (total_up + total_down - 2.0 * total_base) / (total_base * delta_r ** 2)
    else:
        total_dur = 0.0
        total_conv = 0.0

    return {
        "total": {
            "eve_base": round(total_base, 0),
            "eve_up": round(total_up, 0),
            "eve_down": round(total_down, 0),
            "effective_duration": round(total_dur, 4),
            "convexity": round(total_conv, 4),
            "delta_eve_up": round(total_up - total_base, 0),
            "delta_eve_down": round(total_down - total_base, 0),
        },
        "by_currency": by_currency,
    }


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

    # Sort tenor points for boundary computation
    sorted_tenors = sorted(TENOR_YEARS.items(), key=lambda x: x[1])
    tenor_yr_list = [t[1] for t in sorted_tenors]

    for idx, (tenor_label, tenor_yr) in enumerate(sorted_tenors):
        # Piecewise-constant step bump: each day maps to exactly one tenor
        # bucket based on midpoint boundaries between adjacent BCBS tenors.
        if idx == 0:
            lo = -np.inf
        else:
            lo = (tenor_yr_list[idx - 1] + tenor_yr) / 2.0
        if idx == len(sorted_tenors) - 1:
            hi = np.inf
        else:
            hi = (tenor_yr + tenor_yr_list[idx + 1]) / 2.0

        weights = ((day_years >= lo) & (day_years < hi)).astype(float)
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
