"""Parser for liquidity schedule — daily cash flows (90 days) + monthly thereafter.

Same wide format as schedule.xlsx: Dealid, Direction, Currency, then date columns.
Date columns can be YYYY/MM (monthly) or YYYY/MM/DD (daily).
Values represent cash flows (interest + principal), not outstanding balances.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)

_VALID_DIRECTIONS = {"B", "L", "D", "S"}

# Matches YYYY/MM or YYYY/MM/DD date columns
_DATE_COL_RE = re.compile(r"^\d{4}/\d{2}(/\d{2})?$")

_RENAME = {
    "deal_id": "Dealid",
    "direction": "Direction",
    "currency": "Currency",
}


def _date_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like date strings (YYYY/MM or YYYY/MM/DD)."""
    return [c for c in df.columns if isinstance(c, str) and _DATE_COL_RE.match(c)]


def _col_to_date(col: str) -> pd.Timestamp:
    """Convert a date column name to a Timestamp for sorting/aggregation."""
    parts = col.split("/")
    if len(parts) == 3:
        return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
    # Monthly: use first of month
    return pd.Timestamp(int(parts[0]), int(parts[1]), 1)


def parse_liquidity_schedule(path: Path) -> pd.DataFrame:
    """Parse liquidity_schedule.xlsx → wide DataFrame with cash flow columns.

    Expects sheet 'Liquidity' (or 'Schedule') with:
    - deal_id / Dealid: numeric deal identifier
    - direction / Direction: B, L, D, S
    - currency / Currency: CHF, EUR, USD, GBP
    - date columns (YYYY/MM or YYYY/MM/DD): cash flow amounts
    """
    xl = pd.ExcelFile(path, engine="openpyxl")

    # Try 'Liquidity' sheet first, fall back to 'Schedule'
    sheet = None
    for candidate in ["Liquidity", "Schedule", xl.sheet_names[0]]:
        if candidate in xl.sheet_names:
            sheet = candidate
            break

    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")

    # Rename to internal column names
    rename = {k: v for k, v in _RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    # --- Validation ---
    if "Dealid" not in df.columns:
        raise ValueError(f"liquidity_schedule: missing required column 'deal_id' / 'Dealid' in {path}")

    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")
    n_bad = df["Dealid"].isna().sum()
    if n_bad > 0:
        logger.warning("liquidity_schedule: %d rows with non-numeric deal_id (dropped)", n_bad)
        df = df[df["Dealid"].notna()].copy()

    if "Direction" in df.columns:
        bad_dir = ~df["Direction"].isin(_VALID_DIRECTIONS)
        if bad_dir.any():
            logger.warning("liquidity_schedule: %d rows with invalid direction (dropped)", bad_dir.sum())
            df = df[~bad_dir].copy()

    if "Currency" in df.columns:
        bad_ccy = ~df["Currency"].isin(SUPPORTED_CURRENCIES)
        if bad_ccy.any():
            logger.warning("liquidity_schedule: %d rows with unsupported currency (dropped)", bad_ccy.sum())
            df = df[~bad_ccy].copy()

    date_cols = _date_columns(df)
    if not date_cols:
        logger.warning("liquidity_schedule: no date columns found in %s", path)

    # Sort date columns chronologically
    date_cols_sorted = sorted(date_cols, key=_col_to_date)
    meta_cols = [c for c in df.columns if c not in date_cols]
    df = df[meta_cols + date_cols_sorted].reset_index(drop=True)

    # Fill NaN cash flows with 0
    for col in date_cols_sorted:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    n_daily = sum(1 for c in date_cols_sorted if len(c.split("/")) == 3)
    n_monthly = len(date_cols_sorted) - n_daily
    logger.info("liquidity_schedule: %d deals, %d daily cols, %d monthly cols", len(df), n_daily, n_monthly)

    return df
