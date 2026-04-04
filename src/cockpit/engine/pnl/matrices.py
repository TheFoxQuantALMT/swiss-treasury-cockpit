"""Build aligned (n_deals × n_days) matrices for vectorized P&L computation."""
from __future__ import annotations

import numpy as np
import pandas as pd

from cockpit.config import MM_BY_CURRENCY


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
    """Boolean mask (n_deals × n_days): True where deal is alive.

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
    return np.array([MM_BY_CURRENCY.get(c, 360) for c in deals["Currency"]], dtype=np.float64)


def build_rate_matrix(deals: pd.DataFrame, days: pd.DatetimeIndex, ref_curves: pd.DataFrame | None = None) -> np.ndarray:
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
            if not indice:
                continue
            try:
                idx_data = ref_by_date.loc[indice]
                curve_dates = idx_data.index.values.astype("datetime64[D]")
                curve_vals = idx_data.values
                sorter = np.searchsorted(curve_dates, day_dates, side="right") - 1
                sorter = np.clip(sorter, 0, len(curve_vals) - 1)
                result[i] = curve_vals[sorter] + spread
            except KeyError:
                pass
    return result
