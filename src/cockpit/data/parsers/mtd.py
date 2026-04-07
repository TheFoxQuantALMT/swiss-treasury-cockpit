"""Parsers for deal data — ideal format (parse_deals) and legacy MTD format (parse_mtd)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ideal format: deals.xlsx — clean schema, rates in decimal, perimeter explicit
# ---------------------------------------------------------------------------

_DEALS_RENAME = {
    "deal_id": "Dealid",
    "product": "Product",
    "currency": "Currency",
    "direction": "Direction",
    "book": "IAS Book",
    "amount": "Amount",
    "client_rate": "Clientrate",
    "eq_ois_rate": "EqOisRate",
    "ytm": "YTM",
    "coc_rate": "CocRate",
    "spread": "Spread",
    "floating_index": "Floating Rates Short Name",
    "trade_date": "Tradedate",
    "value_date": "Valuedate",
    "maturity_date": "Maturitydate",
    "strategy_ias": "Strategy IAS",
    "hedge_type": "hedge_type",
    "ias_standard": "ias_standard",
    "designation_date": "designation_date",
    "perimeter": "Périmètre TOTAL",
    "counterparty": "Counterparty",
    "pay_receive": "pay_receive",
    "notional": "notional",
    "last_fixing_date": "last_fixing_date",
    "next_fixing_date": "next_fixing_date",
    "ftp": "FTP",
}

_VALID_PRODUCTS = {"IAM/LD", "BND", "FXS", "IRS", "IRS-MTM", "HCD"}
_VALID_DIRECTIONS = {"B", "L", "D", "S"}
_VALID_BOOKS = {"BOOK1", "BOOK2"}
_VALID_PERIMETERS = {"CC", "WM", "CIB"}
_VALID_FLOAT_INDICES = {"SARON", "ESTR", "SOFR", "SONIA", ""}


def parse_deals(path: Path) -> pd.DataFrame:
    """Parse ideal-format deals.xlsx → unified BOOK1 + BOOK2 DataFrame.

    Expects sheet 'Deals' with header in row 1, rates in decimal,
    direction as single char, perimeter explicit.
    """
    df = pd.read_excel(path, sheet_name="Deals", engine="openpyxl")

    # Rename to internal column names
    rename = {k: v for k, v in _DEALS_RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    # --- Validation ---
    if "Dealid" not in df.columns:
        raise ValueError("deals.xlsx: missing required column 'deal_id'")

    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")
    n_bad_id = df["Dealid"].isna().sum()
    if n_bad_id > 0:
        logger.warning("deals.xlsx: %d rows with non-numeric deal_id (dropped)", n_bad_id)
        df = df[df["Dealid"].notna()].copy()

    if "Product" in df.columns:
        bad_product = ~df["Product"].isin(_VALID_PRODUCTS)
        if bad_product.any():
            logger.warning("deals.xlsx: %d rows with invalid product (dropped)", bad_product.sum())
            df = df[~bad_product].copy()

    if "Currency" in df.columns:
        df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()

    if "Direction" in df.columns:
        bad_dir = ~df["Direction"].isin(_VALID_DIRECTIONS)
        if bad_dir.any():
            logger.warning("deals.xlsx: %d rows with invalid direction (dropped)", bad_dir.sum())
            df = df[~bad_dir].copy()

    if "IAS Book" in df.columns:
        bad_book = ~df["IAS Book"].isin(_VALID_BOOKS)
        if bad_book.any():
            logger.warning("deals.xlsx: %d rows with invalid book (dropped)", bad_book.sum())
            df = df[~bad_book].copy()

    if "Périmètre TOTAL" in df.columns:
        bad_peri = ~df["Périmètre TOTAL"].isin(_VALID_PERIMETERS)
        if bad_peri.any():
            logger.warning("deals.xlsx: %d rows with invalid perimeter, defaulting to CC", bad_peri.sum())
            df.loc[bad_peri, "Périmètre TOTAL"] = "CC"

    # Validate rate ranges (warn, don't drop)
    for col in ["Clientrate", "EqOisRate", "YTM", "CocRate", "Spread", "FTP"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            extreme = df[col].abs() > 0.50
            if extreme.any():
                logger.warning("deals.xlsx: %d rows with |%s| > 50%% — are rates in decimal?", extreme.sum(), col)

    # Parse dates
    for col in ["Maturitydate", "Valuedate", "Tradedate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    # Maturity is required
    if "Maturitydate" in df.columns:
        bad_mat = df["Maturitydate"].isna()
        if bad_mat.any():
            logger.warning("deals.xlsx: %d rows with invalid maturity_date (dropped)", bad_mat.sum())
            df = df[bad_mat == False].copy()  # noqa: E712

    # Fill blanks
    if "Floating Rates Short Name" in df.columns:
        df["Floating Rates Short Name"] = df["Floating Rates Short Name"].fillna("")

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Legacy format: MTD PnL Report — rates in percent, composite column names
# ---------------------------------------------------------------------------

_MTD_RENAME = {
    "Deal ID": "Dealid",
    "Product": "Product",
    "Deal Currency": "Currency",
    "ALMT Direction": "Direction",
    "Outstanding": "Amount",
    "Rate Reference": "Floating Rates Short Name",
    "Nominal Interest Rate": "Clientrate",
    # Note: some Excel versions use em-dash (–), others use regular hyphen (-)
    "BD \u2013 1 \u2013 Rate": "EqOisRate",
    "BD - 1 - Rate": "EqOisRate",
    "Yield To Maturity": "YTM",
    "CoC Rate": "CocRate",
    "Trade Date": "Tradedate",
    "Value Date": "Valuedate",
    "Maturity Date": "Maturitydate",
    "Strategy IAS": "Strategy IAS",
    "Credit Spread FIFO": "CreditSpread_FIFO",
    # The Excel file sometimes has a typo: "Counterpaty" (missing 'r')
    "Counterpaty": "Counterparty",
    "Counterparty": "Counterparty",
    "IAS Book": "IAS Book",
    "Spread": "Spread",
    "Post-counted interest flag": "Post-counted interest flag",
}

_RATE_COLS = ["Clientrate", "EqOisRate", "YTM", "CocRate"]


def parse_mtd(path: Path) -> pd.DataFrame:
    """Parse legacy MTD PnL Report → BOOK1 deals with rates in decimal.

    This is the legacy adapter. For the ideal format, use parse_deals().
    """
    # Try ideal format first
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        if "Deals" in xl.sheet_names:
            logger.info("Detected ideal-format deals file: %s", path)
            return parse_deals(path)
    except Exception:
        pass

    # Legacy MTD format
    from cockpit.config import _WM_COUNTERPARTIES, _CIB_COUNTERPARTIES

    raw = pd.read_excel(path, sheet_name="Conso Deal Level", skiprows=1, engine="openpyxl")

    rename = {k: v for k, v in _MTD_RENAME.items() if k in raw.columns}
    df = raw.rename(columns=rename)
    df["Direction"] = df["Direction"].str[0]

    # Perimeter from counterparty
    cpty_col = "Counterparty" if "Counterparty" in df.columns else "Counterpaty"
    df["Périmètre TOTAL"] = np.where(
        df[cpty_col].isin(_WM_COUNTERPARTIES), "WM",
        np.where(df[cpty_col].isin(_CIB_COUNTERPARTIES), "CIB", "CC"),
    )

    # BOOK1 only
    df = df[df["IAS Book"] == "BOOK1"].copy()

    # Credit spread subtraction for BND
    if "CreditSpread_FIFO" in df.columns:
        df["YTM"] = df["YTM"].fillna(0) - df["CreditSpread_FIFO"].fillna(0) / 100
        df = df.drop(columns=["CreditSpread_FIFO"])

    # Rates: percent → decimal
    for col in _RATE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0) / 100.0

    # Spread: bps → decimal
    if "Spread" in df.columns:
        df["Spread"] = pd.to_numeric(df["Spread"], errors="coerce").fillna(0.0) / 10_000.0

    # Filter: supported currencies, valid maturity
    df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()
    mat = pd.to_datetime(df["Maturitydate"], errors="coerce", dayfirst=True)
    df = df[mat.notna()].copy()

    return df.reset_index(drop=True)
