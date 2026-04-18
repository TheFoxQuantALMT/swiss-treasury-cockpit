"""Parser for K+EUR Daily Rate PnL GVA format (Book1 + Book2 sheets)."""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from cockpit.config import SUPPORTED_CURRENCIES
from pnl_engine.config import VALID_DIRECTIONS

logger = logging.getLogger(__name__)

_SHEET_MAP = {
    "Book1": "Book1_Daily_PnL",
    "Book2": "Book2_Daily_PnL",
}

_BOOK_RENAME = {
    "Deal ID": "Dealid",
    "Deal Currency @Cur_Agg": "Currency",
    "@Direction": "Direction",
    "Calculated Initial Amount (Measure)": "Amount",
    "Rate Reference": "Floating Rates Short Name",
    "Nominal Interest Rate": "Clientrate",
    "Yield to Maturity": "YTM",
    "BD - 1 - Rate": "EqOisRate",
    "BD \u2013 1 \u2013 Rate": "EqOisRate",  # em-dash variant
    "Credit Spread FIFO": "CreditSpread_FIFO",
    "Trade Date": "Tradedate",
    "Value Date": "Valuedate",
    "Maturity Date": "Maturitydate",
    "Liquidation Date": "Liquidation Date",
    "Strategy IAS": "Strategy IAS",
    "CRDS Counterparty Code": "Counterparty",
    "@Amount_CHF": "Amount_CHF",
    "Portfolio Short Name": "Portfolio Short Name",
    "Folder Short Name": "Folder Short Name",
    "Source Product Code": "Source Product Code",
    "Source Sub Product Type": "Source Sub Product Type",
    "@Indexation": "Indexation",
    "ISIN Code": "ISIN Code",
    "Rate Start Date": "Rate Start Date",
    "Rate End Date": "Rate End Date",
    "@NbBasis": "NbBasis",
    "@EqOISRate2": "EqOISRate2",
    "CoC/SellDown Carry Date": "CocCarryDate",
    "@Pnl_Acc_Estim_Unadj": "PnL_Acc_Unadj",
    "@PnL_CoC_Estim_Unadj": "PnL_CoC_Unadj",
    "@Nb_Day_Adj": "Nb_Day_Adj",
    "@PnL_Acc_Estim_Adj": "PnL_Acc_Adj",
    "@PnL_Coc_Estim_Adj": "PnL_CoC_Adj",
    "[Daily] PnL IAS - ORC": "PnL_IAS",
    "[Daily] PnL MTM - ORC": "PnL_MTM",
    "IAM Deal ID": "IAM Deal ID",
    "Clean_Price": "Clean Price",  # % of par, bonds only; NaN elsewhere
}

_RATE_COLS = ["Clientrate", "EqOisRate", "YTM"]


def parse_book(
    path: Path,
    date_run: pd.Timestamp,
    book: str,
) -> pd.DataFrame:
    """Parse a single book sheet from K+EUR Daily Rate PnL GVA file.

    Parameters
    ----------
    path : Path
        Excel file path (e.g. ``K+EUR Daily Rate PnL GVA.xlsx``).
    date_run : pd.Timestamp
        Position date to filter on.
    book : str
        ``"Book1"`` or ``"Book2"``.

    Returns
    -------
    pd.DataFrame
        Deals with canonical internal column names, rates in decimal.
    """
    sheet = _SHEET_MAP.get(book)
    if sheet is None:
        raise ValueError(f"Unknown book '{book}', expected one of {list(_SHEET_MAP)}")

    raw = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    rename = {k: v for k, v in _BOOK_RENAME.items() if k in raw.columns}
    df = raw.rename(columns=rename)

    # --- Filter by Position Date ---
    if "Position Date" in df.columns:
        df["Position Date"] = pd.to_datetime(df["Position Date"], errors="coerce")
        target = pd.Timestamp(date_run).normalize()
        df = df[df["Position Date"].dt.normalize() == target].copy()
        if df.empty:
            logger.warning("parse_book(%s): no rows for Position Date %s", book, target.date())
            return df

    # --- Dealid ---
    if "Dealid" not in df.columns:
        raise ValueError(f"parse_book({book}): missing 'Deal ID' column in {path.name}")
    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")
    n_bad_id = df["Dealid"].isna().sum()
    if n_bad_id > 0:
        logger.warning("parse_book(%s): %d rows with non-numeric Deal ID (dropped)", book, n_bad_id)
        df = df[df["Dealid"].notna()].copy()

    # --- Product derivation ---
    src_product = df.get("Source Product Code", pd.Series("", index=df.index)).fillna("")
    folder = df.get("Folder Short Name", pd.Series("", index=df.index)).fillna("")
    df["Product"] = np.where(
        src_product.isin(["LD", "IAM"]),
        "IAM/LD",
        np.where(folder == "TMSWBFIGE", "IRS-MTM", src_product),
    )

    # --- Direction: first char ---
    if "Direction" in df.columns:
        df["Direction"] = df["Direction"].astype(str).str[0]
        bad_dir = ~df["Direction"].isin(VALID_DIRECTIONS)
        if bad_dir.any():
            logger.warning("parse_book(%s): %d rows with invalid Direction (dropped)", book, int(bad_dir.sum()))
            df = df[~bad_dir].copy()

    # --- IAS Book from sheet name ---
    df["IAS Book"] = book.upper()  # "BOOK1" or "BOOK2"

    # --- Perimeter from counterparty ---
    from cockpit.config import _WM_COUNTERPARTIES, _CIB_COUNTERPARTIES

    if "Counterparty" in df.columns:
        df["Périmètre TOTAL"] = np.where(
            df["Counterparty"].isin(_WM_COUNTERPARTIES), "WM",
            np.where(df["Counterparty"].isin(_CIB_COUNTERPARTIES), "CIB", "CC"),
        )
    else:
        df["Périmètre TOTAL"] = "CC"

    # --- Credit Spread subtraction for BND ---
    if "CreditSpread_FIFO" in df.columns and "YTM" in df.columns:
        df["YTM"] = df["YTM"].fillna(0) - df["CreditSpread_FIFO"].fillna(0) / 100
        df = df.drop(columns=["CreditSpread_FIFO"])

    # --- Rates: percent → decimal ---
    for col in _RATE_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0) / 100.0

    # --- Spread: bps → decimal ---
    if "Spread" in df.columns:
        df["Spread"] = pd.to_numeric(df["Spread"], errors="coerce").fillna(0.0) / 10_000.0

    # --- Clean Price: % of par, kept as-is (NaN for non-bond rows) ---
    if "Clean Price" in df.columns:
        df["Clean Price"] = pd.to_numeric(df["Clean Price"], errors="coerce")

    # --- Filter: supported currencies ---
    if "Currency" in df.columns:
        n_before = len(df)
        df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()
        n_dropped = n_before - len(df)
        if n_dropped > 0:
            logger.info("parse_book(%s): dropped %d rows with unsupported currency", book, n_dropped)

    # --- Parse dates ---
    for col in ["Maturitydate", "Valuedate", "Tradedate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=True)

    # --- Maturity required ---
    if "Maturitydate" in df.columns:
        bad_mat = df["Maturitydate"].isna()
        if bad_mat.any():
            logger.warning("parse_book(%s): %d rows with invalid maturity (dropped)", book, int(bad_mat.sum()))
            df = df[~bad_mat].copy()

    # --- Fill blanks ---
    if "Floating Rates Short Name" in df.columns:
        df["Floating Rates Short Name"] = df["Floating Rates Short Name"].fillna("")

    logger.info("parse_book(%s): %d deals loaded from %s", book, len(df), path.name)
    return df.reset_index(drop=True)
