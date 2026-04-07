"""Parser for scenarios.xlsx — BCBS 368 rate shock scenario definitions."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


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
            logger.warning("Scenario file missing column for %s, filling with 0bp", ccy)
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


# ---------------------------------------------------------------------------
# BCBS 368 Table 2: Currency-specific shock magnitudes (bp)
# ---------------------------------------------------------------------------

BCBS_CURRENCY_MAGNITUDES: dict[str, dict[str, int]] = {
    "CHF": {"parallel": 150, "short": 250, "rotation": 100},
    "EUR": {"parallel": 200, "short": 300, "rotation": 150},
    "USD": {"parallel": 200, "short": 300, "rotation": 150},
    "GBP": {"parallel": 250, "short": 350, "rotation": 150},
}


def get_currency_specific_scenarios() -> pd.DataFrame:
    """Return BCBS 368 scenarios with currency-specific shock magnitudes.

    Per BCBS 368 Table 2, shock magnitudes vary by currency:
    - CHF: 150bp parallel, 250bp short
    - EUR/USD: 200bp parallel, 300bp short
    - GBP: 250bp parallel, 350bp short
    """
    tenors = ["O/N", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"]
    tenor_years = [0, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30]
    currencies = ["CHF", "EUR", "USD", "GBP"]

    rows = []
    for sc in BCBS_SCENARIOS:
        for tenor, yr in zip(tenors, tenor_years):
            row = {"scenario": sc, "tenor": tenor}
            for ccy in currencies:
                mag = BCBS_CURRENCY_MAGNITUDES[ccy]
                if sc == "parallel_up":
                    shift = mag["parallel"]
                elif sc == "parallel_down":
                    shift = -mag["parallel"]
                elif sc == "short_up":
                    shift = max(0, mag["short"] * (1 - yr / 20)) if yr <= 20 else 0
                elif sc == "short_down":
                    shift = min(0, -mag["short"] * (1 - yr / 20)) if yr <= 20 else 0
                elif sc == "steepener":
                    half = mag["rotation"]
                    shift = -half + 2 * half * min(yr / 20, 1)
                elif sc == "flattener":
                    half = mag["rotation"]
                    shift = half - 2 * half * min(yr / 20, 1)
                else:
                    shift = 0
                row[ccy] = round(shift)
            rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# FINMA Circular 2019/02 scenarios
# ---------------------------------------------------------------------------

FINMA_SCENARIOS = [
    "finma_parallel_up",
    "finma_parallel_down",
    "finma_steepener",
    "finma_flattener",
]


def get_finma_scenarios() -> pd.DataFrame:
    """Return FINMA Circular 2019/02 stress scenarios.

    FINMA scenarios follow BCBS 368 structure but use Swiss-specific
    magnitudes and add CHF negative-rate scenarios.
    """
    tenors = ["O/N", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"]
    tenor_years = [0, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30]

    rows = []
    for sc in FINMA_SCENARIOS:
        for tenor, yr in zip(tenors, tenor_years):
            if sc == "finma_parallel_up":
                chf = 150
                eur = 200
            elif sc == "finma_parallel_down":
                chf = -150
                eur = -200
            elif sc == "finma_steepener":
                chf = round(-75 + 150 * min(yr / 20, 1))
                eur = round(-100 + 200 * min(yr / 20, 1))
            elif sc == "finma_flattener":
                chf = round(75 - 150 * min(yr / 20, 1))
                eur = round(100 - 200 * min(yr / 20, 1))
            else:
                chf, eur = 0, 0

            rows.append({
                "scenario": sc, "tenor": tenor,
                "CHF": chf, "EUR": eur, "USD": round(eur * 1.0), "GBP": round(eur * 1.25),
            })

    return pd.DataFrame(rows)


def get_snb_reversal_scenario() -> pd.DataFrame:
    """Return SNB rate reversal scenario (CHF -50bp, EUR -25bp).

    Models a scenario where the SNB reverses rate hikes, returning
    to negative territory, while EUR rates decline moderately.
    """
    tenors = ["O/N", "3M", "6M", "1Y", "2Y", "3Y", "5Y", "10Y", "20Y", "30Y"]
    rows = []
    for tenor in tenors:
        rows.append({
            "scenario": "snb_reversal", "tenor": tenor,
            "CHF": -50, "EUR": -25, "USD": 0, "GBP": 0,
        })
    return pd.DataFrame(rows)
