"""PnlEngine — standalone P&L orchestrator accepting pre-parsed DataFrames.

Usage::

    from pnl_engine import PnlEngine

    engine = PnlEngine(
        deals=deals_df,          # BOOK1 deals (parsed DataFrame)
        schedule=schedule_df,    # Echeancier / schedule (wide nominal columns)
        wirp=wirp_df,            # WIRP rate expectations
        irs_stock=irs_stock_df,  # BOOK2 IRS stock (for MTM)
        date_run=datetime(2026, 3, 26),
        date_rates=datetime(2026, 3, 26),
    )
    result = engine.run(shocks=["0", "50"])

No file I/O, no path resolution — all input is via DataFrames.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.config import CURRENCY_TO_OIS, FUNDING_SOURCE, NON_STRATEGY_PRODUCTS
from pnl_engine.curves import CurveCache, clear_carry_cache, load_daily_curves, overlay_wirp
from pnl_engine.engine import (
    _build_ois_matrix,
    _month_columns,
    _resolve_rate_ref,
    aggregate_to_monthly,
    compute_book2_mtm,
    compute_daily_pnl,
    compute_strategy_pnl,
    weighted_average,
)
from pnl_engine.matrices import (
    build_accrual_days,
    build_alive_mask,
    build_client_rate_matrix,
    build_cumulative_carry_factors,
    build_cumulative_rate_factors,
    build_date_grid,
    build_funding_matrix,
    build_mm_vector,
    build_rate_matrix,
    expand_nominal_to_daily,
)
from pnl_engine.report import export_excel

logger = logging.getLogger(__name__)


class PnlEngine:
    """Standalone P&L computation engine.

    Accepts pre-parsed DataFrames — no file I/O. Can be used independently
    of the cockpit project.

    PnL semantics
    --------------
    BOOK1 (accrual): OIS-spread PnL on loans, deposits, bonds, hedge components.
        ``PnL = Nominal x (OIS_fwd - RateRef) / MM`` computed daily, aggregated
        monthly. Handles mid-month maturities via alive mask.

    BOOK2 (MTM): mark-to-market PnL on IRS positions via WASP ``stockSwapMTM``.
        The result is NPV, not an interest-accrual figure; downstream consumers
        should treat BOOK1 and BOOK2 separately.

    Strategy decomposition
    ----------------------
    Deals with IAS hedge accounting (``Strategy IAS`` not null) are decomposed
    into 4 synthetic legs: IAM/LD-NHCD, IAM/LD-HCD, BND-NHCD, BND-HCD.
    HCD legs use ``marginRate = EqOisRate + YTM - Clientrate_HCD`` with no OIS
    subtraction (``subtract_rate=False``).
    """

    def __init__(
        self,
        deals: pd.DataFrame,
        schedule: pd.DataFrame,
        wirp: pd.DataFrame,
        irs_stock: pd.DataFrame,
        date_run: datetime,
        date_rates: Optional[datetime] = None,
        *,
        funding_source: str = FUNDING_SOURCE,
        nmd_profiles: Optional[pd.DataFrame] = None,
        production_plans: Optional[list] = None,
    ):
        self.deals = deals
        self.schedule = schedule
        self.wirp = wirp
        self.irs_stock = irs_stock
        self.dateRun = date_run
        self.dateRates = date_rates if date_rates is not None else date_run

        self._funding_source = funding_source
        self._nmd_profiles = nmd_profiles
        self._production_plans = production_plans or []
        self._fwd_cache = CurveCache()

        # Public result attributes (populated by run)
        self.fwdOIS0: Optional[pd.DataFrame] = None
        self.fwdWIRP: Optional[pd.DataFrame] = None
        self.pnlAll: Optional[pd.DataFrame] = None
        self.pnlAllS: Optional[pd.DataFrame] = None
        self.pnl_by_deal: Optional[pd.DataFrame] = None
        self.eve_results: Optional[pd.DataFrame] = None
        self.eve_scenarios: Optional[pd.DataFrame] = None
        self.eve_krd: Optional[pd.DataFrame] = None
        self.eve_convexity: Optional[dict] = None
        self.nmd_match_log: list[dict] = []
        self.projection_log: list[dict] = []

        # Precomputed matrices (built once, reused across shocks)
        self._deals_use: Optional[pd.DataFrame] = None
        self._nominal_daily: Optional[np.ndarray] = None
        self._mm: Optional[np.ndarray] = None
        self._days: Optional[pd.DatetimeIndex] = None
        self._month_cols: Optional[list[str]] = None
        self._ois_indices: Optional[list[str]] = None
        self._float_wasp_indices: Optional[list[str]] = None
        self._accrual_days: Optional[np.ndarray] = None
        self._alive_mask: Optional[np.ndarray] = None

    def _build_static_matrices(self) -> None:
        """Build deal-level matrices that don't change across shocks."""
        deals = _resolve_rate_ref(self.deals)

        # Date grid from schedule
        self._month_cols = _month_columns(self.schedule)
        if self._month_cols:
            first_month = self._month_cols[0]
            start = pd.Timestamp(first_month.replace("/", "-") + "-01")
        else:
            start = pd.Timestamp(self.dateRun.replace(day=1))
        self._days = build_date_grid(start, months=60)

        # Join deals to schedule by (Dealid, Direction, Currency) per spec S4.3.
        deals["Dealid"] = pd.to_numeric(deals["Dealid"], errors="coerce")
        ech = self.schedule.copy()
        ech["Dealid"] = pd.to_numeric(ech["Dealid"], errors="coerce")

        join_keys = ["Dealid", "Direction", "Currency"]
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
        self._alive_mask = alive
        self._nominal_daily = self._nominal_daily * alive

        # Apply NMD behavioral decay if profiles provided
        if self._nmd_profiles is not None and not self._nmd_profiles.empty:
            from pnl_engine.nmd import apply_nmd_decay
            self._nominal_daily, self.nmd_match_log = apply_nmd_decay(
                self._deals_use, self._nmd_profiles, self._nominal_daily,
                self._days, self.dateRun,
            )

        # Apply CPR-based prepayment to fixed-rate mortgages
        from pnl_engine.prepayment import apply_cpr
        self._nominal_daily, cpr_log = apply_cpr(
            self._deals_use, self._nominal_daily, self._days,
        )
        if cpr_log:
            logger.info("_build_static_matrices: CPR applied to %d deals", len(cpr_log))

        # Apply dynamic balance sheet (reinvestment of maturing volumes)
        if self._production_plans:
            from pnl_engine.dynamic_balance_sheet import project_balance_sheet
            self._nominal_daily, self._deals_use, self.projection_log = project_balance_sheet(
                self._deals_use, self._nominal_daily, self._days,
                self._month_cols, self._production_plans, self.dateRun,
            )
            if self.projection_log:
                logger.info("_build_static_matrices: dynamic BS added %d synthetic deals", len(self.projection_log))

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
    ) -> pd.DataFrame:
        """Execute the full pipeline: build curves, compute all shocks.

        Args:
            shocks: List of shock specs (default ``["50", "0"]``).

        Returns:
            Wide DataFrame with P&L results for all shocks.
        """
        if shocks is None:
            shocks = ["50", "0"]

        self._build_static_matrices()

        # Load base curves
        self.fwdOIS0 = self._load_ois_curves(shock="0")
        self.fwdWIRP = overlay_wirp(self.fwdOIS0, self.wirp)

        # Run all shocks
        deal_summaries = []
        shock_results = []
        for shock in shocks:
            result = self.update_pnl(Shock=shock)
            shock_results.append(result)
            if hasattr(self, '_last_deal_summary') and not self._last_deal_summary.empty:
                deal_summaries.append(self._last_deal_summary)

        self.pnlAll = pd.concat(shock_results, ignore_index=True)
        self.pnl_by_deal = pd.concat(deal_summaries, ignore_index=True) if deal_summaries else None

        self.pnlAllS = self.pnl_stack()

        return self.pnlAll

    def _load_ois_curves(self, shock: str) -> pd.DataFrame:
        """Load OIS daily forward curves for a given shock, with caching."""
        cache_key = ("ois", str(self.dateRates), shock)
        cached = self._fwd_cache.get(cache_key)
        if cached is not None:
            return cached

        curves = load_daily_curves(
            date=self.dateRates,
            indices=self._ois_indices,
            shock=shock,
        )

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

        curves = load_daily_curves(
            date=self.dateRates,
            indices=self._float_wasp_indices,
            shock=shock,
        )

        self._fwd_cache.put(cache_key, curves)
        return curves

    def update_pnl(
        self,
        dateRates: Optional[datetime] = None,
        Shock: str = "0",
    ) -> pd.DataFrame:
        """Recompute P&L for a single shock and optional new rate date.

        Returns wide DataFrame (months as columns) with rows indexed by
        (Perimetre TOTAL, Deal currency, Product2BuyBack, Direction, Indice, Shock).
        """
        if self._deals_use is None:
            self._build_static_matrices()

        if dateRates is not None and dateRates != self.dateRates:
            self.dateRates = dateRates
            self.clear_fwd_cache()
        elif dateRates is not None:
            self.dateRates = dateRates

        # --- Curves & matrices for this shock ---
        if Shock == "wirp":
            ois_curves = self.fwdWIRP
        else:
            ois_curves = self._load_ois_curves(shock=Shock)

        ois_matrix = _build_ois_matrix(self._deals_use, ois_curves, self._days)
        ref_curves = self._load_ref_curves(shock=Shock)
        rate_matrix = build_rate_matrix(self._deals_use, self._days, ref_curves)

        # Apply NMD deposit beta if profiles provided
        if self._nmd_profiles is not None and not self._nmd_profiles.empty:
            from pnl_engine.nmd import apply_deposit_beta
            # Parse shock magnitude for stress-adjusted beta
            try:
                shock_bps = float(Shock) if Shock not in ("wirp",) else 0.0
            except (ValueError, TypeError):
                shock_bps = 0.0
            rate_matrix = apply_deposit_beta(
                rate_matrix, self._deals_use, self._nmd_profiles, ois_matrix,
                shock_bps=shock_bps,
            )

        n_days = len(self._days)
        mm_broadcast = self._mm[:, np.newaxis] * np.ones((1, n_days))
        daily_pnl = compute_daily_pnl(
            self._nominal_daily,
            ois_matrix,
            rate_matrix,
            mm_broadcast,
            accrual_days=self._accrual_days,
        )

        # --- Funding matrices for CoC decomposition ---
        funding_matrix = build_funding_matrix(
            self._deals_use, self._days, ois_matrix,
            funding_source=self._funding_source,
        )
        carry_funding_matrix = build_funding_matrix(
            self._deals_use, self._days, ois_matrix,
            funding_source="carry",
        )

        # --- Cumulative factors for value-date compounding ---
        clear_carry_cache()
        try:
            cum_carry, _carry_boundaries = build_cumulative_carry_factors(
                self._deals_use, self._days,
                date_rates=pd.Timestamp(self.dateRates),
            )
            cum_rate = build_cumulative_rate_factors(
                rate_matrix, self._accrual_days, mm_broadcast,
                self._alive_mask, self._days,
                date_rates=pd.Timestamp(self.dateRates),
            )
        except Exception:
            logger.warning("Cumulative factor build failed — falling back to per-month compounding", exc_info=True)
            cum_carry = None
            cum_rate = None

        # --- Monthly aggregation (deal-level) ---
        monthly = aggregate_to_monthly(
            daily_pnl, self._nominal_daily, ois_matrix, rate_matrix, self._days,
            funding_daily=funding_matrix,
            accrual_days=self._accrual_days,
            mm_daily=mm_broadcast,
            date_rates=pd.Timestamp(self.dateRates),
            carry_funding_daily=carry_funding_matrix,
            cum_carry_factors=cum_carry,
            cum_rate_factors=cum_rate,
        )

        # Enrich with deal metadata
        meta_cols = ["Product", "Currency", "Direction", "Strategy IAS",
                     "Périmètre TOTAL", "Clientrate", "EqOisRate", "YTM", "CocRate", "Amount",
                     "Counterparty", "Dealid", "Maturitydate", "is_floating"]
        for col in meta_cols:
            if col in self._deals_use.columns:
                monthly[col] = monthly["deal_idx"].map(self._deals_use[col])

        monthly["Days in Month"] = monthly["Month"].apply(
            lambda p: p.days_in_month if hasattr(p, "days_in_month") else 30
        )

        # Rename to pnl.py column names
        monthly["Deal currency"] = monthly["Currency"]
        monthly["Product2BuyBack"] = monthly["Product"]

        # --- Deal-level summary (extracted BEFORE aggregation drops deal columns) ---
        deal_summary_cols = [
            c for c in ["deal_idx", "Counterparty", "Dealid", "Currency", "Product",
                        "Direction", "Périmètre TOTAL", "Month"]
            if c in monthly.columns
        ]
        # Use "Total" rows for the current month (sum of Realized+Forecast),
        # and "Realized"/"Forecast" rows for past/future months (no "Total" exists).
        has_total = monthly.groupby("Month")["PnL_Type"].transform(
            lambda s: (s == "Total").any()
        )
        total_rows = monthly[
            ((has_total) & (monthly["PnL_Type"] == "Total"))
            | ((~has_total) & monthly["PnL_Type"].isin(["Realized", "Forecast"]))
        ]
        if not total_rows.empty and deal_summary_cols:
            agg_spec = {"PnL": ("PnL", "sum"), "Nominal": ("Nominal", "mean")}
            # CoC metrics — sum (already monthly totals from _aggregate_slice)
            for col in ["GrossCarry", "FundingCost_Simple", "PnL_Simple",
                        "FundingCost_Compounded", "PnL_Compounded"]:
                if col in total_rows.columns:
                    agg_spec[col] = (col, "sum")
            # Rates — first (one value per deal × month)
            for col in ["OISfwd", "RateRef", "FundingRate_Simple",
                        "FundingRate_Compounded", "Clientrate"]:
                if col in total_rows.columns:
                    agg_spec[col] = (col, "first")
            # Deal metadata — first (static per deal)
            for col in ["Amount", "Maturitydate", "is_floating"]:
                if col in total_rows.columns:
                    agg_spec[col] = (col, "first")
            deal_summary = total_rows.groupby(deal_summary_cols).agg(
                **agg_spec
            ).reset_index()
            deal_summary["Shock"] = Shock
            # Rename for consistency with pnlAllS
            if "Currency" in deal_summary.columns:
                deal_summary["Deal currency"] = deal_summary["Currency"]
            if "Product" in deal_summary.columns:
                deal_summary["Product2BuyBack"] = deal_summary["Product"]
        else:
            deal_summary = pd.DataFrame()
        self._last_deal_summary = deal_summary

        # --- 1. Non-strategy (§9): filter + aggregate + pivot to wide ---
        non_strat_mask = (
            (monthly["Strategy IAS"].isna() | (monthly["Product2BuyBack"] == "IRS-MTM"))
            & monthly["Product2BuyBack"].isin(NON_STRATEGY_PRODUCTS)
        )
        non_strat = monthly[non_strat_mask].copy()
        pnl_no_strat = self._aggregate_and_pivot(non_strat, Shock)

        # I5: Remove IRS-MTM PnL from non-strategy (§12.1 — BOOK2 provides it)
        if not pnl_no_strat.empty and "Indice" in pnl_no_strat.columns:
            pnl_no_strat = pnl_no_strat[
                ~((pnl_no_strat["Product2BuyBack"] == "IRS-MTM") & (pnl_no_strat["Indice"] == "PnL_Simple"))
            ].copy()

        # --- 2. Strategy (§10): 4 synthetic legs ---
        strategy_raw = compute_strategy_pnl(monthly)
        pnl_strat = pd.DataFrame()
        if not strategy_raw.empty:
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
                  & pnl_strat["Direction"].isin(["B", "S"]))
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
                    "Nominal", "OISfwd", "RateRef",
                    "GrossCarry",
                    "FundingCost_Simple", "PnL_Simple", "FundingRate_Simple",
                    "FundingCost_Compounded", "PnL_Compounded", "FundingRate_Compounded",
                ])
            ].copy()

        logger.info(
            "update_pnl Done (stock=%s, rates=%s, shock=%s, rows=%d)",
            self.dateRun, self.dateRates, Shock, len(pnl_all),
        )
        return pnl_all

    def _aggregate_and_pivot(self, data: pd.DataFrame, shock: str) -> pd.DataFrame:
        """Aggregate deal-level monthly data -> wide format (months as columns)."""
        if data.empty:
            return pd.DataFrame()

        group_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "PnL_Type", "Month"]

        sum_cols = {"Nominal": "sum"}
        if "Amount" in data.columns:
            sum_cols["Amount"] = "sum"
        for coc_col in ["GrossCarry",
                        "FundingCost_Simple", "PnL_Simple",
                        "FundingCost_Compounded", "PnL_Compounded"]:
            if coc_col in data.columns:
                sum_cols[coc_col] = "sum"
        agg = data.groupby(group_cols).agg(
            **{k: (k, v) for k, v in sum_cols.items()}
        ).reset_index()

        rate_cols = ["RateRef", "Clientrate", "EqOisRate", "CocRate", "OISfwd", "YTM",
                     "FundingRate_Simple", "FundingRate_Compounded"]
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
        id_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "PnL_Type", "Month"]
        coc_sum_cols = ["GrossCarry",
                        "FundingCost_Simple", "PnL_Simple",
                        "FundingCost_Compounded", "PnL_Compounded"]
        measure_cols = ["Amount", "Nominal"] + present_rates + coc_sum_cols
        present_measures = [c for c in measure_cols if c in agg.columns]

        agg_long = agg.melt(
            id_vars=id_cols,
            value_vars=present_measures,
            var_name="Indice",
            value_name="Value",
        )

        # Pivot months to columns
        pivot_idx = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Indice", "PnL_Type"]
        wide = pd.pivot_table(
            agg_long,
            values="Value",
            index=pivot_idx,
            columns="Month",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()

        if isinstance(wide.columns, pd.MultiIndex):
            wide.columns = [c[0] if c[1] == "" else c[1] for c in wide.columns]

        wide["Shock"] = shock
        cols = list(wide.columns)
        cols.remove("Shock")
        cols.insert(5, "Shock")
        wide = wide[cols]

        return wide

    def _aggregate_strategy_and_pivot(self, strategy_raw: pd.DataFrame, shock: str) -> pd.DataFrame:
        """C3: Second aggregation of strategy legs across strategies -> wide format."""
        if strategy_raw.empty:
            return pd.DataFrame()

        strategy = strategy_raw.copy()
        if "Deal currency" not in strategy.columns:
            strategy["Deal currency"] = strategy.get("Currency", "")

        group_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "PnL_Type", "Month"]
        present_group = [c for c in group_cols if c in strategy.columns]

        sum_cols = {"PnL_Simple": "sum", "Nominal": "sum"}
        if "PnL_Compounded" in strategy.columns:
            sum_cols["PnL_Compounded"] = "sum"
        if "Amount" in strategy.columns:
            sum_cols["Amount"] = "sum"
        agg = strategy.groupby(present_group).agg(**{k: (k, v) for k, v in sum_cols.items()}).reset_index()

        rate_cols = ["RateRef", "OISfwd"]
        present_rates = [c for c in rate_cols if c in strategy.columns]
        if present_rates and "Nominal" in strategy.columns:
            wavg = weighted_average(strategy, present_rates, "Nominal", present_group)
            for col in present_rates:
                if col in wavg.columns:
                    agg = agg.merge(wavg[[col]].reset_index(), on=present_group, how="left", suffixes=("_drop", ""))
                    if f"{col}_drop" in agg.columns:
                        agg = agg.drop(columns=f"{col}_drop")

        measure_cols = list(sum_cols.keys()) + present_rates
        present_measures = [c for c in measure_cols if c in agg.columns]

        agg_long = agg.melt(
            id_vars=present_group,
            value_vars=present_measures,
            var_name="Indice",
            value_name="Value",
        )

        pivot_idx = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Indice", "PnL_Type"]
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
        """Format BOOK2 IRS MTM to wide format (§11)."""
        if self.irs_stock is None or self.irs_stock.empty:
            return pd.DataFrame()

        # I7: Pre-filter
        irs = self.irs_stock.copy()
        mat_col = "Maturity Date" if "Maturity Date" in irs.columns else "Maturitydate" if "Maturitydate" in irs.columns else None
        if mat_col is not None:
            mat = pd.to_datetime(irs[mat_col], errors="coerce", dayfirst=True)
            irs = irs[mat > pd.Timestamp(self.dateRun)].copy()
        # Skip strategy filter when IRS-MTM already identified by Product (K+EUR format)
        is_explicit_mtm = "Product" in irs.columns and (irs["Product"] == "IRS-MTM").all()
        if not is_explicit_mtm:
            strat_col = "Strategy (Agapes IAS)" if "Strategy (Agapes IAS)" in irs.columns else "Strategy IAS" if "Strategy IAS" in irs.columns else None
            if strat_col is not None:
                irs = irs[irs[strat_col].isna()].copy()

        if irs.empty:
            return pd.DataFrame()

        book2 = compute_book2_mtm(irs, self.dateRates, shock)
        if book2.empty or "MTM" not in book2.columns:
            return pd.DataFrame()

        total_mtm = pd.to_numeric(book2["MTM"], errors="coerce").sum()
        if total_mtm == 0:
            return pd.DataFrame()

        direction = "D"
        if "Asset / Liabilities" in book2.columns:
            direction = "D" if (book2["Asset / Liabilities"] == "Actif").any() else "L"

        ccy_series = book2.get("Currency Code (ISO)", book2.get("Currency", pd.Series(["CHF"])))
        ccy = ccy_series.iloc[0] if len(book2) > 0 else "CHF"
        month = self._days[0].to_period("M") if self._days is not None and len(self._days) > 0 else "2026-04"

        row = {
            "Périmètre TOTAL": "CC",
            "Deal currency": ccy if pd.notna(ccy) else "CHF",
            "Product2BuyBack": "IRS-MTM",
            "Direction": direction,
            "Indice": "PnL_Simple",
            "Shock": shock,
            month: total_mtm,
        }
        return pd.DataFrame([row])

    def run_eve(
        self,
        scenarios: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Compute EVE (Economic Value of Equity) and optionally ΔEVE scenarios.

        Must be called after run() so that static matrices and curves are ready.

        Args:
            scenarios: Optional BCBS 368 scenario definitions for ΔEVE.

        Returns:
            Base EVE DataFrame per deal.
        """
        from pnl_engine.eve import compute_eve, compute_eve_scenarios, compute_key_rate_durations

        if self._deals_use is None:
            self._build_static_matrices()
        if self.fwdOIS0 is None:
            self.fwdOIS0 = self._load_ois_curves(shock="0")

        ois_matrix = _build_ois_matrix(self._deals_use, self.fwdOIS0, self._days)
        ref_curves = self._load_ref_curves(shock="0")
        rate_matrix = build_rate_matrix(self._deals_use, self._days, ref_curves)

        # Build client rate matrix for EVE cashflow generation
        client_rate_matrix = build_client_rate_matrix(self._deals_use, len(self._days))

        # Base EVE
        self.eve_results = compute_eve(
            self._nominal_daily, ois_matrix, rate_matrix, self._mm,
            self._days, self._deals_use, self.dateRun,
            client_rate_matrix=client_rate_matrix,
        )
        logger.info("run_eve: base EVE computed (%d deals, total=%.0f)",
                     len(self.eve_results), self.eve_results["eve"].sum())

        # Scenario ΔEVE
        if scenarios is not None and not scenarios.empty:
            # Build nominal adjuster for rate-dependent CPR under scenarios
            from pnl_engine.prepayment import apply_cpr_rate_dependent
            nominal_adjuster = lambda deals, nom, days, ois: apply_cpr_rate_dependent(
                deals, nom, days, ois,
            )

            self.eve_scenarios = compute_eve_scenarios(
                self._nominal_daily, ois_matrix, rate_matrix, self._mm,
                self._days, self._deals_use, self.dateRun,
                scenarios, self.fwdOIS0,
                nominal_adjuster=nominal_adjuster,
                client_rate_matrix=client_rate_matrix,
            )
            logger.info("run_eve: %d scenario results", len(self.eve_scenarios))

            # Key rate durations
            self.eve_krd = compute_key_rate_durations(
                self._nominal_daily, ois_matrix, rate_matrix, self._mm,
                self._days, self._deals_use, self.dateRun,
                self.fwdOIS0,
                client_rate_matrix=client_rate_matrix,
            )
            logger.info("run_eve: KRD computed (%d points)", len(self.eve_krd))

            # Convexity from parallel_up / parallel_down scenarios
            from pnl_engine.eve import compute_eve_convexity

            eve_base_by_ccy = (
                self.eve_results.groupby("Currency")["eve"].sum().to_dict()
                if "Currency" in self.eve_results.columns else {}
            )
            up_rows = self.eve_scenarios[self.eve_scenarios["scenario"] == "parallel_up"]
            down_rows = self.eve_scenarios[self.eve_scenarios["scenario"] == "parallel_down"]
            eve_up_by_ccy = dict(zip(up_rows["currency"], up_rows["eve_shocked"])) if not up_rows.empty else {}
            eve_down_by_ccy = dict(zip(down_rows["currency"], down_rows["eve_shocked"])) if not down_rows.empty else {}

            if eve_base_by_ccy and eve_up_by_ccy and eve_down_by_ccy:
                self.eve_convexity = compute_eve_convexity(
                    eve_base_by_ccy, eve_up_by_ccy, eve_down_by_ccy,
                )
                logger.info("run_eve: convexity computed (eff_dur=%.4f, conv=%.4f)",
                            self.eve_convexity["total"]["effective_duration"],
                            self.eve_convexity["total"]["convexity"])

        return self.eve_results

    def run_scenarios(
        self,
        scenarios: pd.DataFrame,
    ) -> pd.DataFrame:
        """Run BCBS 368 non-parallel rate shock scenarios.

        Args:
            scenarios: DataFrame with columns: scenario, tenor, CHF, EUR, USD, GBP
                       (shift values in basis points).

        Returns:
            Stacked DataFrame (pnlAllS format) with Shock = scenario name.
        """
        from pnl_engine.scenarios import interpolate_scenario_shifts, apply_scenario_to_curves

        if self._deals_use is None:
            self._build_static_matrices()
        if self.fwdOIS0 is None:
            self.fwdOIS0 = self._load_ois_curves(shock="0")

        scenario_names = sorted(scenarios["scenario"].unique())
        all_results = []

        for sc_name in scenario_names:
            # Build shifted curves for each currency's OIS indice
            shifted_curves = self.fwdOIS0.copy()
            for ccy, ois_indice in CURRENCY_TO_OIS.items():
                if ccy not in self._deals_use["Currency"].unique():
                    continue
                shift_array = interpolate_scenario_shifts(
                    scenarios, sc_name, ccy, self._days, self.dateRun,
                )
                shifted_curves = apply_scenario_to_curves(
                    shifted_curves, shift_array, ois_indice,
                )

            # Build OIS matrix from shifted curves
            ois_matrix = _build_ois_matrix(self._deals_use, shifted_curves, self._days)
            ref_curves = self._load_ref_curves(shock="0")
            rate_matrix = build_rate_matrix(self._deals_use, self._days, ref_curves)

            n_days = len(self._days)
            mm_broadcast = self._mm[:, np.newaxis] * np.ones((1, n_days))
            daily_pnl = compute_daily_pnl(
                self._nominal_daily, ois_matrix, rate_matrix, mm_broadcast,
                accrual_days=self._accrual_days,
            )

            monthly = aggregate_to_monthly(
                daily_pnl, self._nominal_daily, ois_matrix, rate_matrix, self._days,
                date_rates=pd.Timestamp(self.dateRates),
            )

            # Enrich with metadata
            meta_cols = ["Product", "Currency", "Direction", "Strategy IAS",
                         "Périmètre TOTAL", "Clientrate", "EqOisRate", "YTM", "CocRate", "Amount"]
            for col in meta_cols:
                if col in self._deals_use.columns:
                    monthly[col] = monthly["deal_idx"].map(self._deals_use[col])

            monthly["Deal currency"] = monthly.get("Currency", "")
            monthly["Product2BuyBack"] = monthly.get("Product", "")

            # Aggregate non-strategy (simplified — skip strategy decomposition for scenarios)
            non_strat = monthly.copy()
            pnl_wide = self._aggregate_and_pivot(non_strat, sc_name)
            if not pnl_wide.empty:
                all_results.append(pnl_wide)

            logger.info("run_scenarios: %s done (%d rows)", sc_name, len(pnl_wide))

        if not all_results:
            return pd.DataFrame()

        combined = pd.concat(all_results, ignore_index=True)

        # Stack to long format (same as pnl_stack but on this subset)
        idx_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                     "Direction", "Indice", "PnL_Type", "Shock"]
        present_idx = [c for c in idx_cols if c in combined.columns]
        month_cols = [c for c in combined.columns if c not in present_idx]
        if month_cols:
            stacked = combined.set_index(present_idx)
            stacked.columns.name = "Month"
            result = stacked.stack().rename("Value").reset_index()
        else:
            result = combined

        return result

    def pnl_stack(self) -> pd.DataFrame:
        """Long stacked view of ``pnlAll`` (Month in index)."""
        if self.pnlAll is None or self.pnlAll.empty:
            return pd.DataFrame()

        idx_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                     "Direction", "Indice", "PnL_Type", "Shock"]
        present_idx = [c for c in idx_cols if c in self.pnlAll.columns]

        month_cols = [c for c in self.pnlAll.columns if c not in present_idx]
        if not month_cols:
            return self.pnlAll.copy()

        stacked = self.pnlAll.set_index(present_idx)
        stacked.columns.name = "Month"
        result = stacked.stack().rename("Value").reset_index()

        mi_cols = ["Périmètre TOTAL", "Deal currency", "Product2BuyBack",
                    "Direction", "Indice", "PnL_Type", "Month", "Shock"]
        present_mi = [c for c in mi_cols if c in result.columns]
        result = result.set_index(present_mi)

        return result

    def compute_enrichment_data(self) -> dict:
        """Compute pre-built enrichment data for dashboard (locked-in NII + beta sensitivity).

        These require engine-internal matrices not available in the chart orchestrator.
        Returns dict with 'locked_in_nii' and 'beta_sensitivity' keys.
        """
        enrichment = {"locked_in_nii": {"has_data": False}, "beta_sensitivity": {}}

        if self._deals_use is None or self._nominal_daily is None:
            return enrichment

        # Build base-shock matrices (shock=0)
        try:
            ois_curves = self._load_ois_curves(shock="0")
            ois_matrix = _build_ois_matrix(self._deals_use, ois_curves, self._days)
            ref_curves = self._load_ref_curves(shock="0")
            rate_matrix = build_rate_matrix(self._deals_use, self._days, ref_curves)

            if self._nmd_profiles is not None and not self._nmd_profiles.empty:
                from pnl_engine.nmd import apply_deposit_beta
                rate_matrix = apply_deposit_beta(
                    rate_matrix, self._deals_use, self._nmd_profiles, ois_matrix,
                )
        except Exception as exc:
            logger.warning("Enrichment: failed to build base matrices: %s", exc)
            return enrichment

        # Locked-in NII
        try:
            from pnl_engine.locked_in_nii import compute_locked_in_nii
            enrichment["locked_in_nii"] = compute_locked_in_nii(
                self._deals_use, self._nominal_daily, rate_matrix, ois_matrix, self._mm,
            )
        except Exception as exc:
            logger.warning("Enrichment: locked_in_nii failed: %s", exc)

        # NMD beta sensitivity
        try:
            from pnl_engine.nmd import compute_nmd_beta_sensitivity
            if self._nmd_profiles is not None and not self._nmd_profiles.empty:
                enrichment["beta_sensitivity"] = compute_nmd_beta_sensitivity(
                    self._deals_use, self._nmd_profiles,
                    rate_matrix, ois_matrix, self._nominal_daily, self._mm,
                )
        except Exception as exc:
            logger.warning("Enrichment: beta_sensitivity failed: %s", exc)

        return enrichment
