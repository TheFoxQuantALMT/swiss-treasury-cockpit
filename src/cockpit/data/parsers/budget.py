"""Parser for budget.xlsx — monthly NII budget by currency."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from pnl_engine.config import SUPPORTED_CURRENCIES


_BUDGET_RENAME = {
    "currency": "currency",
    "month": "month",
    "budget_nii": "budget_nii",
    "budget_nominal": "budget_nominal",
    "budget_rate": "budget_rate",
    "perimeter": "perimeter",
    "product": "product",
}


def parse_budget(path: Path | str) -> pd.DataFrame:
    """Parse budget Excel file.

    Expected sheet: "Budget" with columns:
        currency, month (YYYY-MM), budget_nii, [budget_nominal], [budget_rate],
        [perimeter], [product]

    Returns:
        DataFrame with standardized column names.
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="Budget", engine="openpyxl")
    except ValueError:
        # Try first sheet if "Budget" not found
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    # Normalize column names
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # Ensure required columns
    if "currency" not in df.columns or "budget_nii" not in df.columns:
        raise ValueError(f"budget.xlsx must have 'currency' and 'budget_nii' columns, got: {list(df.columns)}")

    if "month" not in df.columns:
        raise ValueError(f"budget.xlsx must have 'month' column, got: {list(df.columns)}")

    # Filter valid currencies
    df["currency"] = df["currency"].astype(str).str.upper().str.strip()
    df = df[df["currency"].isin(SUPPORTED_CURRENCIES)].copy()

    # Ensure month is string
    df["month"] = df["month"].astype(str).str.strip()

    # Fill optional columns
    if "perimeter" not in df.columns:
        df["perimeter"] = "CC"
    if "budget_nominal" not in df.columns:
        df["budget_nominal"] = 0.0
    if "budget_rate" not in df.columns:
        df["budget_rate"] = 0.0

    return df.reset_index(drop=True)
