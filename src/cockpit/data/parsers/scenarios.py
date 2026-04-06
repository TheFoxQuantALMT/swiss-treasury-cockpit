"""Parser for scenarios.xlsx — BCBS 368 rate shock scenario definitions."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


BCBS_SCENARIOS = [
    "parallel_up", "parallel_down",
    "short_up", "short_down",
    "steepener", "flattener",
]

SUPPORTED_CURRENCIES = {"CHF", "EUR", "USD", "GBP"}


def parse_scenarios(path: Path | str) -> pd.DataFrame:
    """Parse scenarios Excel file.

    Expected sheet: "Scenarios" with columns:
        scenario, tenor, CHF, EUR, USD, GBP
        (shift values in basis points)

    Returns:
        DataFrame with columns: scenario, tenor, CHF, EUR, USD, GBP (in bps).
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="Scenarios", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    # Normalize column names
    df.columns = [str(c).strip() for c in df.columns]
    # Lowercase the non-currency columns
    rename = {}
    for c in df.columns:
        if c.upper() in SUPPORTED_CURRENCIES:
            rename[c] = c.upper()
        else:
            rename[c] = c.lower()
    df = df.rename(columns=rename)

    if "scenario" not in df.columns or "tenor" not in df.columns:
        raise ValueError(f"scenarios.xlsx must have 'scenario' and 'tenor' columns, got: {list(df.columns)}")

    # Ensure currency columns exist
    for ccy in SUPPORTED_CURRENCIES:
        if ccy not in df.columns:
            df[ccy] = 0.0

    return df.reset_index(drop=True)


def get_default_scenarios() -> pd.DataFrame:
    """Return default BCBS 368 scenario definitions.

    Returns DataFrame with standard shifts in basis points.
    """
    tenors = ["O/N", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"]
    tenor_years = [0, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30]

    rows = []
    for sc in BCBS_SCENARIOS:
        for tenor, yr in zip(tenors, tenor_years):
            if sc == "parallel_up":
                shift = 200
            elif sc == "parallel_down":
                shift = max(-200, -100)  # floor at -100bp per BCBS
            elif sc == "short_up":
                shift = max(0, 300 * (1 - yr / 20)) if yr <= 20 else 0
            elif sc == "short_down":
                shift = min(0, -300 * (1 - yr / 20)) if yr <= 20 else 0
            elif sc == "steepener":
                shift = -100 + 200 * min(yr / 20, 1)
            elif sc == "flattener":
                shift = 100 - 200 * min(yr / 20, 1)
            else:
                shift = 0

            rows.append({
                "scenario": sc, "tenor": tenor,
                "CHF": shift, "EUR": shift, "USD": shift, "GBP": shift,
            })

    return pd.DataFrame(rows)
