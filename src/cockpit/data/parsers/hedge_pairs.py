"""Parser for hedge_pairs.xlsx — IAS hedge relationship definitions."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_hedge_pairs(path: Path | str) -> pd.DataFrame:
    """Parse hedge pairs Excel file.

    Expected sheet: "HedgePairs" with columns:
        pair_id, pair_name, hedged_item_deal_ids (comma-separated),
        hedging_instrument_deal_ids (comma-separated),
        hedge_type (fair_value|cash_flow), designation_date,
        ias_standard (IAS39|IFRS9)

    Returns:
        DataFrame with standardized columns.
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="HedgePairs", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    # Normalize column names
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    required = {"pair_id", "hedged_item_deal_ids", "hedging_instrument_deal_ids"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"hedge_pairs.xlsx missing columns: {missing}")

    # Fill defaults
    if "pair_name" not in df.columns:
        df["pair_name"] = df["pair_id"].apply(lambda x: f"Pair {x}")
    if "hedge_type" not in df.columns:
        df["hedge_type"] = "cash_flow"
    if "ias_standard" not in df.columns:
        df["ias_standard"] = "IFRS9"
    if "designation_date" not in df.columns:
        df["designation_date"] = ""

    # Ensure string types for deal ID columns
    df["hedged_item_deal_ids"] = df["hedged_item_deal_ids"].astype(str)
    df["hedging_instrument_deal_ids"] = df["hedging_instrument_deal_ids"].astype(str)

    return df.reset_index(drop=True)
