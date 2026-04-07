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

    Weekdays accrue 1 day; Fridays accrue 3 (Fri->Mon).
    Holiday adjustments require a ``BusinessDayCalendar`` — without one,
    this function uses the standard Sat/Sun weekend convention.

    Returns:
        (n_days,) array of integers >= 1.
    """
    n = len(days)
    if n == 0:
        return np.array([], dtype=np.float64)
    d_i = np.ones(n, dtype=np.float64)
    # For each day, d_i = calendar days until the next fixing
    day_arr = days.values.astype("datetime64[D]")
    for j in range(n - 1):
        d_i[j] = float((day_arr[j + 1] - day_arr[j]) / np.timedelta64(1, "D"))
    # Last day: assume 1 (or weekend weight if Friday)
    if n > 0 and days[-1].weekday() == 4:  # Friday
        d_i[-1] = 3.0
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

                # Map daily rates from curve
                sorter = np.searchsorted(curve_dates, day_dates, side="right") - 1
                sorter = np.clip(sorter, 0, len(curve_vals) - 1)
                daily_rates = curve_vals[sorter]

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
