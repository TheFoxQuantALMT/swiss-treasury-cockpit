"""Parser for nmd_profiles.xlsx — Non-Maturing Deposit behavioral profiles."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_nmd_profiles(path: Path | str) -> pd.DataFrame:
    """Parse NMD profiles Excel file.

    Expected sheet: "NMD" with columns:
        product, currency, direction, tier, behavioral_maturity_years,
        decay_rate, deposit_beta, floor_rate

    Returns:
        DataFrame with NMD profile definitions.
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="NMD", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    required = ["product", "currency", "direction"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"nmd_profiles.xlsx must have '{col}' column, got: {list(df.columns)}")

    # Defaults for optional columns
    defaults = {
        "tier": "core",
        "behavioral_maturity_years": 5.0,
        "decay_rate": 0.15,
        "deposit_beta": 0.5,
        "floor_rate": 0.0,
    }
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    # Type coercion
    for col in ["behavioral_maturity_years", "decay_rate", "deposit_beta", "floor_rate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(defaults.get(col, 0.0))

    return df
