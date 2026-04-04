"""ForecastRatePnL — stateful class wrapping the functional engine.

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
import pandas as pd

from cockpit.config import CURRENCY_TO_OIS, FUNDING_SOURCE, NON_STRATEGY_PRODUCTS, SHOCKS
from cockpit.engine.pnl.curves import CurveCache, load_daily_curves, overlay_wirp
from cockpit.engine.pnl.engine import (
    _build_ois_matrix,
    _mock_curves_from_wirp,
    _resolve_rate_ref,
    aggregate_to_monthly,
    compute_book2_mtm,
    compute_daily_pnl,
    compute_strategy_pnl,
    merge_results,
    weighted_average,
)
from cockpit.engine.pnl.matrices import (
    build_accrual_days,
    build_alive_mask,
    build_date_grid,
    build_funding_matrix,
    build_mm_vector,
    build_rate_matrix,
    expand_nominal_to_daily,
)
from cockpit.data.parsers import (
    _month_columns,
    parse_echeancier,
    parse_irs_stock,
    parse_mtd,
    parse_wirp,
)
from cockpit.engine.pnl.report import export_excel

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_PNL_BASE = os.environ.get(
    "PNL_OIS_BASE",
    r"J:\ALM\ALM\06. Analyses et projets\2024_OIS",
)


class ForecastRatePnL:
    """Forecast economic Rate P&L engine.

    PnL semantics
    --------------
    BOOK1 (accrual): OIS-spread PnL on loans, deposits, bonds, hedge components.
        ``PnL = Nominal × (OIS_fwd − RateRef) / MM`` computed daily, aggregated
        monthly. Handles mid-month maturities via alive mask.

    BOOK2 (MTM): mark-to-market PnL on IRS positions via WASP ``stockSwapMTM``.
        The result is NPV, not an interest-accrual figure; downstream consumers
        should treat BOOK1 and BOOK2 separately.

    Strategy decomposition
    ----------------------
    Deals with IAS hedge accounting (``Strategy IAS`` not null) are decomposed
    into 4 synthetic legs: IAM/LD-NHCD, IAM/LD-HCD, BND-NHCD, BND-HCD.
    HCD legs use ``marginRate = EqOisRate + YTM − Clientrate_HCD`` with no OIS
    subtraction (``subtract_rate=False``).
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
        self._fwd_cache = CurveCache()

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

        # Precomputed matrices (built once in load_data, reused across shocks)
        self._deals_use: Optional[pd.DataFrame] = None
        self._nominal_daily: Optional[np.ndarray] = None
        self._mm: Optional[np.ndarray] = None
        self._days: Optional[pd.DatetimeIndex] = None
        self._month_cols: Optional[list[str]] = None
        self._ois_indices: Optional[list[str]] = None
        self._float_wasp_indices: Optional[list[str]] = None
        self._accrual_days: Optional[np.ndarray] = None

        self.run(shocks=["50", "0"], export=export)

    def load_data(self) -> None:
        """Load deal data, schedule, WIRP, and IRS stock from Excel files."""
        mtd_file = next(self.input_dir.glob("*MTD Standard Liquidity PnL Report*"))
        echeancier_file = next(self.input_dir.glob("*Echeancier*"))
        wirp_file = next(self.input_dir.glob("*WIRP*"))
        irs_file = next(self.input_dir.glob("*IRS*"))

        self.pnlData = parse_mtd(mtd_file)
        self.scheduleData = parse_echeancier(echeancier_file)
        self.wirpData = parse_wirp(wirp_file)
        self.irsStock = parse_irs_stock(irs_file)

        # Filter TMSWBFIGE folder for IRS-MTM deals (mirrors pnl_init.py)
        if "Folder" in self.scheduleData.columns:
            self.scheduleDataMTM = self.scheduleData[
                self.scheduleData["Folder"].isin(["TMSWBFIGE"])
            ]
            self._append_mtm_from_schedule()
        else:
            self.scheduleDataMTM = pd.DataFrame()
            logger.warning("Folder column not found in Echeancier — skipping MTM schedule append")

        logger.info("load_data Done (%d deals, %d schedule rows)", len(self.pnlData), len(self.scheduleData))

    def _append_mtm_from_schedule(self) -> None:
        """Append IRS-MTM deals from TMSWBFIGE schedule rows missing in conso.

        Mirrors pnl_init.py merge_pnl_schedule: schedule rows in the TMSWBFIGE
        folder are mapped to pnlData columns and tagged as IRS-MTM / Product=IRS.
        """
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

    def _build_static_matrices(self) -> None:
        """Build deal-level matrices that don't change across shocks."""
        deals = _resolve_rate_ref(self.pnlData)

        # Date grid from echeancier
        self._month_cols = _month_columns(self.scheduleData)
        if self._month_cols:
            first_month = self._month_cols[0]
            start = pd.Timestamp(first_month.replace("/", "-") + "-01")
        else:
            start = pd.Timestamp(self.dateRun.replace(day=1))
        self._days = build_date_grid(start, months=60)

        # Join deals to echeancier by (Dealid, Direction, Currency) per spec S4.3.
        # Direction is now consistent: parser uses Deal Type "BD" → B for bonds.
        deals["Dealid"] = pd.to_numeric(deals["Dealid"], errors="coerce")
        ech = self.scheduleData.copy()
        ech["Dealid"] = pd.to_numeric(ech["Dealid"], errors="coerce")

        join_keys = ["Dealid", "Direction", "Currency"]
        # Aggregate by join keys (sum F+V legs if both present for same deal)
        present_keys = [k for k in join_keys if k in ech.columns]
        ech_agg = ech.groupby(present_keys)[self._month_cols].sum().reset_index()

        merged = deals.merge(
            ech_agg,
            on=present_keys,
            how="left",
            suffixes=("", "_ech"),
        )
        for mc in self._month_cols:
            if mc in merged.columns:
                merged[mc] = merged[mc].fillna(0.0)

        self._deals_use = merged.reset_index(drop=True)

        # Build matrices (C6: alive mask caps start at first of dateRun's month)
        self._nominal_daily = expand_nominal_to_daily(self._deals_use[self._month_cols], self._days)
        alive = build_alive_mask(self._deals_use, self._days, date_run=pd.Timestamp(self.dateRun))
        self._nominal_daily = self._nominal_daily * alive
        self._mm = build_mm_vector(self._deals_use)
        self._accrual_days = build_accrual_days(self._days)

        # Collect needed curve indices
        self._ois_indices = list({
            CURRENCY_TO_OIS[c]
            for c in self._deals_use["Currency"].unique()
            if c in CURRENCY_TO_OIS
        })
        self._float_wasp_indices = list(
            self._deals_use.loc[self._deals_use["is_floating"], "ref_index"]
            .replace("", np.nan).dropna().unique()
        )
        self._float_wasp_indices = [
            i for i in self._float_wasp_indices
            if i not in set(CURRENCY_TO_OIS.values())
        ]

        logger.info(
            "_build_static_matrices Done (%d deals, %d days, OIS indices=%s, float indices=%s)",
            len(self._deals_use), len(self._days), self._ois_indices, self._float_wasp_indices,
        )

    def clear_fwd_cache(self) -> None:
        """Clear cached forward curves (use after changing dateRates)."""
        self._fwd_cache = CurveCache()

    def run(
        self,
        shocks: Optional[list[str]] = None,
        export: bool = False,
    ) -> None:
        """Execute the full pipeline: load data, build curves, compute all shocks.

        Args:
            shocks: List of shock specs (default ``["50", "0"]``).
            export: Write Excel workbook after computation.
        """
        if shocks is None:
            shocks = ["50", "0"]

        self.load_data()
        self._build_static_matrices()

        # Load base curves
        self.fwdOIS0 = self._load_ois_curves(shock="0")
        self.fwdWIRP = overlay_wirp(self.fwdOIS0, self.wirpData)

        # Run all shocks
        self.pnlAll = pd.concat(
            [self.update_pnl(Shock=shock) for shock in shocks],
            ignore_index=True,
        )

        self.pnlAllS = self.pnl_stack()

        if export:
            self.export_files()

    def _load_ois_curves(self, shock: str) -> pd.DataFrame:
        """Load OIS daily forward curves for a given shock, with caching."""
        cache_key = ("ois", str(self.dateRates), shock)
        cached = self._fwd_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            curves = load_daily_curves(
                date=self.dateRates,
                indices=self._ois_indices,
                shock=shock,
            )
        except RuntimeError:
            logger.info("WASP unavailable, building mock curves from WIRP (shock=%s)", shock)
            curves = _mock_curves_from_wirp(self.wirpData, self._days, shock=shock)

        self._fwd_cache.put(cache_key, curves)
        return curves

    def _load_ref_curves(self, shock: str) -> Optional[pd.DataFrame]:
        """Load non-OIS floating reference rate curves, with caching."""
        if not self._float_wasp_indices:
            return None

        cache_key = ("ref", str(self.dateRates), shock)
        cached = self._fwd_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            curves = load_daily_curves(
                date=self.dateRates,
                indices=self._float_wasp_indices,
                shock=shock,
            )
        except RuntimeError:
            return None

        self._fwd_cache.put(cache_key, curves)
        return curves

    def update_pnl(
        self,
        dateRates: Optional[datetime] = None,
        reload_data: bool = False,
        Shock: str = "0",
    ) -> pd.DataFrame:
        """Recompute P&L for a single shock and optional new rate date.

        Returns wide DataFrame (months as columns) with rows indexed by
        (Périmètre TOTAL, Deal currency, Product2BuyBack, Direction, Indice, Shock).
        Aligned with pnl.py ``merge_pnl`` output format.
        """
        if dateRates is not None:
            self.dateRates = dateRates

        if reload_data:
            self.load_data()
            self._build_static_matrices()
            self.clear_fwd_cache()
            self.fwdOIS0 = self._load_ois_curves(shock="0")
            self.fwdWIRP = overlay_wirp(self.fwdOIS0, self.wirpData)

        # --- Curves & matrices for this shock ---
        if Shock == "wirp":
            ois_curves = self.fwdWIRP
        else:
            ois_curves = self._load_ois_curves(shock=Shock)

        ois_matrix = _build_ois_matrix(self._deals_use, ois_curves, self._days)
        ref_curves = self._load_ref_curves(shock=Shock)
        rate_matrix = build_rate_matrix(self._deals_use, self._days, ref_curves)

        n_days = len(self._days)
        mm_broadcast = self._mm[:, np.newaxis] * np.ones((1, n_days))
        daily_pnl = compute_daily_pnl(
            self._nominal_daily,
            ois_matrix,
            rate_matrix,
            mm_broadcast,
        )

        # --- Funding matrix for CoC decomposition ---
        funding_matrix = build_funding_matrix(
            self._deals_use, self._days, ois_matrix,
            funding_source=self._funding_source,
        )

        # --- Monthly aggregation (deal-level) ---
        monthly = aggregate_to_monthly(
            daily_pnl, self._nominal_daily, ois_matrix, rate_matrix, self._days,
            funding_daily=funding_matrix,
            accrual_days=self._accrual_days,
            mm_daily=mm_broadcast,
        )

        # Enrich with deal metadata
        meta_cols = ["Product", "Currency", "Direction", "Strategy IAS",
                     "Périmètre TOTAL", "Clientrate", "EqOisRate", "YTM", "CocRate", "Amount"]
        for col in meta_cols:
            if col in self._deals_use.columns:
                monthly[col] = monthly["deal_idx"].map(self._deals_use[col])

        monthly["Days in Month"] = monthly["Month"].apply(
            lambda p: p.days_in_month if hasattr(p, "days_in_month") else 30
        )

        # Rename to pnl.py column names
        monthly["Deal currency"] = monthly["Currency"]
        monthly["Product2BuyBack"] = monthly["Product"]

        # --- 1. Non-strategy (§9): filter + aggregate + pivot to wide ---
        # IRS-MTM (BOOK2) bypasses Strategy IAS filter — they carry a strategy
        # tag from the MTD but are valued via BOOK2 MTM, not the strategy path.
        non_strat_mask = (
            (monthly["Strategy IAS"].isna() | (monthly["Product2BuyBack"] == "IRS-MTM"))
            & monthly["Product2BuyBack"].isin(NON_STRATEGY_PRODUCTS)
        )
        non_strat = monthly[non_strat_mask].copy()
        pnl_no_strat = self._aggregate_and_pivot(non_strat, Shock)

        # I5: Remove IRS-MTM PnL from non-strategy (§12.1 — BOOK2 provides it)
        if not pnl_no_strat.empty and "Indice" in pnl_no_strat.columns:
            pnl_no_strat = pnl_no_strat[
                ~((pnl_no_strat["Product2BuyBack"] == "IRS-MTM") & (pnl_no_strat["Indice"] == "PnL"))
            ].copy()

        # --- 2. Strategy (§10): 4 synthetic legs ---
        strategy_raw = compute_strategy_pnl(monthly)
        pnl_strat = pd.DataFrame()
        if not strategy_raw.empty:
            # C3: Second aggregation across strategies (§10.6)
            # Strategy output already has Product2BuyBack = IAM/LD-NHCD etc.
            # Aggregate by (Périmètre, Deal currency, Product2BuyBack, Direction, Month)
            pnl_strat = self._aggregate_strategy_and_pivot(strategy_raw, Shock)

        # --- 3. BOOK2 IRS MTM (§11) ---
        pnl_irs_mtm = self._format_book2_wide(Shock)

        # --- 4. Final assembly (§12) ---
        parts = []
        if not pnl_no_strat.empty:
            parts.append(pnl_no_strat)

        if not pnl_strat.empty:
            # Direction filtering (§10.8)
            pnl_strat = pnl_strat[
                ~(pnl_strat["Product2BuyBack"].isin(["BND-HCD", "BND-NHCD"])
                  & pnl_strat["Direction"].isin(["L", "D"]))
            ]
            pnl_strat = pnl_strat[
                ~(pnl_strat["Product2BuyBack"].isin(["IAM/LD-HCD", "IAM/LD-NHCD"])
                  & pnl_strat["Direction"].isin(["B"]))
            ]
            parts.append(pnl_strat)

        if not pnl_irs_mtm.empty:
            parts.append(pnl_irs_mtm)

        if not parts:
            return pd.DataFrame()

        pnl_all = pd.concat(parts, ignore_index=True)

        # Filter: keep core + CoC Indice rows (§12.2)
        if "Indice" in pnl_all.columns:
            pnl_all = pnl_all[
                pnl_all["Indice"].isin([
                    "Nominal", "OISfwd", "PnL", "RateRef",
                    "GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate",
                ])
            ].copy()

        logger.info(
            "update_pnl Done (stock=%s, rates=%s, shock=%s, rows=%d)",
            self.dateRun, self.dateRates, Shock, len(pnl_all),
        )
        return pnl_all

    def _aggregate_and_pivot(self, data: pd.DataFrame, shock: str) -> pd.DataFrame:
        """Aggregate deal-level monthly data → wide format (months as columns).

        Aligned with pnl.py ``compute_indic_pnl`` + ``compute_pnl_agg``.
        PnL/Nominal/Amount: sum. Rates: nominal-weighted average.
        """
        if data.empty:
            return pd.DataFrame()

        group_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Month"]

        # Aggregation: PnL/Nominal/Amount/CoC measures sum; rates weighted avg
        sum_cols = {"PnL": "sum", "Nominal": "sum"}
        if "Amount" in data.columns:
            sum_cols["Amount"] = "sum"
        for coc_col in ["GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound"]:
            if coc_col in data.columns:
                sum_cols[coc_col] = "sum"
        agg = data.groupby(group_cols).agg(
            **{k: (k, v) for k, v in sum_cols.items()}
        ).reset_index()

        rate_cols = ["RateRef", "Clientrate", "EqOisRate", "CocRate", "OISfwd", "YTM", "FundingRate"]
        present_rates = [c for c in rate_cols if c in data.columns]
        if present_rates:
            wavg = weighted_average(data, present_rates, "Nominal", group_cols)
            for col in present_rates:
                if col in wavg.columns:
                    agg = agg.merge(
                        wavg[[col]].reset_index(),
                        on=group_cols,
                        how="left",
                        suffixes=("", "_wavg"),
                    )
                    if f"{col}_wavg" in agg.columns:
                        agg[col] = agg[f"{col}_wavg"]
                        agg = agg.drop(columns=f"{col}_wavg")

        # Stack measures into Indice rows
        id_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Month"]
        measure_cols = ["Amount", "Nominal", "PnL"] + present_rates
        present_measures = [c for c in measure_cols if c in agg.columns]

        agg_long = agg.melt(
            id_vars=id_cols,
            value_vars=present_measures,
            var_name="Indice",
            value_name="Value",
        )

        # Pivot months to columns
        pivot_idx = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Indice"]
        wide = pd.pivot_table(
            agg_long,
            values="Value",
            index=pivot_idx,
            columns="Month",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        # Flatten MultiIndex columns if needed
        if isinstance(wide.columns, pd.MultiIndex):
            wide.columns = [c[0] if c[1] == "" else c[1] for c in wide.columns]

        wide["Shock"] = shock
        # Insert Shock after Direction (position 4→5, like pnl.py)
        cols = list(wide.columns)
        cols.remove("Shock")
        cols.insert(5, "Shock")
        wide = wide[cols]

        return wide

    def _aggregate_strategy_and_pivot(self, strategy_raw: pd.DataFrame, shock: str) -> pd.DataFrame:
        """C3: Second aggregation of strategy legs across strategies → wide format.

        Aligned with pnl.py compute_pnl_agg(pnlOisDataTStrat) — collapses
        all strategies into product-level totals by (Périmètre, Currency,
        Product2BuyBack, Direction, Month).
        """
        if strategy_raw.empty:
            return pd.DataFrame()

        strategy = strategy_raw.copy()
        if "Deal currency" not in strategy.columns:
            strategy["Deal currency"] = strategy.get("Currency", "")

        group_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Month"]
        present_group = [c for c in group_cols if c in strategy.columns]

        # Sum P&L, Nominal, Amount across strategies
        sum_cols = {"PnL": "sum", "Nominal": "sum"}
        if "Amount" in strategy.columns:
            sum_cols["Amount"] = "sum"
        agg = strategy.groupby(present_group).agg(**{k: (k, v) for k, v in sum_cols.items()}).reset_index()

        # Nominal-weighted average for rates
        rate_cols = ["RateRef", "OISfwd"]
        present_rates = [c for c in rate_cols if c in strategy.columns]
        if present_rates and "Nominal" in strategy.columns:
            wavg = weighted_average(strategy, present_rates, "Nominal", present_group)
            for col in present_rates:
                if col in wavg.columns:
                    agg = agg.merge(wavg[[col]].reset_index(), on=present_group, how="left", suffixes=("_drop", ""))
                    if f"{col}_drop" in agg.columns:
                        agg = agg.drop(columns=f"{col}_drop")

        # Stack measures into Indice rows
        measure_cols = list(sum_cols.keys()) + present_rates
        present_measures = [c for c in measure_cols if c in agg.columns]

        agg_long = agg.melt(
            id_vars=present_group,
            value_vars=present_measures,
            var_name="Indice",
            value_name="Value",
        )

        # Pivot months to columns
        pivot_idx = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Indice"]
        present_idx = [c for c in pivot_idx if c in agg_long.columns]

        wide = pd.pivot_table(
            agg_long, values="Value", index=present_idx, columns="Month",
            aggfunc="sum", fill_value=0,
        ).reset_index()

        if isinstance(wide.columns, pd.MultiIndex):
            wide.columns = [c[0] if c[1] == "" else c[1] for c in wide.columns]

        wide["Shock"] = shock
        cols = list(wide.columns)
        cols.remove("Shock")
        cols.insert(5, "Shock")
        wide = wide[cols]

        return wide

    def _format_book2_wide(self, shock: str) -> pd.DataFrame:
        """Format BOOK2 IRS MTM to pnl.py wide format (§11).

        I7: Pre-filter IRS stock to Maturity > dateRun and Strategy IAS is null.
        """
        if self.irsStock is None or self.irsStock.empty:
            return pd.DataFrame()

        # I7: Pre-filter
        irs = self.irsStock.copy()
        if "Maturity Date" in irs.columns:
            mat = pd.to_datetime(irs["Maturity Date"], errors="coerce", dayfirst=True)
            irs = irs[mat > pd.Timestamp(self.dateRun)].copy()
        if "Strategy (Agapes IAS)" in irs.columns:
            irs = irs[irs["Strategy (Agapes IAS)"].isna()].copy()

        if irs.empty:
            return pd.DataFrame()

        book2 = compute_book2_mtm(irs, self.dateRates, shock)
        if book2.empty or "MTM" not in book2.columns:
            return pd.DataFrame()

        total_mtm = pd.to_numeric(book2["MTM"], errors="coerce").sum()
        if total_mtm == 0:
            return pd.DataFrame()

        # Direction from Asset/Liabilities (§11.5)
        direction = "L"  # default
        if "Asset / Liabilities" in book2.columns:
            direction = "L" if (book2["Asset / Liabilities"] == "Actif").any() else "D"

        ccy = book2.get("Currency Code (ISO)", pd.Series(["CHF"])).iloc[0] if len(book2) > 0 else "CHF"
        month = self._days[0].to_period("M") if self._days is not None and len(self._days) > 0 else "2026-04"

        row = {
            "Périmètre TOTAL": "CC",
            "Deal currency": ccy if pd.notna(ccy) else "CHF",
            "Product2BuyBack": "IRS-MTM",
            "Direction": direction,
            "Indice": "PnL",
            "Shock": shock,
            month: total_mtm,
        }
        return pd.DataFrame([row])

    def pnl_stack(self) -> pd.DataFrame:
        """Long stacked view of ``pnlAll`` (Month in index).

        Aligned with pnl.py ``pnl_stack``: 7-level MultiIndex
        (Périmètre TOTAL, Deal currency, Product2BuyBack, Direction, Indice, Month, Shock).
        """
        if self.pnlAll is None or self.pnlAll.empty:
            return pd.DataFrame()

        idx_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                     "Direction", "Indice", "Shock"]
        present_idx = [c for c in idx_cols if c in self.pnlAll.columns]

        # Month columns = everything not in idx_cols
        month_cols = [c for c in self.pnlAll.columns if c not in present_idx]
        if not month_cols:
            return self.pnlAll.copy()

        stacked = self.pnlAll.set_index(present_idx)
        stacked.columns.name = "Month"
        result = stacked.stack().rename("Value").reset_index()

        # Set 7-level MultiIndex like pnl.py
        mi_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                    "Direction", "Indice", "Month", "Shock"]
        present_mi = [c for c in mi_cols if c in result.columns]
        result = result.set_index(present_mi)

        return result

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
                 "Direction", "Shock", "Indice", "Level"]
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
