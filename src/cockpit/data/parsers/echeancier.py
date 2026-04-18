"""Parser for ideal-format rate_schedule.xlsx → wide DataFrame with monthly balances."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)

_VALID_DIRECTIONS = {"B", "L", "D", "S"}


def _month_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM' date strings."""
    return [c for c in df.columns if isinstance(c, str) and "/" in c and c[:4].isdigit()]


_SCHEDULE_RENAME = {
    "deal_id": "Dealid",
    "direction": "Direction",
    "currency": "Currency",
    "rate_type": "Rate Type",
}


def parse_schedule(path: Path) -> pd.DataFrame:
    """Parse ideal-format rate_schedule.xlsx → wide DataFrame with monthly balances.

    Expects sheet 'Schedule' with header in row 1, deal_id as plain integer,
    direction as single char, RFR V-legs and reverse repos pre-filtered,
    V-leg balances pre-forward-filled.
    """
    df = pd.read_excel(path, sheet_name="Schedule", engine="openpyxl")

    rename = {k: v for k, v in _SCHEDULE_RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    if "Dealid" not in df.columns:
        raise ValueError("rate_schedule.xlsx: missing required column 'deal_id'")

    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")
    n_bad = df["Dealid"].isna().sum()
    if n_bad > 0:
        logger.warning("rate_schedule.xlsx: %d rows with non-numeric deal_id (dropped)", n_bad)
        df = df[df["Dealid"].notna()].copy()

    if "Direction" in df.columns:
        bad_dir = ~df["Direction"].isin(_VALID_DIRECTIONS)
        if bad_dir.any():
            logger.warning("rate_schedule.xlsx: %d rows with invalid direction (dropped)", bad_dir.sum())
            df = df[~bad_dir].copy()

    if "Currency" in df.columns:
        bad_ccy = ~df["Currency"].isin(SUPPORTED_CURRENCIES)
        if bad_ccy.any():
            logger.warning("rate_schedule.xlsx: %d rows with unsupported currency (dropped)", bad_ccy.sum())
            df = df[~bad_ccy].copy()

    month_cols = _month_columns(df)
    if not month_cols:
        logger.warning("rate_schedule.xlsx: no YYYY/MM balance columns found")

    return df.reset_index(drop=True)
