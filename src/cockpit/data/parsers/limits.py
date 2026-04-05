"""Parser for limits.xlsx — Board-approved NII/EVE limits."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_limits(path: Path | str) -> pd.DataFrame:
    """Parse limits Excel file.

    Expected sheet: "Limits" with columns:
        metric, currency, limit_value, warning_pct, limit_type

    Standard metrics:
      - nii_sensitivity_50bp: |NII(+50bp) - NII(0)| <= limit
      - nii_at_risk_worst: |worst scenario NII - base NII| <= limit
      - eve_change_200bp: |ΔEVE(+200bp)| <= limit
      - eve_change_worst: |worst scenario ΔEVE| <= limit
      - concentration_hhi: HHI on counterparty P&L <= limit

    Returns:
        DataFrame with limit definitions.
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="Limits", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    if "metric" not in df.columns:
        raise ValueError(f"limits.xlsx must have 'metric' column, got: {list(df.columns)}")

    # Defaults
    if "currency" not in df.columns:
        df["currency"] = "ALL"
    if "warning_pct" not in df.columns:
        df["warning_pct"] = 80.0
    if "limit_type" not in df.columns:
        df["limit_type"] = "absolute"

    df["limit_value"] = pd.to_numeric(df["limit_value"], errors="coerce")
    df["warning_pct"] = pd.to_numeric(df["warning_pct"], errors="coerce").fillna(80.0)
    df["currency"] = df["currency"].fillna("ALL").str.strip().str.upper()

    return df
