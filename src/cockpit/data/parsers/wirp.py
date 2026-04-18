"""Parser for ideal-format wirp.xlsx — proper header, WASP index names, rates in decimal."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_VALID_INDICES = {"CHFSON", "EUREST", "USSOFR", "GBPOIS"}

_WIRP_RENAME = {
    "index": "Indice",
    "meeting_date": "Meeting",
    "rate": "Rate",
    "change_bps": "Hike / Cut",
}


def parse_wirp_ideal(path: Path) -> pd.DataFrame:
    """Parse ideal-format wirp.xlsx → long DataFrame with WASP index names."""
    df = pd.read_excel(path, sheet_name="WIRP", engine="openpyxl")

    rename = {k: v for k, v in _WIRP_RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    if "Indice" not in df.columns:
        raise ValueError("wirp.xlsx: missing required column 'index'")

    bad_idx = ~df["Indice"].isin(_VALID_INDICES)
    if bad_idx.any():
        logger.warning("wirp.xlsx: %d rows with unknown index (dropped)", bad_idx.sum())
        df = df[~bad_idx].copy()

    df["Meeting"] = pd.to_datetime(df["Meeting"], errors="coerce", dayfirst=True)
    df = df.dropna(subset=["Meeting"])

    if "Rate" in df.columns:
        df["Rate"] = pd.to_numeric(df["Rate"], errors="coerce")
        extreme = df["Rate"].abs() > 0.20
        if extreme.any():
            logger.warning("wirp.xlsx: %d rows with |rate| > 20%% — are rates in decimal?", extreme.sum())

    return df.sort_values(["Indice", "Meeting"]).reset_index(drop=True)
