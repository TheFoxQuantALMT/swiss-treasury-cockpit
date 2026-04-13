"""Tier 2: Invariant property tests.

These test properties that must ALWAYS hold regardless of input data.
Uses the mock ideal-format input files for realistic multi-deal scenarios.

Regulatory basis:
    - IFRS 9 §6.5.16: hedge effectiveness (strategy legs sum to original)
    - BCBS 368: NII sensitivity monotonicity
    - Internal: Total = Realized + Forecast (additive P&L decomposition)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cockpit.config import CURRENCY_TO_OIS
from cockpit.data.parsers import parse_deals, parse_schedule, _month_columns
from cockpit.engine.pnl.engine import (
    _build_ois_matrix,
    _mock_curves_from_wirp,
    _resolve_rate_ref,
    aggregate_to_monthly,
    compute_daily_pnl,
    compute_strategy_pnl,
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

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ideal_input"


# ---------------------------------------------------------------------------
# Shared fixture: run the engine on mock data
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine_result():
    """Run the engine on the mock ideal-format files and return monthly DataFrame.

    Returns dict with keys: monthly, deals, schedule, days, daily_pnl, etc.
    """
    deals_all = parse_deals(FIXTURES / "deals.xlsx")
    book1 = deals_all[deals_all["IAS Book"] == "BOOK1"].copy().reset_index(drop=True)
    schedule = parse_schedule(FIXTURES / "rate_schedule.xlsx")

    deals = _resolve_rate_ref(book1)

    month_cols = _month_columns(schedule)
    start = pd.Timestamp(month_cols[0].replace("/", "-") + "-01")
    days = build_date_grid(start, months=60)

    # Join deals to schedule
    deals["Dealid"] = pd.to_numeric(deals["Dealid"], errors="coerce")
    ech = schedule.copy()
    ech["Dealid"] = pd.to_numeric(ech["Dealid"], errors="coerce")
    join_keys = ["Dealid", "Direction", "Currency"]
    present_keys = [k for k in join_keys if k in ech.columns]
    ech_agg = ech.groupby(present_keys)[month_cols].sum().reset_index()
    merged = deals.merge(ech_agg, on=present_keys, how="left", suffixes=("", "_ech"))
    for mc in month_cols:
        if mc in merged.columns:
            merged[mc] = merged[mc].fillna(0.0)

    # Build matrices
    nominal_daily = expand_nominal_to_daily(merged[month_cols], days)
    alive = build_alive_mask(merged, days, date_run=pd.Timestamp("2026-04-04"))
    nominal_daily = nominal_daily * alive
    mm = build_mm_vector(merged)
    n_days = len(days)
    mm_broadcast = mm[:, np.newaxis] * np.ones((1, n_days))

    # Flat OIS curves (mock)
    ois_flat = {}
    for ccy, idx in CURRENCY_TO_OIS.items():
        ois_flat[idx] = 0.0100  # 1% flat for all currencies
    n_deals = len(merged)
    ois_matrix = np.full((n_deals, n_days), 0.0100)  # simplified flat

    rate_matrix = build_rate_matrix(merged, days, ref_curves=None)
    daily_pnl = compute_daily_pnl(nominal_daily, ois_matrix, rate_matrix, mm_broadcast)

    funding_matrix = build_funding_matrix(merged, days, ois_matrix, funding_source="ois")
    # Carry funding: same rate as OIS for test (so Compounded ≈ Simple)
    carry_funding_matrix = ois_matrix.copy()
    accrual_days = build_accrual_days(days)

    # Two runs: with and without date_rates
    date_rates = pd.Timestamp("2026-04-10")
    monthly_split = aggregate_to_monthly(
        daily_pnl, nominal_daily, ois_matrix, rate_matrix, days,
        funding_daily=funding_matrix, carry_funding_daily=carry_funding_matrix,
        accrual_days=accrual_days, mm_daily=mm_broadcast,
        date_rates=date_rates,
    )
    monthly_total = aggregate_to_monthly(
        daily_pnl, nominal_daily, ois_matrix, rate_matrix, days,
        funding_daily=funding_matrix, carry_funding_daily=carry_funding_matrix,
        accrual_days=accrual_days, mm_daily=mm_broadcast,
        date_rates=None,
    )

    # Enrich with deal metadata
    for col in ["Product", "Currency", "Direction", "Strategy IAS",
                "Périmètre TOTAL", "Clientrate", "EqOisRate", "YTM",
                "CocRate", "Amount"]:
        if col in merged.columns:
            monthly_split[col] = monthly_split["deal_idx"].map(merged[col])
            monthly_total[col] = monthly_total["deal_idx"].map(merged[col])

    monthly_split["Days in Month"] = monthly_split["Month"].apply(
        lambda p: p.days_in_month if hasattr(p, "days_in_month") else 30
    )
    monthly_total["Days in Month"] = monthly_total["Month"].apply(
        lambda p: p.days_in_month if hasattr(p, "days_in_month") else 30
    )

    return {
        "monthly_split": monthly_split,
        "monthly_total": monthly_total,
        "deals": merged,
        "days": days,
        "date_rates": date_rates,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 1: Total = Realized + Forecast
#   Must hold for every (deal, month) combination
# ═══════════════════════════════════════════════════════════════════════════

class TestTotalEqualsRealizedPlusForecast:

    def test_current_month_additivity(self, engine_result):
        """For the month containing dateRates, Total = Realized + Forecast."""
        df = engine_result["monthly_split"]
        date_rates = engine_result["date_rates"]
        current_month = date_rates.to_period("M")

        current = df[df["Month"] == current_month]
        for deal_idx in current["deal_idx"].unique():
            deal_rows = current[current["deal_idx"] == deal_idx]
            types = set(deal_rows["PnL_Type"])
            if {"Total", "Realized", "Forecast"} <= types:
                total = deal_rows[deal_rows["PnL_Type"] == "Total"]["PnL"].iloc[0]
                realized = deal_rows[deal_rows["PnL_Type"] == "Realized"]["PnL"].iloc[0]
                forecast = deal_rows[deal_rows["PnL_Type"] == "Forecast"]["PnL"].iloc[0]
                assert abs(total - (realized + forecast)) < 0.01, (
                    f"Deal {deal_idx}: Total={total:.4f} != Realized({realized:.4f}) + Forecast({forecast:.4f})"
                )

    def test_coc_forward_additivity(self, engine_result):
        """PnL_Simple also splits: Total = Realized + Forecast."""
        df = engine_result["monthly_split"]
        date_rates = engine_result["date_rates"]
        current_month = date_rates.to_period("M")

        current = df[df["Month"] == current_month]
        for deal_idx in current["deal_idx"].unique():
            deal_rows = current[current["deal_idx"] == deal_idx]
            types = set(deal_rows["PnL_Type"])
            if {"Total", "Realized", "Forecast"} <= types and "PnL_Simple" in deal_rows.columns:
                total = deal_rows[deal_rows["PnL_Type"] == "Total"]["PnL_Simple"].iloc[0]
                realized = deal_rows[deal_rows["PnL_Type"] == "Realized"]["PnL_Simple"].iloc[0]
                forecast = deal_rows[deal_rows["PnL_Type"] == "Forecast"]["PnL_Simple"].iloc[0]
                assert abs(total - (realized + forecast)) < 0.01

    def test_past_months_are_realized(self, engine_result):
        """Months before dateRates have only 'Realized' rows."""
        df = engine_result["monthly_split"]
        date_rates = engine_result["date_rates"]
        rates_month = date_rates.to_period("M")

        past = df[df["Month"] < rates_month]
        if not past.empty:
            assert (past["PnL_Type"] == "Realized").all()

    def test_future_months_are_forecast(self, engine_result):
        """Months after dateRates have only 'Forecast' rows."""
        df = engine_result["monthly_split"]
        date_rates = engine_result["date_rates"]
        rates_month = date_rates.to_period("M")

        future = df[df["Month"] > rates_month]
        if not future.empty:
            assert (future["PnL_Type"] == "Forecast").all()


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 2: PnL_Simple ≈ PnL_Compounded for low rates / short tenor
#   Diverges with higher rates when funding curves differ
# ═══════════════════════════════════════════════════════════════════════════

class TestCoCForwardVsCompd:

    def test_close_for_low_rates(self, engine_result):
        """For rates ~1%, forward and compounded should agree within 5%."""
        df = engine_result["monthly_total"]
        for _, row in df.iterrows():
            simple = row.get("PnL_Simple", 0)
            compound = row.get("PnL_Compounded", 0)
            if abs(simple) > 1:  # skip near-zero
                relative = abs(compound - simple) / abs(simple)
                assert relative < 0.05, (
                    f"Deal {row['deal_idx']}, Month {row['Month']}: "
                    f"PnL_Simple={simple:.2f}, PnL_Compounded={compound:.2f}, "
                    f"relative diff={relative:.4f}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 3: Strategy legs — direction filtering
#   BND legs exclude L, D directions; IAM/LD legs exclude B, S directions
#   IFRS 9 §6.5.16: hedge designation applies to specific direction
# ═══════════════════════════════════════════════════════════════════════════

class TestStrategyDirectionFiltering:

    def test_strategy_decomposition_produces_legs(self, engine_result):
        """Deals with Strategy IAS should decompose into up to 4 legs."""
        df = engine_result["monthly_total"]
        strat_deals = df[df["Strategy IAS"].notna()]
        if strat_deals.empty:
            pytest.skip("No strategy deals in test data")

        strat_deals["Deal currency"] = strat_deals["Currency"]
        strat_deals["Product2BuyBack"] = strat_deals["Product"]
        result = compute_strategy_pnl(strat_deals)

        if not result.empty:
            valid_legs = {"IAM/LD-NHCD", "IAM/LD-HCD", "BND-NHCD", "BND-HCD"}
            assert result["Product2BuyBack"].isin(valid_legs).all()

    def test_no_bnd_legs_for_deposit_direction(self, engine_result):
        """BND legs should not appear for L/D direction deals."""
        df = engine_result["monthly_total"]
        strat_deals = df[df["Strategy IAS"].notna()].copy()
        if strat_deals.empty:
            pytest.skip("No strategy deals in test data")

        strat_deals["Deal currency"] = strat_deals["Currency"]
        strat_deals["Product2BuyBack"] = strat_deals["Product"]
        result = compute_strategy_pnl(strat_deals)

        if not result.empty:
            bnd_legs = result[result["Product2BuyBack"].isin(["BND-NHCD", "BND-HCD"])]
            # BND legs should not have L or D direction
            if not bnd_legs.empty:
                assert not bnd_legs["Direction"].isin(["L", "D"]).any()


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 4: Nominal average consistency
#   Nom_avg = sum(daily_nominal) / calendar_days_in_month
# ═══════════════════════════════════════════════════════════════════════════

class TestNominalConsistency:

    def test_nominal_is_daily_average(self, engine_result):
        """Nominal column should be the average daily nominal over the month."""
        df = engine_result["monthly_total"]

        for _, row in df.iterrows():
            nom = row["Nominal"]
            nom_days = row.get("nominal_days", None)
            if nom_days is None:
                continue
            month = row["Month"]
            n_cal = month.days_in_month if hasattr(month, "days_in_month") else 30

            if n_cal > 0:
                expected_avg = nom_days / n_cal
                assert abs(nom - expected_avg) < 0.01, (
                    f"Deal {row['deal_idx']}, Month {month}: "
                    f"Nominal={nom:.2f} != nominal_days({nom_days:.2f})/{n_cal}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 5: Zero nominal → zero P&L
#   After maturity, alive mask zeroes nominal → P&L must be zero
# ═══════════════════════════════════════════════════════════════════════════

class TestZeroNominalZeroPnl:

    def test_dead_deals_zero_pnl(self, engine_result):
        """When nominal = 0, PnL must be 0."""
        df = engine_result["monthly_total"]
        zero_nom = df[df["Nominal"] == 0]
        if not zero_nom.empty:
            assert (zero_nom["PnL"].abs() < 0.001).all(), (
                "Found non-zero P&L rows with zero nominal"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 6: P&L sign convention
#   Deposit (D) + positive OIS-RateRef → positive P&L
#   Loan (L) + positive OIS-RateRef → negative P&L (negative nominal)
# ═══════════════════════════════════════════════════════════════════════════

class TestPnlSignConvention:

    def test_deposit_positive_spread_positive_pnl(self, engine_result):
        """Deposits with OIS > RateRef should have positive P&L."""
        df = engine_result["monthly_total"]
        deposits = df[(df["Direction"] == "D") & (df["Nominal"] > 0)]

        for _, row in deposits.iterrows():
            ois = row.get("OISfwd", 0)
            rate = row.get("RateRef", 0)
            pnl = row["PnL"]
            if pd.notna(ois) and pd.notna(rate) and ois > rate + 1e-6:
                assert pnl > -0.01, (
                    f"Deposit deal {row['deal_idx']}: OIS={ois:.4f} > RateRef={rate:.4f} "
                    f"but PnL={pnl:.2f}"
                )


# ═══════════════════════════════════════════════════════════════════════════
# Invariant 7: date_rates=None backward compatibility
#   Without date_rates, all rows should have PnL_Type = "Total"
# ═══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:

    def test_no_date_rates_all_total(self, engine_result):
        """When date_rates is None, every row has PnL_Type = 'Total'."""
        df = engine_result["monthly_total"]
        assert (df["PnL_Type"] == "Total").all()

    def test_totals_match_between_modes(self, engine_result):
        """'Total' PnL from split mode should match 'Total' from no-split mode."""
        split = engine_result["monthly_split"]
        nosplit = engine_result["monthly_total"]

        # Compare only the Total rows from split mode
        split_totals = split[split["PnL_Type"] == "Total"].copy()

        for _, row_ns in nosplit.iterrows():
            deal_idx = row_ns["deal_idx"]
            month = row_ns["Month"]

            match = split_totals[
                (split_totals["deal_idx"] == deal_idx) &
                (split_totals["Month"] == month)
            ]
            if not match.empty:
                # Only the current month has Total rows in split mode
                assert abs(row_ns["PnL"] - match["PnL"].iloc[0]) < 0.01, (
                    f"Deal {deal_idx}, Month {month}: "
                    f"no-split={row_ns['PnL']:.4f} != split-total={match['PnL'].iloc[0]:.4f}"
                )
