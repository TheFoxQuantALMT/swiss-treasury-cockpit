"""Parser for alert_thresholds.xlsx — per-currency alert threshold overrides."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_alert_thresholds(path: Path | str) -> dict:
    """Parse alert thresholds Excel file.

    Expected sheet: "Thresholds" with columns:
        currency, annual_nii_floor, mom_delta_pct, ccy_concentration_pct, shock_sensitivity_limit

    Currency "ALL" sets global defaults; specific currencies override.

    Returns:
        Dict with structure: {"ALL": {threshold_name: value}, "CHF": {...}, ...}
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="Thresholds", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    df.columns = [str(c).strip().lower() for c in df.columns]
    if "currency" not in df.columns:
        raise ValueError(f"alert_thresholds.xlsx must have 'currency' column, got: {list(df.columns)}")

    threshold_cols = ["annual_nii_floor", "mom_delta_pct", "ccy_concentration_pct", "shock_sensitivity_limit"]
    result = {}
    for _, row in df.iterrows():
        ccy = str(row["currency"]).strip().upper()
        overrides = {}
        for col in threshold_cols:
            if col in row and pd.notna(row[col]):
                overrides[col] = float(row[col])
        if overrides:
            result[ccy] = overrides

    return result
