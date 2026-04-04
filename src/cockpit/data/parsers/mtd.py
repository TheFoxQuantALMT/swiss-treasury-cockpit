"""Parser for MTD PnL Report Excel files."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cockpit.config import (
    SUPPORTED_CURRENCIES,
    _WM_COUNTERPARTIES,
    _CIB_COUNTERPARTIES,
)

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
    "Indexation": "Indexation",
    "Source Sub Product Type": "Typeofinstr",
    "Spread": "Spread",
    "Basis": "Basis",
    "Post-counted interest flag": "Post-counted interest flag",
}

_RATE_COLS = ["Clientrate", "EqOisRate", "YTM", "CocRate"]


def parse_mtd(path: Path) -> pd.DataFrame:
    """Parse MTD PnL Report → BOOK1 deals with rates in decimal."""
    raw = pd.read_excel(path, sheet_name="Conso Deal Level", skiprows=1, engine="openpyxl")

    rename = {k: v for k, v in _MTD_RENAME.items() if k in raw.columns}
    df = raw.rename(columns=rename)
    df["Direction"] = df["Direction"].str[0]

    # Perimeter from counterparty (column may be "Counterparty" after rename)
    cpty_col = "Counterparty" if "Counterparty" in df.columns else "Counterpaty"
    df["Périmètre TOTAL"] = np.where(
        df[cpty_col].isin(_WM_COUNTERPARTIES), "WM",
        np.where(df[cpty_col].isin(_CIB_COUNTERPARTIES), "CIB", "CC"),
    )

    # BOOK1 only — IRS-MTM deals come from Agapes schedule (Folder=TMSWBFIGE)
    df = df[df["IAS Book"] == "BOOK1"].copy()

    # Credit spread subtraction for BND (before rate division)
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
