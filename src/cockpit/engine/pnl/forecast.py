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

from pnl_engine.config import FUNDING_SOURCE
from pnl_engine.orchestrator import PnlEngine
from cockpit.data.parsers import (
    parse_deals,
    parse_echeancier,
    parse_irs_stock,
    parse_mtd,
    parse_wirp,
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
    - Legacy MTD/IRS format support
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
        self.fwdOIS0: Optional[pd.DataFrame] = None
        self.fwdWIRP: Optional[pd.DataFrame] = None
        self.pnlAll: Optional[pd.DataFrame] = None
        self.pnlAllS: Optional[pd.DataFrame] = None
        self.pnl_by_deal: Optional[pd.DataFrame] = None

        # Internal engine instance
        self._engine: Optional[PnlEngine] = None

        self.run(shocks=["50", "0"], export=export)

    def load_data(self) -> None:
        """Load deal data, schedule, WIRP, and IRS stock from Excel files.

        Supports two input layouts:
        - **Ideal format**: ``deals.xlsx`` (unified BOOK1+BOOK2), ``rate_schedule.xlsx``, ``wirp.xlsx``
        - **Legacy format**: ``*MTD*``, ``*Echeancier*``, ``*WIRP*``, ``*IRS*`` (separate files)

        Ideal format is tried first; falls back to legacy if no ``*deals*`` file found.
        """
        # --- Deals: try unified deals file, fall back to legacy MTD + IRS ---
        deals_files = list(self.input_dir.glob("*deals*"))
        if deals_files:
            all_deals = parse_deals(deals_files[0])
            self.pnlData, self.irsStock = self._split_deals_by_book(all_deals)
            logger.info("Loaded unified deals file: %s (BOOK1=%d, BOOK2=%d)",
                        deals_files[0].name, len(self.pnlData), len(self.irsStock))
        else:
            mtd_file = next(self.input_dir.glob("*MTD Standard Liquidity PnL Report*"))
            irs_file = next(self.input_dir.glob("*IRS*"))
            self.pnlData = parse_mtd(mtd_file)
            self.irsStock = parse_irs_stock(irs_file)

        # --- Schedule ---
        schedule_files = list(self.input_dir.glob("*rate_schedule*")) or list(self.input_dir.glob("*schedule*")) or list(self.input_dir.glob("*Echeancier*"))
        echeancier_file = schedule_files[0] if schedule_files else next(self.input_dir.glob("*Echeancier*"))
        self.scheduleData = parse_echeancier(echeancier_file)

        # --- WIRP ---
        wirp_files = list(self.input_dir.glob("*wirp*")) or list(self.input_dir.glob("*WIRP*"))
        wirp_file = wirp_files[0] if wirp_files else next(self.input_dir.glob("*WIRP*"))
        self.wirpData = parse_wirp(wirp_file)

        # Filter TMSWBFIGE folder for IRS-MTM deals (legacy schedule only)
        if "Folder" in self.scheduleData.columns:
            self.scheduleDataMTM = self.scheduleData[
                self.scheduleData["Folder"].isin(["TMSWBFIGE"])
            ]
            self._append_mtm_from_schedule()
        else:
            self.scheduleDataMTM = pd.DataFrame()
            if not deals_files:
                logger.warning("Folder column not found in Echeancier — skipping MTM schedule append")

        logger.info("load_data Done (%d deals, %d schedule rows)", len(self.pnlData), len(self.scheduleData))

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

    def _append_mtm_from_schedule(self) -> None:
        """Append IRS-MTM deals from TMSWBFIGE schedule rows missing in conso."""
        if self.scheduleDataMTM is None or self.scheduleDataMTM.empty:
            return

        col_map = {
            "Situation Date": "Mark To Market Date",
            "Deal currency": "Currency",
            "Trade Date": "Tradedate",
            "Value Date": "Valuedate",
            "Maturity Date": "Maturitydate",
        }
        passthrough = ["Dealid", "Direction", "Amount", "Rate"]

        available = [c for c in list(col_map) + passthrough if c in self.scheduleDataMTM.columns]
        mtm = self.scheduleDataMTM[available].rename(columns=col_map).copy()

        if "Rate" in mtm.columns:
            mtm["Clientrate"] = mtm.pop("Rate") / 100

        mtm["Product2BuyBack"] = "IRS-MTM"
        mtm["Product"] = "IRS"
        mtm["Périmètre TOTAL"] = "CC"
        mtm = mtm.reindex(columns=self.pnlData.columns)

        self.pnlData = pd.concat([self.pnlData, mtm], ignore_index=True)
        logger.info("Appended %d IRS-MTM rows from TMSWBFIGE schedule", len(mtm))

    def run(
        self,
        shocks: Optional[list[str]] = None,
        export: bool = False,
    ) -> None:
        """Execute the full pipeline: load data, build curves, compute all shocks."""
        if shocks is None:
            shocks = ["50", "0"]

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
        """Write main P&L workbook under ``output``."""
        out = Path(self.output)
        out.mkdir(parents=True, exist_ok=True)
        path = (
            out
            / f"stock_{self.dateRun.strftime('%Y%m%d')}_rates_{self.dateRates.strftime('%Y%m%d')}_pnl.xlsx"
        )
        self.pnlAll.to_excel(
            path,
            sheet_name=f"pnl{self.dateRates.strftime('%Y%m%d')}",
            index=False,
            engine="openpyxl",
        )
        logger.info("export_files Done -> %s", path)


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
