"""BCBS 368 scenario engine — tenor-dependent rate shock interpolation.

Provides tools to apply non-parallel (tenor-dependent) rate shocks
from BCBS 368 IRRBB scenarios to daily OIS forward curves.

The 6 standard BCBS scenarios are:
  - parallel_up / parallel_down: ±200bp across all tenors
  - short_up / short_down: ±300bp at O/N, tapering to 0 at 20Y
  - steepener: -100bp short, +100bp long
  - flattener: +100bp short, -100bp long
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Tenor label → year fraction mapping (BCBS standard tenor points)
TENOR_YEARS = {
    "O/N": 0.0, "3M": 0.25, "6M": 0.5, "1Y": 1.0, "2Y": 2.0,
    "3Y": 3.0, "5Y": 5.0, "10Y": 10.0, "20Y": 20.0, "30Y": 30.0,
}

BCBS_SCENARIOS = [
    "parallel_up", "parallel_down",
    "short_up", "short_down",
    "steepener", "flattener",
]


def interpolate_scenario_shifts(
    scenario_df: pd.DataFrame,
    scenario_name: str,
    currency: str,
    days: pd.DatetimeIndex,
    date_run: datetime,
) -> np.ndarray:
    """Interpolate BCBS tenor-point shifts to a daily date grid.

    Args:
        scenario_df: DataFrame with columns: scenario, tenor, CHF, EUR, USD, GBP
                     (shift values in basis points).
        scenario_name: Which scenario to apply (e.g. "parallel_up").
        currency: Currency column to read shifts from (e.g. "CHF").
        days: Daily date grid.
        date_run: Reference date (day 0 of the tenor axis).

    Returns:
        (n_days,) array of shifts in decimal (e.g. 200bp → 0.02).
    """
    sc_rows = scenario_df[scenario_df["scenario"] == scenario_name]
    if sc_rows.empty:
        return np.zeros(len(days))

    # Extract tenor → shift mapping
    tenor_years = []
    shifts_bps = []
    for _, row in sc_rows.iterrows():
        tenor = str(row["tenor"])
        if tenor in TENOR_YEARS:
            tenor_years.append(TENOR_YEARS[tenor])
            shift = row.get(currency, row.get(currency.upper(), 0.0))
            shifts_bps.append(float(shift) if pd.notna(shift) else 0.0)

    if not tenor_years:
        return np.zeros(len(days))

    # Sort by tenor year
    order = np.argsort(tenor_years)
    tenor_years = np.array(tenor_years)[order]
    shifts_bps = np.array(shifts_bps)[order]

    # Convert days to year fractions from date_run
    date_run_ts = pd.Timestamp(date_run)
    day_years = np.array([(d - date_run_ts).days / 365.0 for d in days])

    # Interpolate shifts to daily grid (extrapolate flat at boundaries)
    daily_shifts_bps = np.interp(day_years, tenor_years, shifts_bps)

    # Convert from basis points to decimal
    return daily_shifts_bps / 10000.0


def apply_scenario_to_curves(
    base_curves: pd.DataFrame,
    shift_array: np.ndarray,
    currency_ois_indice: str,
) -> pd.DataFrame:
    """Apply daily tenor-dependent shifts to base OIS curves.

    Args:
        base_curves: DataFrame with columns [Date, Indice, value].
        shift_array: (n_days,) shift array in decimal from interpolate_scenario_shifts.
        currency_ois_indice: OIS indice to shift (e.g. "CHFSON").

    Returns:
        Copy of base_curves with shifted values for the target indice.
    """
    result = base_curves.copy()
    mask = result["Indice"] == currency_ois_indice

    if mask.sum() == 0:
        return result

    # Match shifts to curve dates
    curve_dates = result.loc[mask, "Date"].values
    if len(shift_array) >= len(curve_dates):
        shifts = shift_array[:len(curve_dates)]
    else:
        # Pad with last shift value
        shifts = np.pad(shift_array, (0, len(curve_dates) - len(shift_array)),
                       mode='edge')

    result.loc[mask, "value"] = result.loc[mask, "value"].values + shifts
    return result
