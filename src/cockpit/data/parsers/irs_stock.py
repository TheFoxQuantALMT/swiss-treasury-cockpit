"""Parser for IRS stock (BOOK2 MTM) Excel files."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_irs_stock(path: Path) -> pd.DataFrame:
    """Parse IRS.xlsx → swap stock for BOOK2 MTM pricing."""
    raw = pd.read_excel(path, engine="openpyxl", header=None)
    if len(raw) < 5:
        raise ValueError(f"IRS stock file has unexpected format ({len(raw)} rows, expected >= 5): {path}")
    colnames = raw.iloc[3, 1:]
    df = raw.iloc[4:, 1:].copy()
    df.columns = colnames
    if "Index" in df.columns:
        df["Index"] = df["Index"].fillna("")
    return df.reset_index(drop=True)
