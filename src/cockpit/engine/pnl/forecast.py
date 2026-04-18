"""ForecastRatePnL — cockpit wrapper around pnl_engine.PnlEngine.

Adds file I/O (load_data, export_files) and dill serialization
(save_pnl, load_pnl, compare_pnl) on top of the standalone engine.

Usage::

    from cockpit.engine.pnl.forecast import ForecastRatePnL, compare_pnl, save_pnl, load_pnl

    pnl = ForecastRatePnL(
        dateRun=datetime(2026, 3, 26),
        dateRates=datetime(2026, 3, 26),
        export=True,
    )
    pnl.pnlAll      # wide DataFrame (months as columns)
    pnl.pnlAllS     # stacked long DataFrame

    # Re-run with different rates/shock without reloading data:
    pnl.update_pnl(dateRates=datetime(2026, 3, 27), Shock="50")

Shock convention
----------------
The ``Shock`` parameter is in **basis points** and is passed through to
WASP ``LoadMarketRamp`` via ``YCParallelShift``.
E.g. ``Shock=50`` means a +0.50% parallel shift of the yield curve.

dateRun vs dateRates
--------------------
- ``dateRun``: stock / run reference date — controls which deal data is loaded
  and which input files are resolved.
- ``dateRates``: market date for loading forward curves via WASP. Before this
  date, rates are realized; after, rates are forwards. Defaults to ``dateRun``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

import dill
import numpy as np
import pandas as pd

from pnl_engine import config as pnl_cfg
from pnl_engine.config import FUNDING_SOURCE
from pnl_engine.orchestrator import PnlEngine
from cockpit.export.synthesis import build_synthesis, export_synthesis_to_excel
from cockpit.data.parsers import (
    BankNativeInputs,
    discover_bank_native_input,
    parse_bank_native_deals,
    parse_bank_native_schedule,
    parse_bank_native_wirp,
    parse_book,
    parse_deals,
    parse_schedule,
    parse_wirp_ideal,
)

logger = logging.getLogger(__name__)

DEFAULT_PNL_BASE = os.environ.get(
    "PNL_OIS_BASE",
    r"J:\ALM\ALM\06. Analyses et projets\2024_OIS",
)


class ForecastRatePnL:
    """Forecast economic Rate P&L engine — cockpit wrapper with file I/O.

    Delegates all computation to ``pnl_engine.PnlEngine``. This class adds:
    - File discovery and parsing (load_data)
    - Excel export and dill serialization
    """

    def __init__(
        self,
        dateRun: datetime,
        dateRates: Optional[datetime] = None,
        export: bool = True,
        *,
        base_dir: Optional[Union[str, Path]] = None,
        input_dir: Optional[Union[str, Path]] = None,
        output_dir: Optional[Union[str, Path]] = None,
        funding_source: str = FUNDING_SOURCE,
        auto_run: bool = True,
    ):
        self.dateRun = dateRun
        self.date_ref_day = self.dateRun.strftime("%Y%m%d")
        self.date_ref_month = self.dateRun.strftime("%Y%m")
        self.dateRates = dateRates if dateRates is not None else self.dateRun

        root = Path(base_dir) if base_dir is not None else Path(DEFAULT_PNL_BASE)
        self.input_dir = (
            Path(input_dir)
            if input_dir is not None
            else root / self.date_ref_month / self.date_ref_day
        )
        self.output = Path(
            output_dir
            if output_dir is not None
            else root / self.date_ref_month / "output"
        )

        self._funding_source = funding_source

        # Public result attributes (populated by run)
        self.pnlData: Optional[pd.DataFrame] = None
        self.scheduleData: Optional[pd.DataFrame] = None
        self.scheduleDataMTM: Optional[pd.DataFrame] = None
        self.wirpData: Optional[pd.DataFrame] = None
        self.irsStock: Optional[pd.DataFrame] = None
        self.book2NonIrs: pd.DataFrame = pd.DataFrame()
        self.fwdOIS0: Optional[pd.DataFrame] = None
        self.fwdWIRP: Optional[pd.DataFrame] = None
        self.pnlAll: Optional[pd.DataFrame] = None
        self.pnlAllS: Optional[pd.DataFrame] = None
        self.pnl_by_deal: Optional[pd.DataFrame] = None

        # Internal engine instance
        self._engine: Optional[PnlEngine] = None

        if auto_run:
            # Honor the configured SHOCKS list — CLI callers override via
            # pnl_engine.config.SHOCKS, and the previous hardcoded ["50", "0"]
            # silently dropped the WIRP shock from downstream dashboards.
            self.run(shocks=list(pnl_cfg.SHOCKS), export=export)

    def load_data(self) -> None:
        """Load deal data, schedule, WIRP, and IRS stock from Excel files.

        Supports three input layouts (tried in order):
        - **Bank-native format**: triple of ``*Daily Rate PnL*_YYYYMMDD.xlsx``,
          ``YYYYMMDD_WIRP.xlsx``, ``YYYYMMDD_rate_schedule.xlsx`` — either
          directly in ``input_dir`` or under a ``YYYYPP/YYYYMMDDVV/`` tree.
          Applies per-deal FX re-apply via ``Optimus Reporting FxRate``.
        - **K+EUR format**: ``*Daily Rate PnL*`` (Book1 + Book2 sheets, IRS-MTM from Folder Short Name)
        - **Ideal format**: ``*deals*`` (unified BOOK1+BOOK2), ``rate_schedule.xlsx``, ``wirp.xlsx``
        """
        bank_native_inputs = self._detect_bank_native_input()
        if bank_native_inputs is not None:
            self._load_bank_native(bank_native_inputs)
            logger.info("load_data Done (bank-native: %d deals, %d schedule rows)",
                        len(self.pnlData), len(self.scheduleData))
            return

        book_files = list(self.input_dir.glob("*Daily Rate PnL*"))
        deals_files = list(self.input_dir.glob("*deals*"))

        if book_files:
            book_file = book_files[0]
            date_run_ts = pd.Timestamp(self.dateRun)
            book1 = parse_book(book_file, date_run_ts, "Book1")
            book2 = parse_book(book_file, date_run_ts, "Book2")
            self.pnlData = pd.concat([book1, book2], ignore_index=True)
            self.irsStock = self._irs_stock_from_pnl_data()
            logger.info(
                "Loaded K+EUR format: %s (Book1=%d, Book2=%d, IRS-MTM=%d)",
                book_file.name, len(book1), len(book2), len(self.irsStock),
            )
        elif deals_files:
            all_deals = parse_deals(deals_files[0])
            self.pnlData, self.irsStock = self._split_deals_by_book(all_deals)
            logger.info("Loaded unified deals file: %s (BOOK1=%d, BOOK2=%d)",
                        deals_files[0].name, len(self.pnlData), len(self.irsStock))
        else:
            raise FileNotFoundError(f"No deal file found in {self.input_dir}")

        schedule_files = list(self.input_dir.glob("*rate_schedule*")) or list(self.input_dir.glob("*schedule*"))
        if not schedule_files:
            raise FileNotFoundError(f"No rate_schedule file found in {self.input_dir}")
        self.scheduleData = parse_schedule(schedule_files[0])

        wirp_files = list(self.input_dir.glob("*wirp*")) or list(self.input_dir.glob("*WIRP*"))
        if not wirp_files:
            raise FileNotFoundError(f"No WIRP file found in {self.input_dir}")
        self.wirpData = parse_wirp_ideal(wirp_files[0])

        self.scheduleDataMTM = pd.DataFrame()

        logger.info("load_data Done (%d deals, %d schedule rows)", len(self.pnlData), len(self.scheduleData))

    def _detect_bank_native_input(self) -> Optional[BankNativeInputs]:
        """Return a BankNativeInputs if the input_dir resolves to bank-native files.

        Two layouts are accepted:
        - ``input_dir`` is the day dir itself containing the three bank-native files
          (detected by presence of ``YYYYMMDD_rate_schedule.xlsx``, which is
          unique to the bank-native layout).
        - ``input_dir`` is the root of a ``YYYYPP/YYYYMMDDVV/`` tree.
        """
        date_str = pd.Timestamp(self.dateRun).strftime("%Y%m%d")

        rs_candidates = list(self.input_dir.glob(f"{date_str}_rate_schedule.xlsx"))
        wirp_candidates = list(self.input_dir.glob(f"{date_str}_WIRP.xlsx"))
        pnl_candidates = list(self.input_dir.glob(f"*Daily Rate PnL*_{date_str}.xlsx"))
        if rs_candidates and wirp_candidates and pnl_candidates:
            return BankNativeInputs(
                pnl_workbook=pnl_candidates[0],
                wirp=wirp_candidates[0],
                rate_schedule=rs_candidates[0],
                position_date=pd.Timestamp(self.dateRun).normalize(),
                variant="",
                day_dir=self.input_dir,
            )

        try:
            return discover_bank_native_input(self.input_dir, position_date=pd.Timestamp(self.dateRun))
        except FileNotFoundError:
            return None

    def _load_bank_native(self, inputs: BankNativeInputs) -> None:
        """Populate pnlData/scheduleData/wirpData/irsStock from the bank-native triple.

        FX re-apply (per memory rule): overwrite @Amount_CHF / Amount_CHF_source
        with nominal_ccy × Optimus Reporting FxRate so the forecast uses a single
        consistent FX snapshot across all 60 months. Book2 is split: IRS go to
        irsStock for the WASP MTM path; non-IRS Book2 (MTM bond/FVH legs) are
        set aside as ``book2NonIrs`` for Phase 3b.
        """
        deals = parse_bank_native_deals(inputs.pnl_workbook, date_run=pd.Timestamp(self.dateRun))
        self.scheduleData = parse_bank_native_schedule(inputs.rate_schedule)
        self.wirpData = parse_bank_native_wirp(inputs.wirp)
        self.scheduleDataMTM = pd.DataFrame()

        if "FxRate" in deals.columns:
            deals["Amount_CHF"] = deals["Amount"].astype(float) * deals["FxRate"].astype(float)

        book1 = deals[deals["IAS Book"] == "BOOK1"].copy().reset_index(drop=True)
        book2 = deals[deals["IAS Book"] == "BOOK2"].copy().reset_index(drop=True)

        self.pnlData = book1
        self.irsStock, self.book2NonIrs = self._split_book2_bank_native(book2)

        logger.info(
            "Bank-native: BOOK1=%d, BOOK2 IRS=%d, BOOK2 non-IRS=%d (deferred), schedule=%d",
            len(self.pnlData), len(self.irsStock), len(self.book2NonIrs),
            len(self.scheduleData),
        )

    @staticmethod
    def _split_book2_bank_native(book2: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Split Book2 deals: IRS → MTM stock (WASP path); non-IRS → deferred.

        Bank-native Book2 contains four @Category2 buckets: IRS_FVH, IRS_FVO
        (both IRS) plus OPP_Bond_ASW, OPR_FVH (MTM bond / hedge legs). The MTM
        bond legs need a different pricing path (Phase 3b); for now they are
        separated out and the engine sees only IRS Book2.
        """
        if book2.empty:
            return pd.DataFrame(), pd.DataFrame()

        is_irs = book2["Product"].isin({"IRS", "IRS-MTM"})
        irs = book2[is_irs].copy()
        non_irs = book2[~is_irs].copy()

        if irs.empty:
            return pd.DataFrame(), non_irs.reset_index(drop=True)

        irs_stock = irs.rename(columns={
            "Maturitydate": "Maturity Date",
            "Valuedate": "Value Date",
            "Strategy IAS": "Strategy (Agapes IAS)",
            "Currency": "Currency Code (ISO)",
            "Dealid": "Deal",
            "Floating Rates Short Name": "Index",
            "Clientrate": "Rate",
            "Amount": "Notional",
        })
        # Pay/Receive derived from Direction (L/B/S → RECEIVE fixed leg; D → PAY)
        if "Direction" in irs_stock.columns:
            irs_stock["Pay/Receive"] = np.where(
                irs_stock["Direction"].isin(["L", "B", "S"]), "RECEIVE", "PAY"
            )
            irs_stock["Buy / Sell"] = np.where(
                irs_stock["Pay/Receive"] == "RECEIVE", "Buy", "Sell"
            )
            irs_stock["Asset / Liabilities"] = np.where(
                irs_stock["Pay/Receive"] == "RECEIVE", "Actif", "Passif"
            )

        return irs_stock.reset_index(drop=True), non_irs.reset_index(drop=True)

    @staticmethod
    def _split_deals_by_book(all_deals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Split unified deals into BOOK1 (accrual) and BOOK2 (IRS stock for WASP MTM)."""
        if "IAS Book" not in all_deals.columns:
            return all_deals.copy(), pd.DataFrame()

        book1 = all_deals[all_deals["IAS Book"] == "BOOK1"].copy().reset_index(drop=True)
        book2_raw = all_deals[all_deals["IAS Book"] == "BOOK2"].copy()

        if book2_raw.empty:
            return book1, pd.DataFrame()

        irs_stock = book2_raw.rename(columns={
            "Maturitydate": "Maturity Date",
            "Valuedate": "Value Date",
            "Strategy IAS": "Strategy (Agapes IAS)",
            "Currency": "Currency Code (ISO)",
            "notional": "Notional",
            "pay_receive": "Pay/Receive",
            "Dealid": "Deal",
            "Floating Rates Short Name": "Index",
            "Clientrate": "Rate",
        })

        if "Pay/Receive" in irs_stock.columns:
            irs_stock["Buy / Sell"] = np.where(
                irs_stock["Pay/Receive"] == "RECEIVE", "Buy", "Sell"
            )
            irs_stock["Asset / Liabilities"] = np.where(
                irs_stock["Pay/Receive"] == "RECEIVE", "Actif", "Passif"
            )

        return book1, irs_stock.reset_index(drop=True)

    def _irs_stock_from_pnl_data(self) -> pd.DataFrame:
        """Extract IRS-MTM deals from pnlData for compute_book2_mtm."""
        mtm = self.pnlData[self.pnlData["Product"] == "IRS-MTM"].copy()
        if mtm.empty:
            return pd.DataFrame()

        # Derive Pay/Receive from Direction: L/B/S → RECEIVE, D → PAY
        if "Direction" in mtm.columns:
            mtm["Pay/Receive"] = np.where(
                mtm["Direction"].isin(["L", "B", "S"]), "RECEIVE", "PAY"
            )

        return mtm.reset_index(drop=True)

    def run(
        self,
        shocks: Optional[list[str]] = None,
        export: bool = False,
    ) -> None:
        """Execute the full pipeline: load data, build curves, compute all shocks."""
        if shocks is None:
            shocks = list(pnl_cfg.SHOCKS)

        self.load_data()

        # Create standalone engine with parsed data
        self._engine = PnlEngine(
            deals=self.pnlData,
            schedule=self.scheduleData,
            wirp=self.wirpData,
            irs_stock=self.irsStock,
            date_run=self.dateRun,
            date_rates=self.dateRates,
            funding_source=self._funding_source,
        )

        self.pnlAll = self._engine.run(shocks=shocks)
        self.pnlAllS = self._engine.pnlAllS
        self.pnl_by_deal = self._engine.pnl_by_deal
        self.fwdOIS0 = self._engine.fwdOIS0
        self.fwdWIRP = self._engine.fwdWIRP

        if export:
            self.export_files()

    def update_pnl(
        self,
        dateRates: Optional[datetime] = None,
        reload_data: bool = False,
        Shock: str = "0",
    ) -> pd.DataFrame:
        """Recompute P&L for a single shock and optional new rate date."""
        if dateRates is not None:
            self.dateRates = dateRates

        if reload_data or self._engine is None:
            self.load_data()
            self._engine = PnlEngine(
                deals=self.pnlData,
                schedule=self.scheduleData,
                wirp=self.wirpData,
                irs_stock=self.irsStock,
                date_run=self.dateRun,
                date_rates=self.dateRates,
                funding_source=self._funding_source,
            )
            self._engine._build_static_matrices()
            self._engine.fwdOIS0 = self._engine._load_ois_curves(shock="0")
            self._engine.fwdWIRP = overlay_wirp(self._engine.fwdOIS0, self.wirpData)

        return self._engine.update_pnl(dateRates=dateRates, Shock=Shock)

    def clear_fwd_cache(self) -> None:
        """Clear cached forward curves."""
        if self._engine is not None:
            self._engine.clear_fwd_cache()

    def pnl_stack(self) -> pd.DataFrame:
        """Long stacked view of ``pnlAll``."""
        if self._engine is not None:
            return self._engine.pnl_stack()
        return pd.DataFrame()

    def export_files(self) -> None:
        """Write main P&L workbook under ``output``.

        Sheets:
        - ``pnl{dateRates}``: aggregated portfolio P&L (wide format)
        - ``Deal PnL``: deal-level P&L detail (all shocks × months)

        For bank-native loads (``IAS Book`` + ``Category2`` on ``pnlData``),
        additionally writes ``{YYYYMM}_Daily_Forecast.xlsx`` with the
        ``Synthesis`` sheet.
        """
        out = Path(self.output)
        out.mkdir(parents=True, exist_ok=True)
        path = (
            out
            / f"stock_{self.dateRun.strftime('%Y%m%d')}_rates_{self.dateRates.strftime('%Y%m%d')}_pnl.xlsx"
        )
        with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
            self.pnlAll.to_excel(
                writer,
                sheet_name=f"pnl{self.dateRates.strftime('%Y%m%d')}",
                index=False,
            )
            if self.pnl_by_deal is not None and not self.pnl_by_deal.empty:
                deal_cols = [c for c in [
                    "Dealid", "Counterparty", "Currency", "Product", "Direction",
                    "Périmètre TOTAL", "Shock", "Month",
                    "Nominal", "Amount", "Maturitydate", "is_floating",
                    "Clientrate", "OISfwd", "RateRef",
                    "GrossCarry", "FundingCost_Simple", "PnL_Simple",
                    "FundingRate_Simple",
                    "FundingCost_Compounded", "PnL_Compounded",
                    "FundingRate_Compounded",
                ] if c in self.pnl_by_deal.columns]
                self.pnl_by_deal[deal_cols].to_excel(
                    writer, sheet_name="Deal PnL", index=False,
                )
        logger.info("export_files Done -> %s", path)

        self._export_synthesis(out)

    def _export_synthesis(self, out: Path) -> None:
        """Write the bank-native Synthesis workbook when Book/Category2 are present."""
        deals = self._taxonomy_frame()
        if deals is None or self.pnl_by_deal is None or self.pnl_by_deal.empty:
            return

        synthesis = build_synthesis(self.pnl_by_deal, deals, shock="0")
        if synthesis.empty:
            return
        export_synthesis_to_excel(
            synthesis, out / f"{self.date_ref_month}_Daily_Forecast.xlsx"
        )

    def _taxonomy_frame(self) -> Optional[pd.DataFrame]:
        """Assemble the Dealid → (IAS Book, Category2) lookup from loaded data.

        Returns None when the load path was not bank-native (no Category2).
        """
        frames: list[pd.DataFrame] = []
        for df in (self.pnlData, self.book2NonIrs):
            if df is None or df.empty:
                continue
            if {"Dealid", "IAS Book", "Category2"}.issubset(df.columns):
                frames.append(df[["Dealid", "IAS Book", "Category2"]])

        irs = self.irsStock
        if irs is not None and not irs.empty and "Category2" in irs.columns:
            dealid_col = "Deal" if "Deal" in irs.columns else "Dealid"
            if dealid_col in irs.columns and "IAS Book" in irs.columns:
                frames.append(
                    irs[[dealid_col, "IAS Book", "Category2"]].rename(columns={dealid_col: "Dealid"})
                )

        if not frames:
            return None
        return pd.concat(frames, ignore_index=True).drop_duplicates(subset=["Dealid"])


# Need overlay_wirp for update_pnl reload path
from pnl_engine.curves import overlay_wirp  # noqa: E402


# ---------------------------------------------------------------------------
# Module-level serialization and comparison (aligned with pnl.py)
# ---------------------------------------------------------------------------

def save_pnl(pnl: ForecastRatePnL) -> Path:
    """Pickle ``pnl`` under ``output`` as ``{dateRates}_pnl.pkl``. Returns the file path.

    Security: ``dill.load`` is equivalent to unpickling; only load from trusted paths.
    """
    out = Path(pnl.output)
    out.mkdir(parents=True, exist_ok=True)
    file_name = out / f"{pnl.dateRates.strftime('%Y%m%d')}_pnl.pkl"
    with open(file_name, "wb") as f:
        dill.dump(pnl, f)
    logger.info("save_pnl Done -> %s", file_name)
    return file_name


def load_pnl(infile: Union[str, Path]) -> ForecastRatePnL:
    """Load a ``ForecastRatePnL`` from a ``dill`` file. Trusted sources only."""
    path = Path(infile)
    with open(path, "rb") as f:
        loaded = dill.load(f)
    logger.info("load_pnl Done <- %s", path)
    return loaded


def compare_pnl(
    new_pnl: ForecastRatePnL,
    prev_pnl: ForecastRatePnL,
    output_path: Optional[Union[str, Path]] = None,
) -> pd.DataFrame:
    """Compare stacked P&L from two runs (outer join, delta, wide pivot by month).

    Aligned with pnl.py ``compare_pnl``: produces wide format with
    Level (Value_new / Value_prev / Delta) and Level_date columns.
    Writes comparison workbook under ``new_pnl.output``.
    """
    # 1. Outer join on MultiIndex
    comp = pd.merge(
        new_pnl.pnlAllS,
        prev_pnl.pnlAllS,
        left_index=True,
        right_index=True,
        how="outer",
        suffixes=("_new", "_prev"),
    )
    comp["Value_new"] = comp["Value_new"].fillna(0)
    comp["Value_prev"] = comp["Value_prev"].fillna(0)
    comp["Delta"] = comp["Value_new"] - comp["Value_prev"]
    comp = comp.reset_index()

    # 2. Melt Value_new / Value_prev / Delta into Level column
    value_cols = ["Value_new", "Value_prev", "Delta"]
    id_vars = [c for c in comp.columns if c not in value_cols]
    comp = comp.melt(
        id_vars=id_vars,
        value_vars=value_cols,
        var_name="Level",
        value_name="Value",
    )

    # 3. Pivot months to columns (wide format)
    pivot_idx = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                 "Direction", "Shock", "Indice", "PnL_Type", "Level"]
    present_idx = [c for c in pivot_idx if c in comp.columns]

    if "Month" in comp.columns:
        wide = pd.pivot_table(
            comp,
            values="Value",
            index=present_idx,
            columns="Month",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        if isinstance(wide.columns, pd.MultiIndex):
            wide.columns = [c[0] if c[1] == "" else c[1] for c in wide.columns]
    else:
        wide = comp

    # 4. Add Level_date (human-readable date string per Level)
    wide["Level_date"] = np.where(
        wide["Level"] == "Value_new",
        new_pnl.dateRates.strftime("%Y%m%d"),
        np.where(
            wide["Level"] == "Value_prev",
            prev_pnl.dateRates.strftime("%Y%m%d"),
            f"{new_pnl.dateRates.strftime('%Y%m%d')} vs {prev_pnl.dateRates.strftime('%Y%m%d')}",
        ),
    )
    # Insert Level_date after Level
    cols = list(wide.columns)
    cols.remove("Level_date")
    level_pos = cols.index("Level") + 1 if "Level" in cols else len(cols)
    cols.insert(level_pos, "Level_date")
    wide = wide[cols]

    # 5. Write Excel
    if output_path is None:
        output_path = (
            Path(new_pnl.output)
            / f"pnl_comp_{new_pnl.dateRates.strftime('%Y%m%d')}_vs_{prev_pnl.dateRates.strftime('%Y%m%d')}.xlsx"
        )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wide.to_excel(output_path, index=False, engine="openpyxl")
    logger.info("compare_pnl Done -> %s", output_path)

    return wide
