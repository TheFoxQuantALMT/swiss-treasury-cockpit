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
    d_i = np.ones(n, dtype=np.float64)
    # For each day, d_i = calendar days until the next fixing
    day_arr = days.values.astype("datetime64[D]")
    for j in range(n - 1):
        d_i[j] = float((day_arr[j + 1] - day_arr[j]) / np.timedelta64(1, "D"))
    # Last day: compute gap to next business day using Swiss calendar
    if n > 0:
        last_date = days[-1].date()
        from datetime import timedelta
        next_bd = next_business_day(last_date + timedelta(days=1))
        d_i[-1] = float((next_bd - last_date).days)
    return d_i


def build_rate_matrix(deals: pd.DataFrame, days: pd.DatetimeIndex, ref_curves: pd.DataFrame | None = None) -> np.ndarray:
    """Build (n_deals x n_days) reference rate matrix.

    Fixed-rate deals: broadcast RateRef across all days.
    Floating-rate deals: load forward curve by ref_index, apply lookback
    shift for SARON (2-BD) and SONIA (5-BD) per SNB/BoE conventions.
    """
    n_deals = len(deals)
    n_days = len(days)
    result = np.zeros((n_deals, n_days), dtype=np.float64)
    is_floating = deals["is_floating"].values if "is_floating" in deals.columns else np.zeros(n_deals, dtype=bool)
    fixed_mask = ~is_floating
    if fixed_mask.any():
        rates = deals.loc[fixed_mask, "RateRef"].values
        result[fixed_mask] = rates[:, np.newaxis]
    if is_floating.any() and ref_curves is not None:
        day_dates = days.values.astype("datetime64[D]")
        ref_by_date = ref_curves.set_index(["Indice", "Date"])["value"]
        for i in np.where(is_floating)[0]:
            indice = deals.iloc[i].get("ref_index", "")
            spread = deals.iloc[i].get("Spread", 0.0)
            ccy = deals.iloc[i].get("Currency", "")
            if not indice:
                continue
            try:
                idx_data = ref_by_date.loc[indice]
                curve_dates = idx_data.index.values.astype("datetime64[D]")
                curve_vals = idx_data.values

                # Map daily rates from curve via linear interpolation
                curve_dates_num = curve_dates.astype("datetime64[D]").astype(np.int64)
                day_dates_num = day_dates.astype(np.int64)
                daily_rates = np.interp(day_dates_num, curve_dates_num, curve_vals)

                # Apply SARON/SONIA lookback shift (ISDA 2021 observation shift)
                lookback = LOOKBACK_DAYS.get(ccy, 0)
                if lookback > 0:
                    daily_rates = apply_lookback_shift(daily_rates, lookback_days=lookback)

                # Warn if curve ends before the date grid (flat extrapolation)
                if len(curve_dates) > 0 and len(day_dates) > 0:
                    if day_dates[-1] > curve_dates[-1]:
                        extrap_days = int((day_dates[-1] - curve_dates[-1]) / np.timedelta64(1, "D"))
                        logger.warning(
                            "Rate curve for %s ends before date grid; flat-extrapolating %d days",
                            indice, extrap_days,
                        )

                result[i] = daily_rates + spread
            except KeyError:
                pass
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
    funding_source: str = "ois",
) -> np.ndarray:
    """Build (n_deals x n_days) funding rate matrix.

    Args:
        funding_source: "ois" uses the OIS forward curve (default, ISDA CSA standard),
                        "coc" uses the deal-level CocRate.
    """
    if funding_source == "coc" and "CocRate" in deals.columns:
        n_deals = len(deals)
        coc_rates = deals["CocRate"].fillna(0.0).values
        return np.broadcast_to(coc_rates[:, np.newaxis], ois_matrix.shape).copy()
    # Default: OIS curve = standard post-LIBOR funding rate
    return ois_matrix
