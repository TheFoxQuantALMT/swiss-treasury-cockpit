"""Parser for counterparty reference table Excel files."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_reference_table(path: Path) -> pd.DataFrame:
    """Parse counterparty reference table → DataFrame with rating, HQLA, country.

    Expected columns: counterparty, rating, hqla_level, country.
    Missing values get defaults: rating='NR', hqla_level='Non-HQLA', country='XX'.
    """
    df = pd.read_excel(path, engine="openpyxl")
    expected = ["counterparty", "rating", "hqla_level", "country"]
    for col in expected:
        if col not in df.columns:
            df[col] = None
    df = df[expected].copy()
    df["rating"] = df["rating"].fillna("NR")
    df["hqla_level"] = df["hqla_level"].fillna("Non-HQLA")
    df["country"] = df["country"].fillna("XX")
    return df.reset_index(drop=True)
