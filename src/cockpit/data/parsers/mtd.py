"""Parser for ideal-format deals.xlsx → unified BOOK1 + BOOK2 DataFrame."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES
from pnl_engine.config import (
    VALID_PRODUCTS,
    VALID_DIRECTIONS,
    VALID_BOOKS,
    VALID_PERIMETERS,
    VALID_FLOAT_INDICES,
)

logger = logging.getLogger(__name__)

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
    "current_fixing_rate": "current_fixing_rate",
    "ftp": "FTP",
    "asset_liability": "AssetLiability",
}

_VALID_PRODUCTS = VALID_PRODUCTS
_VALID_DIRECTIONS = VALID_DIRECTIONS
_VALID_BOOKS = VALID_BOOKS
_VALID_PERIMETERS = VALID_PERIMETERS
_VALID_FLOAT_INDICES = VALID_FLOAT_INDICES


def parse_deals(path: Path) -> pd.DataFrame:
    """Parse ideal-format deals.xlsx → unified BOOK1 + BOOK2 DataFrame.

    Expects sheet 'Deals' with header in row 1, rates in decimal,
    direction as single char, perimeter explicit.
    """
    df = pd.read_excel(path, sheet_name="Deals", engine="openpyxl")

    rename = {k: v for k, v in _DEALS_RENAME.items() if k in df.columns}
    df = df.rename(columns=rename)

    if "Dealid" not in df.columns:
        raise ValueError("deals.xlsx: missing required column 'deal_id'")

    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")
    n_bad_id = df["Dealid"].isna().sum()
    if n_bad_id > 0:
        logger.warning("deals.xlsx: %d rows with non-numeric deal_id (dropped)", n_bad_id)
        df = df[df["Dealid"].notna()].copy()

    _n_before_filter = len(df)
    _n_bad_product = 0
    _n_bad_currency = 0
    _n_bad_dir = 0
    _n_bad_book = 0

    if "Product" in df.columns:
        bad_product = ~df["Product"].isin(_VALID_PRODUCTS)
        _n_bad_product = int(bad_product.sum())
        if bad_product.any():
            logger.warning("deals.xlsx: %d rows with invalid product (dropped)", _n_bad_product)
            df = df[~bad_product].copy()

    if "Currency" in df.columns:
        _n_bad_currency = int((~df["Currency"].isin(SUPPORTED_CURRENCIES)).sum())
        df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()

    if "Direction" in df.columns:
        bad_dir = ~df["Direction"].isin(_VALID_DIRECTIONS)
        _n_bad_dir = int(bad_dir.sum())
        if bad_dir.any():
            logger.warning("deals.xlsx: %d rows with invalid direction (dropped)", _n_bad_dir)
            df = df[~bad_dir].copy()

    if "IAS Book" in df.columns:
        bad_book = ~df["IAS Book"].isin(_VALID_BOOKS)
        _n_bad_book = int(bad_book.sum())
        if bad_book.any():
            logger.warning("deals.xlsx: %d rows with invalid book (dropped)", _n_bad_book)
            df = df[~bad_book].copy()

    _n_dropped = _n_before_filter - len(df)
    if _n_dropped > 0:
        logger.info(
            "[parse] Dropped %d rows: %d unknown products, %d unsupported currencies, "
            "%d invalid directions, %d invalid books",
            _n_dropped, _n_bad_product, _n_bad_currency, _n_bad_dir, _n_bad_book,
        )

    if "Périmètre TOTAL" in df.columns:
        bad_peri = ~df["Périmètre TOTAL"].isin(_VALID_PERIMETERS)
        if bad_peri.any():
            logger.warning("deals.xlsx: %d rows with invalid perimeter, defaulting to CC", bad_peri.sum())
            df.loc[bad_peri, "Périmètre TOTAL"] = "CC"

    for col in ["Clientrate", "EqOisRate", "YTM", "CocRate", "Spread"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            extreme = df[col].abs() > 0.50
            if extreme.any():
                logger.warning("deals.xlsx: %d rows with |%s| > 50%% — are rates in decimal?", extreme.sum(), col)

    # FTP: keep NaN to distinguish "missing FTP" from "explicit 0.0 FTP".
    # Downstream charts filter on .notna() and surface coverage separately.
    if "FTP" in df.columns:
        df["FTP"] = pd.to_numeric(df["FTP"], errors="coerce")
        n_ftp_missing = int(df["FTP"].isna().sum())
        if n_ftp_missing > 0:
            logger.info("deals.xlsx: %d rows with missing FTP (kept as NaN)", n_ftp_missing)
        extreme_ftp = df["FTP"].abs() > 0.50
        if extreme_ftp.any():
            logger.warning("deals.xlsx: %d rows with |FTP| > 50%% — are rates in decimal?", int(extreme_ftp.sum()))

    for col in ["Maturitydate", "Valuedate", "Tradedate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    if "Maturitydate" in df.columns:
        bad_mat = df["Maturitydate"].isna()
        if bad_mat.any():
            logger.warning("deals.xlsx: %d rows with invalid maturity_date (dropped)", bad_mat.sum())
            df = df[bad_mat == False].copy()  # noqa: E712

    if "Floating Rates Short Name" in df.columns:
        df["Floating Rates Short Name"] = df["Floating Rates Short Name"].fillna("")

    return df.reset_index(drop=True)
