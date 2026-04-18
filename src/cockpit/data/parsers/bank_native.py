"""Parsers for the bank-native K+EUR / Optimus input format (replacing MTD/echeancier).

The bank delivers three files per day under ``YYYYPP/YYYYMMDDVV/``:

1. ``K+EUR Daily Rate PnL GVA_YYYYMMDD.xlsx`` — two sheets, ``Book1_Daily_PnL``
   (accrual / IAS) and ``Book2_Daily_PnL`` (mark-to-market). Real exports
   often store rates as percent and credit spreads as basis points; the
   parser auto-detects (max |x| > 1.0) and rescales to decimal. Test
   fixtures use decimal directly. Nominals are already signed per
   ``DIRECTION_SIDE``.
2. ``YYYYMMDD_WIRP.xlsx`` — market-implied policy rate expectations keyed by
   bare short names (SARON / ESTR / SOFR / SONIA).
3. ``YYYYMMDD_rate_schedule.xlsx`` — wide monthly nominal schedule, sheet
   ``Operation_Propres EoM``, 60 monthly buckets (``YYYY/MM``).

The parser output shape is drop-in compatible with ``parse_deals()`` /
``parse_schedule()`` / ``parse_wirp_ideal()`` so downstream code sees
familiar column names. It additionally carries three bank-native columns:

- ``Category2`` — one of :data:`pnl_engine.config.VALID_CATEGORY2`
- ``FxRate`` — per-deal ``Optimus Reporting FxRate`` (CHF per deal-ccy unit);
  engine re-applies this for forecast days per the FX memory.
- ``IAS Book`` — ``BOOK1`` / ``BOOK2`` (existing canonical, now sourced from
  the sheet name via :data:`pnl_engine.config.SHEET_TO_BOOK`).

For the folder layout, :func:`discover_bank_native_input` walks the
``YYYYPP/YYYYMMDDVV`` tree and returns the triple of (pnl, wirp, schedule)
paths for a given position date (latest variant wins).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from cockpit.config import (
    SUPPORTED_CURRENCIES,
    _CIB_COUNTERPARTIES,
    _WM_COUNTERPARTIES,
)
from pnl_engine.config import (
    FLOAT_NAME_TO_WASP,
    SHEET_TO_BOOK,
    VALID_CATEGORY2_BOOK1,
    VALID_CATEGORY2_BOOK2,
    VALID_DIRECTIONS,
)

# Per-book Category2 lookup for sheet-aware validation
_CATEGORY2_BY_BOOK: dict[str, set[str]] = {
    "BOOK1": VALID_CATEGORY2_BOOK1,
    "BOOK2": VALID_CATEGORY2_BOOK2,
}

# Bare RFR short names → WASP overnight index (subset of FLOAT_NAME_TO_WASP)
_WIRP_BARE_INDICES: tuple[str, ...] = ("SARON", "ESTR", "SOFR", "SONIA")
_WIRP_SHORT_TO_WASP: dict[str, str] = {k: FLOAT_NAME_TO_WASP[k] for k in _WIRP_BARE_INDICES}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column rename map — bank-native → canonical
# ---------------------------------------------------------------------------

_DEAL_RENAME: dict[str, str] = {
    "Deal ID": "Dealid",
    "Deal Currency": "Currency",
    "@Direction": "Direction",
    "Source Product Code": "Product",
    "Calculated initial Amount (Measure)": "Amount",
    "Optimus Reporting FxRate": "FxRate",
    "Nominal Interest Rate": "Clientrate",
    "@EqOISRate2": "EqOisRate",
    "Yield To Maturity": "YTM",
    "CoC/SellDown Carry Rate": "CocRate",
    "Credit Spread FIFO": "Spread",
    "Rate Reference": "Floating Rates Short Name",
    "Trade Date": "Tradedate",
    "Value Date": "Valuedate",
    "Maturity Date": "Maturitydate",
    "Rate Start Date": "last_fixing_date",
    "Rate End Date": "next_fixing_date",
    "CRDS Counterparty Code": "Counterparty",
    "@Category": "Category",
    "@Category2": "Category2",
    "ISIN Code": "ISIN",
    "@indexation": "Indexation",
    "@NbBasis": "NbBasis",
    "@Nb_Day_Adj": "Nb_Day_Adj",
    "@Amount_CHF": "Amount_CHF_source",       # audit-only, not used in math
    "@PnL_Acc_Estim_Unadj": "PnL_Acc_Unadj",
    "@PnL_Acc_Estim_Adj": "PnL_Acc_Adj",
    "@PnL_CoC_Estim_Unadj": "PnL_CoC_Unadj",
    "@PnL_CoC_Estim_Adj": "PnL_CoC_Adj",
    # Both realised columns target the same canonical name; per-sheet collision
    # is impossible (each sheet has only one of the two).
    "[Daily] PnL IAS - ORC": "PnL_Realized",
    "[Daily] PnL MTM": "PnL_Realized",
    "Portfolio Short Name": "Portfolio",
    "Folder Short Name": "Folder",
}


# ---------------------------------------------------------------------------
# Daily P&L workbook parser (both sheets)
# ---------------------------------------------------------------------------

_HEADER_ANCHORS: tuple[str, ...] = ("Deal ID", "Position Date", "@KeyID")

# Real bank exports use shorter Product codes than the engine's canonical set.
_PRODUCT_RENAME: dict[str, str] = {
    "LD": "IAM/LD",
}

# Real bank exports use plural / mixed-case Category2 spellings.
_CATEGORY2_RENAME: dict[str, str] = {
    "OPP_Bonds_ASW": "OPP_Bond_ASW",
    "OPP_Bonds_nASW": "OPP_Bond_nASW",
    "OPP_Cash": "OPP_CASH",
}

# Threshold above which a "rate" column is interpreted as percent and divided
# by 100. Genuine decimal rates can't exceed 1.0 (= 100%), so any column whose
# max absolute value clears 1.0 must be percent-encoded.
_PERCENT_DETECT_THRESHOLD: float = 1.0
# Rate columns the bank exports as percent (4.875 = 4.875%).
_PERCENT_RATE_COLUMNS: tuple[str, ...] = ("Clientrate", "EqOisRate", "YTM", "CocRate")
# Credit Spread FIFO is exported in basis points (8.0 = 8.0 bps = 0.0008).
_BPS_RATE_COLUMNS: tuple[str, ...] = ("Spread",)
_RATE_COLUMNS: tuple[str, ...] = _PERCENT_RATE_COLUMNS + _BPS_RATE_COLUMNS


def _read_sheet_with_anchored_header(
    xl: pd.ExcelFile, sheet_name: str, max_scan: int = 5,
) -> pd.DataFrame:
    """Read a sheet, locating the header by anchor columns within the first rows.

    Why: bank exports sometimes prepend a blank/title row above the column
    names, while test fixtures keep headers on row 0. Reads once with
    header=None and promotes the detected row in-memory.
    """
    raw = pd.read_excel(xl, sheet_name=sheet_name, header=None)
    if raw.empty:
        return raw
    header_row = 0
    for i in range(min(max_scan, len(raw))):
        row_vals = {str(v).strip() for v in raw.iloc[i].tolist() if pd.notna(v)}
        if any(anchor in row_vals for anchor in _HEADER_ANCHORS):
            header_row = i
            break
    promoted = raw.iloc[header_row + 1:].reset_index(drop=True)
    promoted.columns = raw.iloc[header_row].astype(str)
    return promoted


def _parse_one_sheet(xl: pd.ExcelFile, sheet_name: str, book: str,
                     date_run: pd.Timestamp | None) -> pd.DataFrame:
    """Parse a single Book{1,2} sheet into canonical shape."""
    raw = _read_sheet_with_anchored_header(xl, sheet_name)
    rename = {k: v for k, v in _DEAL_RENAME.items() if k in raw.columns}
    df = raw.rename(columns=rename)

    if "Position Date" in df.columns:
        df["Position Date"] = pd.to_datetime(df["Position Date"], errors="coerce")
        if date_run is not None:
            target = pd.Timestamp(date_run).normalize()
            df = df[df["Position Date"].dt.normalize() == target].copy()
            if df.empty:
                logger.warning("bank_native(%s): no rows for position date %s",
                               sheet_name, target.date())
                df["IAS Book"] = book
                return df

    if "Dealid" not in df.columns:
        raise ValueError(f"bank_native({sheet_name}): missing required column 'Deal ID'")

    # Dealid kept as string — bank IDs mix digits with hyphen suffixes (e.g. "300001-M")
    df["Dealid"] = df["Dealid"].astype(str).str.strip()
    df = df[df["Dealid"].ne("")].copy()

    if "Direction" in df.columns:
        df["Direction"] = df["Direction"].astype(str).str.strip().str[0]
        bad_dir = ~df["Direction"].isin(VALID_DIRECTIONS)
        if bad_dir.any():
            logger.warning("bank_native(%s): %d rows with invalid Direction (dropped)",
                           sheet_name, int(bad_dir.sum()))
            df = df[~bad_dir].copy()

    # Set before any early return so concat always sees the column
    df["IAS Book"] = book

    if "Category2" in df.columns:
        valid = _CATEGORY2_BY_BOOK[book]
        df["Category2"] = df["Category2"].astype(str).str.strip().replace(_CATEGORY2_RENAME)
        unknown = ~df["Category2"].isin(valid)
        if unknown.any():
            logger.warning("bank_native(%s): %d rows with unknown @Category2 (kept as-is): %s",
                           sheet_name, int(unknown.sum()),
                           sorted(df.loc[unknown, "Category2"].unique())[:5])

    if "Product" in df.columns:
        df["Product"] = df["Product"].astype(str).str.strip().replace(_PRODUCT_RENAME)

    if "Currency" in df.columns:
        df["Currency"] = df["Currency"].astype(str).str.strip().str.upper()
        n_before = len(df)
        df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()
        n_dropped = n_before - len(df)
        if n_dropped > 0:
            logger.info("bank_native(%s): dropped %d rows with unsupported currency",
                        sheet_name, n_dropped)

    if "Counterparty" in df.columns:
        df["Périmètre TOTAL"] = np.where(
            df["Counterparty"].isin(_WM_COUNTERPARTIES), "WM",
            np.where(df["Counterparty"].isin(_CIB_COUNTERPARTIES), "CIB", "CC"),
        )
    else:
        df["Périmètre TOTAL"] = "CC"

    for col in (*_RATE_COLUMNS, "FxRate"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    # Real K+EUR exports store rates as percent and spreads as bps; fixtures
    # are decimal. Detect per-column: |x| > 1.0 means the value is encoded.
    for col in _PERCENT_RATE_COLUMNS:
        if col in df.columns and df[col].abs().max() > _PERCENT_DETECT_THRESHOLD:
            logger.info("bank_native(%s): %s percent-encoded, rescaling /100", sheet_name, col)
            df[col] = df[col] / 100.0
    for col in _BPS_RATE_COLUMNS:
        if col in df.columns and df[col].abs().max() > _PERCENT_DETECT_THRESHOLD:
            logger.info("bank_native(%s): %s bps-encoded, rescaling /10000", sheet_name, col)
            df[col] = df[col] / 10000.0

    for col in ["Maturitydate", "Valuedate", "Tradedate",
                "last_fixing_date", "next_fixing_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", dayfirst=False)

    if "Maturitydate" in df.columns:
        bad_mat = df["Maturitydate"].isna()
        if bad_mat.any():
            logger.warning("bank_native(%s): %d rows with invalid Maturity Date (dropped)",
                           sheet_name, int(bad_mat.sum()))
            df = df[~bad_mat].copy()

    # Must run before current_fixing_rate so NaN→"" lets the empty-check work
    if "Floating Rates Short Name" in df.columns:
        df["Floating Rates Short Name"] = (
            df["Floating Rates Short Name"].fillna("").astype(str).str.strip()
        )
        bad_idx = df["Floating Rates Short Name"].ne("") & ~df["Floating Rates Short Name"].isin(FLOAT_NAME_TO_WASP)
        if bad_idx.any():
            logger.warning("bank_native(%s): %d rows with unknown Rate Reference: %s",
                           sheet_name, int(bad_idx.sum()),
                           sorted(df.loc[bad_idx, "Floating Rates Short Name"].unique())[:5])
    else:
        df["Floating Rates Short Name"] = ""

    is_float = df["Floating Rates Short Name"].ne("")
    df["is_floating"] = is_float
    df["ref_index"] = np.where(
        is_float,
        df["Floating Rates Short Name"].map(FLOAT_NAME_TO_WASP).fillna(""),
        "",
    )

    if "Clientrate" in df.columns:
        df["current_fixing_rate"] = np.where(is_float, df["Clientrate"], np.nan)

    return df.reset_index(drop=True)


def parse_bank_native_deals(
    path: Path,
    date_run: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Parse the bank-native daily P&L workbook into a unified canonical deals DataFrame.

    Reads both ``Book1_Daily_PnL`` and ``Book2_Daily_PnL`` sheets, tags each
    row with ``IAS Book`` via :data:`SHEET_TO_BOOK`, and concatenates. The
    resulting DataFrame has the same canonical column names as
    :func:`parse_deals` (``Dealid``, ``Product``, ``Currency``, ``Direction``,
    ``Amount``, ``Clientrate``, ``Maturitydate`` …) plus the three
    bank-native additions ``Category2``, ``FxRate``, and retained reconciliation
    columns (``PnL_Realized``, ``PnL_Acc_Adj``, …).
    """
    xl = pd.ExcelFile(path, engine="openpyxl")
    frames: list[pd.DataFrame] = []
    for sheet_name, book in SHEET_TO_BOOK.items():
        if sheet_name not in xl.sheet_names:
            logger.warning("bank_native: expected sheet '%s' not in %s", sheet_name, path.name)
            continue
        frames.append(_parse_one_sheet(xl, sheet_name, book, date_run))

    if not frames:
        raise ValueError(f"bank_native: no Book1/Book2 sheets in {path}")

    merged = pd.concat(frames, ignore_index=True, sort=False)
    counts = merged["IAS Book"].value_counts().to_dict() if "IAS Book" in merged.columns else {}
    logger.info("bank_native: %d deals loaded (%s)", len(merged), counts)
    return merged


# ---------------------------------------------------------------------------
# Rate schedule (echeancier) parser
# ---------------------------------------------------------------------------

_MONTH_COL_RE = re.compile(r"^\d{4}/\d{2}$")


def _month_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if isinstance(c, str) and _MONTH_COL_RE.match(c)]


def parse_bank_native_schedule(path: Path) -> pd.DataFrame:
    """Parse the bank-native wide rate schedule → canonical schedule DataFrame.

    Reads sheet ``Operation_Propres EoM``, normalises column names to the
    ``parse_schedule()`` shape (``Dealid``, ``Direction``, ``Currency``,
    ``Rate Type`` + ``YYYY/MM`` monthly balance columns).
    """
    df = pd.read_excel(path, sheet_name="Operation_Propres EoM", engine="openpyxl")

    rename = {
        "Deal Number KND": "Dealid",
        "Deal Currency": "Currency",
        "Rate Type": "Rate Type",
        "Rate index - level 1": "Floating Rates Short Name",
        "Maturity Date": "Maturitydate",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "Dealid" not in df.columns:
        raise ValueError("bank_native schedule: missing 'Deal Number KND' column")
    df["Dealid"] = df["Dealid"].astype(str).str.strip()
    df = df[df["Dealid"].ne("")].copy()

    # Direction derivation — the schedule sheet has 'Asset / Liability' not Direction.
    # Map per DIRECTION_SIDE: asset (L/B/S) negative, liability (D) positive.
    # Bond identification: Chart of account lines with BND → B; otherwise
    # assets default to L and liabilities to D (engine joins back to deals
    # workbook on Dealid anyway, so this is a best-effort tag).
    if "Asset / Liability" in df.columns and "Direction" not in df.columns:
        al = df["Asset / Liability"].astype(str).str.strip().str.lower()
        is_asset = al.eq("asset")
        # Best-effort bond flag from chart of account levels
        is_bond = pd.Series(False, index=df.index)
        for lvl in ["Chart of account - level 2", "Chart of account - level 3"]:
            if lvl in df.columns:
                is_bond |= df[lvl].astype(str).str.upper().str.contains("BND|BOND", na=False, regex=True)
        df["Direction"] = np.where(
            is_asset,
            np.where(is_bond, "B", "L"),
            "D",
        )

    # Currency filter
    if "Currency" in df.columns:
        df["Currency"] = df["Currency"].astype(str).str.strip().str.upper()
        df = df[df["Currency"].isin(SUPPORTED_CURRENCIES)].copy()

    if "Maturitydate" in df.columns:
        df["Maturitydate"] = pd.to_datetime(df["Maturitydate"], errors="coerce", dayfirst=False)

    # Validate monthly columns exist
    if not _month_columns(df):
        logger.warning("bank_native schedule: no YYYY/MM balance columns found in %s", path.name)

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# WIRP parser
# ---------------------------------------------------------------------------

def parse_bank_native_wirp(path: Path) -> pd.DataFrame:
    """Parse the bank-native WIRP workbook → long DataFrame keyed by WASP index.

    Maps bare short names (SARON/ESTR/SOFR/SONIA) to the WASP index names used
    throughout the P&L engine (CHFSON/EUREST/USSOFR/GBPOIS).
    """
    df = pd.read_excel(path, sheet_name="WIRP", engine="openpyxl")

    rename = {"Meeting Date": "Meeting"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    if "Indice" not in df.columns:
        raise ValueError("bank_native WIRP: missing required column 'Indice'")

    df["Indice"] = df["Indice"].astype(str).str.strip().str.upper()
    unknown = ~df["Indice"].isin(_WIRP_SHORT_TO_WASP)
    if unknown.any():
        logger.warning("bank_native WIRP: %d rows with unknown Indice (dropped): %s",
                       int(unknown.sum()),
                       sorted(df.loc[unknown, "Indice"].unique()))
        df = df[~unknown].copy()
    df["Indice"] = df["Indice"].map(_WIRP_SHORT_TO_WASP)

    df["Meeting"] = pd.to_datetime(df["Meeting"], errors="coerce", dayfirst=False)
    df = df.dropna(subset=["Meeting"])

    if "Rate" in df.columns:
        df["Rate"] = pd.to_numeric(df["Rate"], errors="coerce")
        extreme = df["Rate"].abs() > 0.20
        if extreme.any():
            logger.warning("bank_native WIRP: %d rows with |rate| > 20%% — are rates in decimal?",
                           int(extreme.sum()))

    return df.sort_values(["Indice", "Meeting"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Folder discovery
# ---------------------------------------------------------------------------

class BankNativeInputs(NamedTuple):
    """The three input file paths for one position date."""
    pnl_workbook: Path
    wirp: Path
    rate_schedule: Path
    position_date: pd.Timestamp
    variant: str           # the trailing 2-digit suffix from YYYYMMDDVV
    day_dir: Path          # the full YYYYMMDDVV directory


_YEAR_PERIOD_RE = re.compile(r"^\d{4}\d{2}$")     # YYYYPP
_DAY_VARIANT_RE = re.compile(r"^(\d{8})(\d{2})$")  # YYYYMMDD + VV


def discover_bank_native_input(
    root: Path,
    position_date: pd.Timestamp | None = None,
) -> BankNativeInputs:
    """Discover the input triple for a position date from a YYYYPP/YYYYMMDDVV tree.

    Parameters
    ----------
    root
        Top-level directory containing ``YYYYPP/`` subdirectories.
    position_date
        If None, picks the latest-dated folder found. Otherwise finds the
        folder for that date (latest variant wins when multiple exist).
    """
    if not root.is_dir():
        raise FileNotFoundError(f"bank_native root not found: {root}")

    # Walk to collect (date, variant, dir) tuples
    candidates: list[tuple[pd.Timestamp, str, Path]] = []
    for year_period in sorted(root.iterdir()):
        if not year_period.is_dir() or not _YEAR_PERIOD_RE.match(year_period.name):
            continue
        for day_dir in sorted(year_period.iterdir()):
            if not day_dir.is_dir():
                continue
            m = _DAY_VARIANT_RE.match(day_dir.name)
            if not m:
                continue
            date_str, variant = m.groups()
            ts = pd.to_datetime(date_str, format="%Y%m%d", errors="coerce")
            if pd.isna(ts):
                continue
            candidates.append((ts, variant, day_dir))

    if not candidates:
        raise FileNotFoundError(f"bank_native: no YYYYPP/YYYYMMDDVV folders under {root}")

    if position_date is not None:
        target = pd.Timestamp(position_date).normalize()
        matches = [c for c in candidates if c[0] == target]
        if not matches:
            raise FileNotFoundError(
                f"bank_native: no folder for position date {target.date()} under {root}")
        # Latest variant wins
        ts, variant, day_dir = max(matches, key=lambda c: c[1])
    else:
        # Latest date, then latest variant
        ts, variant, day_dir = max(candidates, key=lambda c: (c[0], c[1]))

    date_str = ts.strftime("%Y%m%d")

    # Locate the three files
    pnl_candidates = list(day_dir.glob(f"*Daily Rate PnL*_{date_str}.xlsx"))
    wirp_candidates = list(day_dir.glob(f"{date_str}_WIRP.xlsx"))
    rs_candidates = list(day_dir.glob(f"{date_str}_rate_schedule.xlsx"))

    def _exactly_one(lst: list[Path], label: str) -> Path:
        if not lst:
            raise FileNotFoundError(f"bank_native: no {label} file in {day_dir}")
        if len(lst) > 1:
            logger.warning("bank_native: multiple %s files in %s, picking %s",
                           label, day_dir, lst[0].name)
        return lst[0]

    return BankNativeInputs(
        pnl_workbook=_exactly_one(pnl_candidates, "daily P&L workbook"),
        wirp=_exactly_one(wirp_candidates, "WIRP"),
        rate_schedule=_exactly_one(rs_candidates, "rate_schedule"),
        position_date=ts,
        variant=variant,
        day_dir=day_dir,
    )
