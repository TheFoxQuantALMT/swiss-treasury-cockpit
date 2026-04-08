"""Parsers for WIRP data — ideal format and legacy format."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_VALID_INDICES = {"CHFSON", "EUREST", "USSOFR", "GBPOIS"}

# ---------------------------------------------------------------------------
# Ideal format: wirp.xlsx — proper header, WASP index names, rates in decimal
# ---------------------------------------------------------------------------

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

    # Validate indices
    bad_idx = ~df["Indice"].isin(_VALID_INDICES)
    if bad_idx.any():
        logger.warning("wirp.xlsx: %d rows with unknown index (dropped)", bad_idx.sum())
        df = df[~bad_idx].copy()

    # Parse meeting dates
    df["Meeting"] = pd.to_datetime(df["Meeting"], errors="coerce", dayfirst=True)
    df = df.dropna(subset=["Meeting"])

    # Validate rate range
    if "Rate" in df.columns:
        df["Rate"] = pd.to_numeric(df["Rate"], errors="coerce")
        extreme = df["Rate"].abs() > 0.20
        if extreme.any():
            logger.warning("wirp.xlsx: %d rows with |rate| > 20%% — are rates in decimal?", extreme.sum())

    return df.sort_values(["Indice", "Meeting"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Legacy format: WIRP — usecols, skiprows, forward-fill
# ---------------------------------------------------------------------------

def parse_wirp(path: Path) -> pd.DataFrame:
    """Parse WIRP → long DataFrame with (Indice, Meeting date, Rate, Hike/Cut).

    Tries ideal format first, falls back to legacy.
    """
    # Try ideal format first
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        if "WIRP" in xl.sheet_names:
            test_df = pd.read_excel(path, sheet_name="WIRP", nrows=1, engine="openpyxl")
            if "index" in test_df.columns or "Indice" in test_df.columns:
                logger.info("Detected ideal-format WIRP file: %s", path)
                return parse_wirp_ideal(path)
    except (ValueError, KeyError):
        pass

    # Legacy format
    raw = pd.read_excel(path, skiprows=2, usecols=[2, 3, 4, 5], engine="openpyxl")
    raw.columns = ["Indice", "Meeting", "Rate", "Hike / Cut"]
    raw["Indice"] = raw["Indice"].ffill()
    raw = raw.dropna(subset=["Meeting"])
    raw["Meeting"] = pd.to_datetime(raw["Meeting"], errors="coerce", dayfirst=True)
    raw = raw.dropna(subset=["Meeting"])
    return raw.reset_index(drop=True)
