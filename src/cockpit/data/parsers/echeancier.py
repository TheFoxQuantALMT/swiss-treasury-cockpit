"""Parsers for schedule data — ideal format (parse_schedule) and legacy (parse_echeancier)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)

_VALID_DIRECTIONS = {"B", "L", "D", "S"}


def _month_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM' date strings."""
    return [c for c in df.columns if isinstance(c, str) and "/" in c and c[:4].isdigit()]


# ---------------------------------------------------------------------------
# Ideal format: rate_schedule.xlsx — clean schema, pre-filtered, explicit direction
# ---------------------------------------------------------------------------

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

    # Rename to internal column names
    rename = {k: v for k, v in _SCHEDULE_RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    # --- Validation ---
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


# ---------------------------------------------------------------------------
# Legacy format: Echeancier — composite IDs, implicit direction, needs filtering
# ---------------------------------------------------------------------------

def parse_echeancier(path: Path) -> pd.DataFrame:
    """Parse legacy Echeancier → wide DataFrame with monthly balances.

    This is the legacy adapter. For the ideal format, use parse_schedule().
    """
    # Try ideal format first
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        if "Schedule" in xl.sheet_names:
            logger.info("Detected ideal-format schedule file: %s", path)
            return parse_schedule(path)
    except (ValueError, KeyError):
        pass

    # Legacy Echeancier format
    df = pd.read_excel(path, sheet_name="Operations Propres EoM", skiprows=2, engine="openpyxl")

    # Drop leading unnamed column
    first_col = df.columns[0]
    if str(first_col).startswith("Unnamed"):
        df = df.drop(columns=first_col)

    deal_col = df.columns[0]  # Deal Number KND
    df = df.dropna(subset=[deal_col])

    # Parse deal type and ID
    split_data = df[deal_col].astype(str).str.split("@", n=1, expand=True)
    if split_data.shape[1] < 2:
        split_data[1] = np.nan
    df[["Deal Type", "Dealid"]] = split_data
    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")

    rate_type_col = [c for c in df.columns if "Rate Type" in str(c)]
    post_flag_col = [c for c in df.columns if "Post-counted" in str(c)]

    # Filter: drop RFR V-legs
    rate_code_col = [c for c in df.columns if "level 1 Code" in str(c)]
    if rate_type_col:
        rt = df[rate_type_col[0]]
        pf = df[post_flag_col[0]].fillna(0) if post_flag_col else pd.Series(0, index=df.index)
        rc = df[rate_code_col[0]] if rate_code_col else pd.Series("", index=df.index)
        is_rfr_v = (rt == "V") & ((pf == 1) | (rc == "RFR"))
        df = df[~is_rfr_v].copy()

    # Filter: drop reverse repo V-legs
    level5_col = [c for c in df.columns if "level 5" in str(c)]
    if rate_type_col and level5_col:
        rt = df[rate_type_col[0]]
        l5 = df[level5_col[0]].fillna("")
        df = df[~((rt == "V") & (l5 == "Reverse repos"))].copy()

    # Direction: BD@ = Bond → B, else from balance sign
    month_cols = _month_columns(df)
    is_bond = df["Deal Type"] == "BD"
    if month_cols:
        balance_sum = df[month_cols].sum(axis=1)
    else:
        logger.warning("parse_echeancier: no YYYY/MM balance columns found, direction inference unreliable")
        balance_sum = pd.Series(0, index=df.index)
    df["Direction"] = np.where(is_bond, "B", np.where(balance_sum < 0, "L", "D"))

    # Currency
    curr_cols = [c for c in df.columns if "currency" in str(c).lower()]
    if curr_cols:
        df["Currency"] = df[curr_cols[0]]

    # V-leg carry-forward
    if rate_type_col:
        rt_col = rate_type_col[0]
        v_mask = df[rt_col] == "V"
        if v_mask.any():
            df.loc[v_mask, month_cols] = df.loc[v_mask, month_cols].ffill(axis=1)

    return df.reset_index(drop=True)
