"""Parser for custom_scenarios.xlsx — user-defined rate shock scenarios.

Expected format:
    | scenario | tenor | CHF | EUR | USD | GBP |
    |----------|-------|-----|-----|-----|-----|
    | SNB_reversal | 0.25 | -50 | -25 | 0 | 0 |
    | SNB_reversal | 1    | -50 | -25 | 0 | 0 |
    | ...          | ...  | ... | ... | ... | ... |

Tenors are in years (BCBS 368 convention).
Shocks are in basis points.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def parse_custom_scenarios(path: Path | str) -> Optional[pd.DataFrame]:
    """Parse custom_scenarios.xlsx into a DataFrame.

    Returns DataFrame with columns: scenario, tenor, and one column per currency.
    Returns None if the file doesn't exist or is empty.
    """
    path = Path(path)
    if not path.exists():
        return None

    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception:
        return None

    if df.empty:
        return None

    # Normalize column names
    df.columns = [str(c).strip() for c in df.columns]

    required = {"scenario", "tenor"}
    if not required.issubset(set(df.columns.str.lower())):
        return None

    # Normalize scenario and tenor columns
    col_map = {c: c.lower() for c in df.columns if c.lower() in required}
    df = df.rename(columns=col_map)

    df["scenario"] = df["scenario"].astype(str).str.strip()
    df["tenor"] = pd.to_numeric(df["tenor"], errors="coerce")

    # Currency columns are everything except scenario and tenor
    ccy_cols = [c for c in df.columns if c not in ("scenario", "tenor")]
    for c in ccy_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    return df


def custom_scenarios_to_bcbs_format(df: pd.DataFrame) -> list[dict]:
    """Convert custom scenarios DataFrame to the BCBS-style dict format.

    Returns list of dicts compatible with the scenario engine:
    [{"name": "SNB_reversal", "shocks": {"CHF": {0.25: -50, 1: -50, ...}, ...}}, ...]
    """
    if df is None or df.empty:
        return []

    scenarios = []
    ccy_cols = [c for c in df.columns if c not in ("scenario", "tenor")]

    for name, group in df.groupby("scenario"):
        shocks: dict[str, dict[float, float]] = {}
        for ccy in ccy_cols:
            tenor_shocks = {}
            for _, row in group.iterrows():
                tenor = float(row["tenor"])
                shock_bp = float(row[ccy])
                if shock_bp != 0:
                    tenor_shocks[tenor] = shock_bp
            if tenor_shocks:
                shocks[ccy.upper()] = tenor_shocks
        scenarios.append({"name": str(name), "shocks": shocks})

    return scenarios
