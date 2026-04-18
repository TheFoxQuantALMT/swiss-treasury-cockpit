"""Test-only helper: build synthetic OIS curves from WIRP.

This module lives under ``tests/`` because the production engine always
requires WASP (the bank's market-data library). When tests run in an
environment where WASP is unavailable, they use this helper to produce
step-function OIS curves from the WIRP meeting schedule so the engine
has something plausible to consume.

Do NOT import from production code — the engine must fail loudly if
WASP is missing in prod.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def mock_curves_from_wirp(
    wirp: pd.DataFrame,
    days: pd.DatetimeIndex,
    shock: str = "0",
) -> pd.DataFrame:
    """Build mock daily OIS curves from WIRP meeting schedule.

    For each OIS indice found in WIRP, creates a daily series by forward-filling
    meeting rates across the date grid. Applies parallel shock shift (bps -> decimal).
    """
    rows = []
    for indice in wirp["Indice"].unique():
        sub = wirp[wirp["Indice"] == indice].sort_values("Meeting")
        meetings = sub["Meeting"].values.astype("datetime64[D]")
        rates = sub["Rate"].values.astype(float)

        day_arr = days.values.astype("datetime64[D]")
        idx = np.searchsorted(meetings, day_arr, side="right") - 1

        for j, d in enumerate(days):
            if idx[j] >= 0:
                val = rates[idx[j]]
            else:
                val = rates[0] if len(rates) > 0 else 0.0
            rows.append({"Date": d, "Indice": indice, "value": val})

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df["dateM"] = df["Date"].dt.to_period("M")

    shock_f = 0.0 if shock == "wirp" else float(shock)
    if shock_f != 0.0:
        df["value"] = df["value"] + shock_f / 10_000.0

    return df


# Legacy alias — existing tests import the underscored name.
_mock_curves_from_wirp = mock_curves_from_wirp
