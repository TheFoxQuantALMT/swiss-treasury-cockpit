"""Build aligned (n_deals x n_days) matrices for vectorized P&L computation.

Regulatory references:
    - ISDA 2006 §4.16: day count conventions per instrument type
    - ISDA 2021 §6.9: d_i = calendar days between fixings for compounding
    - SNB Working Group: SARON 2-BD lookback
    - BoE Working Group: SONIA 5-BD lookback
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from pnl_engine.config import MM_BY_CURRENCY, LOOKBACK_DAYS
from pnl_engine.models import get_day_count
from pnl_engine.saron import apply_lookback_shift

logger = logging.getLogger(__name__)


def days_to_years(days: pd.DatetimeIndex, ref_date, divisor: float = 365.0) -> np.ndarray:
    """Convert DatetimeIndex to year fractions from ref_date.

    Args:
        days: DatetimeIndex of dates.
        ref_date: Reference date (t=0).
        divisor: Day-count divisor (365 for ACT/365, 360 for ACT/360).
            Default 365 for NII purposes.  For EVE discounting, pass the
            currency-appropriate OIS convention (360 for CHF/EUR, 365 for
            GBP/USD).
    """
    ref_ts = pd.Timestamp(ref_date)
    return (pd.DatetimeIndex(days) - ref_ts).days.values.astype(float) / divisor


def broadcast_mm(mm_vector: np.ndarray) -> np.ndarray:
    """Broadcast 1-D mm_vector to 2-D for element-wise division with (n_deals, n_days) arrays."""
    return mm_vector[:, np.newaxis] if mm_vector.ndim == 1 else mm_vector


def build_date_grid(start: pd.Timestamp, months: int = 60) -> pd.DatetimeIndex:
    end = start + pd.DateOffset(months=months)
    return pd.date_range(start, end - pd.Timedelta(days=1), freq="D")


def expand_nominal_to_daily(nominals_wide: pd.DataFrame, days: pd.DatetimeIndex) -> np.ndarray:
    n_deals = len(nominals_wide)
    n_days = len(days)
    result = np.zeros((n_deals, n_days), dtype=np.float64)
    day_months = days.to_period("M").astype(str)  # produces "YYYY-MM"
    month_cols = [c for c in nominals_wide.columns if isinstance(c, str) and "/" in c and c[:4].isdigit()]
    for col in month_cols:
        # Column names use "YYYY/MM"; period strings use "YYYY-MM" — normalise for comparison
        col_normalized = col.replace("/", "-")
        mask = day_months == col_normalized
        if not mask.any():
            continue
        col_idx = np.where(mask)[0]
        vals = nominals_wide[col].fillna(0.0).values
        result[:, col_idx] = vals[:, np.newaxis]
    return result


def build_alive_mask(
    deals: pd.DataFrame,
    days: pd.DatetimeIndex,
    date_run: pd.Timestamp | None = None,
) -> np.ndarray:
    """Boolean mask (n_deals x n_days): True where deal is alive.

    Active range per deal: max(Valuedate, first_of_month(dateRun)) to Maturitydate.
    """
    val_dates = pd.to_datetime(deals["Valuedate"], dayfirst=True, errors="coerce").values.astype("datetime64[D]")
    mat_dates = pd.to_datetime(deals["Maturitydate"], dayfirst=True, errors="coerce").values.astype("datetime64[D]")

    # Cap start at first of dateRun's month (§7.1)
    if date_run is not None:
        run_month_start = np.datetime64(date_run.replace(day=1), "D")
        val_dates = np.maximum(val_dates, run_month_start)

    day_arr = days.values.astype("datetime64[D]")
    alive = (day_arr[np.newaxis, :] >= val_dates[:, np.newaxis]) & (day_arr[np.newaxis, :] <= mat_dates[:, np.newaxis])
    return alive


def build_mm_vector(deals: pd.DataFrame) -> np.ndarray:
    """Day count divisor per deal (ISDA 2006 §4.16).

    Product-aware: bonds use 30/360 (except GBP: Act/365),
    money market instruments use Act/360 (GBP: Act/365).
    """
    if "Product" in deals.columns:
        return np.array(
            [get_day_count(p, c).divisor for p, c in zip(deals["Product"], deals["Currency"])],
            dtype=np.float64,
        )
    return np.array([MM_BY_CURRENCY.get(c, 360) for c in deals["Currency"]], dtype=np.float64)


def build_accrual_days(days: pd.DatetimeIndex) -> np.ndarray:
    """Calendar days each fixing accrues for (ISDA 2021 §6.9).

    Uses the Swiss business day calendar from ``cockpit.calendar`` to
    compute the gap to the next business day for the last day in the
    grid (handles weekends and Swiss public holidays correctly).

    Returns:
        (n_days,) array of integers >= 1.
    """
    from cockpit.calendar import next_business_day

    n = len(days)
    if n == 0:
        return np.array([], dtype=np.float64)
    day_arr = days.values.astype("datetime64[D]")
    d_i = np.ones(n, dtype=np.float64)
    if n > 1:
        d_i[:-1] = np.diff(day_arr).astype("timedelta64[D]").astype(np.float64)
    # Last day: gap to next business day via Swiss calendar
    last_date = days[-1].date()
    from datetime import timedelta
    next_bd = next_business_day(last_date + timedelta(days=1))
    d_i[-1] = float((next_bd - last_date).days)
    return d_i


def build_rate_matrix(
    deals: pd.DataFrame,
    days: pd.DatetimeIndex,
    ref_curves: pd.DataFrame | None = None,
    date_run: "pd.Timestamp | None" = None,
) -> np.ndarray:
    """Build (n_deals x n_days) reference rate matrix.

    Fixed-rate deals: broadcast RateRef across all days.
    Floating-rate deals branch on ``fixing_tenor_days``:
      - tenor == 0 (overnight RFR): interpolate forward curve daily and apply
        lookback shift (SARON 2-BD, SONIA 5-BD per SNB/BoE conventions).
      - tenor  > 0 (term floater, e.g. SARON3M): hold the rate constant over
        each fixing period [t_k, t_k+tenor). For the period containing
        ``date_run`` (the business run date, NOT wall-clock today — backfills
        need determinism) use ``current_fixing_rate`` (the contractual fix
        recorded in MTD); for other periods, sample the forward curve at t_k.
    """
    n_deals = len(deals)
    n_days = len(days)
    result = np.zeros((n_deals, n_days), dtype=np.float64)
    is_floating = deals["is_floating"].values if "is_floating" in deals.columns else np.zeros(n_deals, dtype=bool)
    fixed_mask = ~is_floating
    if fixed_mask.any():
        rates = deals.loc[fixed_mask, "RateRef"].values
        result[fixed_mask] = rates[:, np.newaxis]
    if not is_floating.any() or ref_curves is None:
        return result

    day_dates = days.values.astype("datetime64[D]")
    day_dates_num = day_dates.astype(np.int64)

    # Pre-group ref_curves by Indice once instead of per-deal .loc
    curve_by_indice: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    grouped = ref_curves.sort_values("Date").groupby("Indice", sort=False)
    for indice, sub in grouped:
        curve_dates = sub["Date"].values.astype("datetime64[D]")
        curve_vals = sub["value"].values.astype(np.float64)
        curve_by_indice[indice] = (curve_dates.astype(np.int64), curve_vals)
        if len(curve_dates) > 0 and len(day_dates) > 0 and day_dates[-1] > curve_dates[-1]:
            extrap_days = int((day_dates[-1] - curve_dates[-1]) / np.timedelta64(1, "D"))
            logger.warning(
                "Rate curve for %s ends before date grid; flat-extrapolating %d days",
                indice, extrap_days,
            )

    # Pre-extract per-deal columns into numpy arrays (avoid 7 .iloc calls per row)
    ref_index_arr = deals["ref_index"].values if "ref_index" in deals.columns else np.array([""] * n_deals)
    spread_arr = pd.to_numeric(deals["Spread"], errors="coerce").fillna(0.0).values if "Spread" in deals.columns else np.zeros(n_deals)
    currency_arr = deals["Currency"].values if "Currency" in deals.columns else np.array([""] * n_deals)
    rate_ref_arr = pd.to_numeric(deals["RateRef"], errors="coerce").fillna(0.0).values if "RateRef" in deals.columns else np.zeros(n_deals)
    last_fix_arr = pd.to_datetime(deals["last_fixing_date"], errors="coerce") if "last_fixing_date" in deals.columns else pd.Series([pd.NaT] * n_deals)
    next_fix_arr = pd.to_datetime(deals["next_fixing_date"], errors="coerce") if "next_fixing_date" in deals.columns else pd.Series([pd.NaT] * n_deals)
    current_fix_arr = pd.to_numeric(deals["current_fixing_rate"], errors="coerce") if "current_fixing_rate" in deals.columns else pd.Series([np.nan] * n_deals)
    tenor_col = deals["fixing_tenor_days"].values if "fixing_tenor_days" in deals.columns else np.zeros(n_deals, dtype=int)

    _ref_ts = pd.Timestamp(date_run) if date_run is not None else pd.Timestamp.today()
    ref_day = np.datetime64(_ref_ts.normalize().to_datetime64(), "D")
    grid_start = day_dates[0]
    grid_end = day_dates[-1]
    one_day = np.timedelta64(1, "D")

    for i in np.where(is_floating)[0]:
        indice = ref_index_arr[i]
        if not indice:
            continue
        curve = curve_by_indice.get(indice)
        if curve is None:
            continue
        curve_dates_num, curve_vals = curve

        spread = float(spread_arr[i])
        tenor_days = int(tenor_col[i]) if i < len(tenor_col) else 0

        if tenor_days <= 0:
            # Overnight RFR: rate floats every day, with optional lookback shift.
            daily_rates = np.interp(day_dates_num, curve_dates_num, curve_vals)
            lookback = LOOKBACK_DAYS.get(currency_arr[i], 0)
            if lookback > 0:
                daily_rates = apply_lookback_shift(daily_rates, lookback_days=lookback)
            result[i] = daily_rates + spread
            continue

        # Term floater: walk the fixing schedule and hold the rate constant
        # over each [t_k, t_k+tenor) segment.
        last_fix = last_fix_arr.iloc[i]
        next_fix = next_fix_arr.iloc[i]
        current_fix = current_fix_arr.iloc[i]

        if pd.notna(last_fix):
            anchor = pd.Timestamp(last_fix).to_datetime64().astype("datetime64[D]")
        elif pd.notna(next_fix):
            anchor = (pd.Timestamp(next_fix) - pd.Timedelta(days=tenor_days)).to_datetime64().astype("datetime64[D]")
        else:
            logger.warning(
                "Term floater (deal idx %d, %s) missing fixing dates; degrading to overnight RFR",
                i, indice,
            )
            daily_rates = np.interp(day_dates_num, curve_dates_num, curve_vals)
            result[i] = daily_rates + spread
            continue

        # Roll anchor forward in tenor steps until the segment overlaps the grid.
        # Arithmetic skip avoids a while-loop for deals last fixed long ago.
        step = np.timedelta64(tenor_days, "D")
        if anchor + step <= grid_start:
            gap_days = int((grid_start - anchor) / one_day)
            n_skip = gap_days // tenor_days
            anchor = anchor + np.timedelta64(n_skip * tenor_days, "D")
            while anchor + step <= grid_start:
                anchor = anchor + step

        rates_path = np.zeros(n_days, dtype=np.float64)
        seg_start = anchor
        while seg_start <= grid_end:
            seg_end = seg_start + step  # exclusive
            if seg_start <= ref_day < seg_end:
                if pd.notna(current_fix):
                    seg_rate = float(current_fix)
                else:
                    logger.warning(
                        "Term floater (deal idx %d, %s) missing current_fixing_rate "
                        "for active period; falling back to RateRef (may be wrong for IRS)",
                        i, indice,
                    )
                    seg_rate = float(rate_ref_arr[i])
            else:
                fix_num = int(seg_start.astype(np.int64))
                seg_rate = float(np.interp(fix_num, curve_dates_num, curve_vals))

            mask = (day_dates >= seg_start) & (day_dates < seg_end)
            rates_path[mask] = seg_rate
            seg_start = seg_end

        result[i] = rates_path + spread

    return result


def build_client_rate_matrix(deals: pd.DataFrame, n_days: int) -> np.ndarray:
    """Build (n_deals x n_days) client rate matrix for EVE cashflow generation.

    Uses the contractual Clientrate for all deals, broadcast across all days.
    This is the rate the bank actually earns/pays, distinct from the reference
    rate used for NII computation (EqOisRate, YTM, etc.).
    """
    n_deals = len(deals)
    result = np.zeros((n_deals, n_days), dtype=np.float64)
    if "Clientrate" in deals.columns:
        rates = pd.to_numeric(deals["Clientrate"], errors="coerce").fillna(0.0).values
        result = rates[:, np.newaxis] * np.ones((1, n_days))
    return result


def build_funding_matrix(
    deals: pd.DataFrame,
    days: pd.DatetimeIndex,
    ois_matrix: np.ndarray,
    funding_source: str = "carry",
) -> np.ndarray:
    """Build (n_deals x n_days) funding rate matrix.

    Args:
        funding_source:
            "carry" (default) uses WASP carry-compounded rates per currency/month.
            "ois" uses the OIS forward curve (ISDA CSA standard).
            "coc" uses the deal-level CocRate.
    """
    if funding_source == "coc" and "CocRate" in deals.columns:
        n_deals = len(deals)
        coc_rates = deals["CocRate"].fillna(0.0).values
        return np.broadcast_to(coc_rates[:, np.newaxis], ois_matrix.shape).copy()

    if funding_source == "carry":
        return _build_carry_funding_matrix(deals, days, ois_matrix)

    # "ois": OIS curve = standard post-LIBOR funding rate
    return ois_matrix


def _build_carry_funding_matrix(
    deals: pd.DataFrame,
    days: pd.DatetimeIndex,
    ois_matrix: np.ndarray,
) -> np.ndarray:
    """Build funding matrix from WASP carry-compounded rates per (currency, month).

    For each currency, loads one carry-compounded rate per month via WASP,
    then fills all days in that month with that rate. Falls back to OIS
    matrix for currencies where carry loading fails.
    """
    import logging
    from pnl_engine.config import CURRENCY_TO_CARRY_INDEX, SUPPORTED_CURRENCIES
    from pnl_engine.curves import load_carry_compounded

    logger = logging.getLogger(__name__)
    n_deals = len(deals)
    n_days = len(days)
    result = ois_matrix.copy()  # fallback: OIS

    # Build month boundaries
    months = days.to_period("M").unique()

    for ccy in SUPPORTED_CURRENCIES:
        if ccy not in CURRENCY_TO_CARRY_INDEX:
            continue
        deal_mask = (deals["Currency"] == ccy).values
        if not deal_mask.any():
            continue

        for month in months:
            month_start = month.start_time
            month_end = month.end_time
            day_mask = np.asarray(days.to_period("M") == month)
            if not day_mask.any():
                continue

            try:
                carry_rate = load_carry_compounded(month_start, month_end, ccy)
                result[np.ix_(deal_mask, day_mask)] = carry_rate
            except Exception as exc:
                logger.warning(
                    "Carry compounded failed %s %s, keeping OIS: %s", ccy, month, exc
                )

    return result


# ---------------------------------------------------------------------------
# Cumulative factor arrays for value-date compounding
# ---------------------------------------------------------------------------

def build_cumulative_carry_factors(
    deals: pd.DataFrame,
    days: pd.DatetimeIndex,
    date_rates: "pd.Timestamp | None" = None,
) -> tuple[np.ndarray, list]:
    """Build cumulative carry factors from each deal's value date to each boundary.

    Calls WASP carryCompounded(value_date, boundary, currency) per unique
    (currency, value_date) group.  Results are cached to avoid duplicate calls.

    Args:
        deals: DataFrame with 'Currency' and 'Valuedate' columns.
        days: Full daily date grid.
        date_rates: If provided, inserted as an extra boundary for Realized/Forecast split.

    Returns:
        cum_carry: (n_deals, n_boundaries+1) array.  cum_carry[i, 0] = 1.0 (at or before VD).
                   cum_carry[i, j+1] = 1 + carryCompounded(VD_i, boundary_j, ccy_i).
        boundaries: list of boundary dates (pd.Timestamp), length = n_boundaries.
    """
    from pnl_engine.config import SUPPORTED_CURRENCIES, CURRENCY_TO_CARRY_INDEX
    from pnl_engine.curves import load_carry_compounded_cached

    n_deals = len(deals)
    months = days.to_period("M").unique().sort_values()

    # Build boundary dates: end of each month
    boundary_dates = [m.end_time for m in months]

    # Insert date_rates as extra boundary if it falls within the grid
    if date_rates is not None:
        dr_ts = pd.Timestamp(date_rates)
        for k, bd in enumerate(boundary_dates):
            if dr_ts <= bd:
                if dr_ts.date() != bd.date():
                    boundary_dates.insert(k, dr_ts)
                break

    n_boundaries = len(boundary_dates)

    # Column 0 = virtual "start" boundary (factor = 1.0 for all deals)
    cum = np.ones((n_deals, n_boundaries + 1), dtype=np.float64)

    # Parse value dates
    value_dates = pd.to_datetime(deals["Valuedate"], dayfirst=True, errors="coerce")
    currencies = deals["Currency"].values

    # Group by (currency, value_date) to minimize WASP calls
    groups: dict[tuple[str, str], list[int]] = {}
    for i in range(n_deals):
        ccy = currencies[i]
        vd = value_dates.iloc[i]
        if pd.isna(vd) or ccy not in CURRENCY_TO_CARRY_INDEX:
            continue
        key = (ccy, str(vd.date()))
        groups.setdefault(key, []).append(i)

    for (ccy, vd_str), deal_indices in groups.items():
        vd = pd.Timestamp(vd_str)
        for j, bd in enumerate(boundary_dates):
            if bd < vd:
                continue
            try:
                cc = load_carry_compounded_cached(vd, bd, ccy)
                for i in deal_indices:
                    cum[i, j + 1] = 1.0 + cc
            except Exception as exc:
                logger.warning(
                    "Cumulative carry failed %s VD=%s BD=%s: %s", ccy, vd_str, bd.date(), exc,
                )

    return cum, boundary_dates


def build_cumulative_rate_factors(
    rate_daily: np.ndarray,
    accrual_days: np.ndarray,
    mm_daily: np.ndarray,
    alive_mask: np.ndarray,
    days: pd.DatetimeIndex,
    date_rates: "pd.Timestamp | None" = None,
) -> np.ndarray:
    """Build cumulative rate factors from each deal's value date to each boundary.

    Compounds (1 + rate * d_i / MM) daily, starting from each deal's first alive day.
    Sampled at the same boundaries as build_cumulative_carry_factors.

    Returns:
        cum_rate: (n_deals, n_boundaries+1) array matching the carry boundaries layout.
                  Column 0 = 1.0 (start), columns 1..N = cumulative product at each boundary.
    """
    n_deals, n_days = rate_daily.shape
    months = days.to_period("M").unique().sort_values()

    # Build boundary dates (same logic as carry)
    boundary_dates = [m.end_time for m in months]
    if date_rates is not None:
        dr_ts = pd.Timestamp(date_rates)
        for k, bd in enumerate(boundary_dates):
            if dr_ts <= bd:
                if dr_ts.date() != bd.date():
                    boundary_dates.insert(k, dr_ts)
                break

    n_boundaries = len(boundary_dates)

    # Daily factors: where alive, (1 + rate * d / MM); where not alive, 1.0
    accrual_row = accrual_days[np.newaxis, :]
    factors_alive = 1.0 + rate_daily * accrual_row / mm_daily
    daily_factors = np.where(alive_mask, factors_alive, 1.0)

    # Cumulative product along day axis
    cum_prod = np.cumprod(daily_factors, axis=1)

    # Sample at boundary dates
    cum = np.ones((n_deals, n_boundaries + 1), dtype=np.float64)
    day_dates = days.normalize()
    for j, bd in enumerate(boundary_dates):
        bd_date = pd.Timestamp(bd).normalize()
        mask = day_dates <= bd_date
        if mask.any():
            day_idx = int(np.where(mask)[0][-1])
            cum[:, j + 1] = cum_prod[:, day_idx]

    return cum
