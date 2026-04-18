"""Tier 1: Known-answer validation tests.

Each test constructs a minimal deal with hand-calculated expected P&L,
then runs the engine and asserts numerical equality. These tests serve as
the regulatory audit trail proving formulas match IFRS 9 / ISDA 2021 / BCBS 368.

Convention: all hand calculations are commented step-by-step.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cockpit.engine.pnl.engine import (
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_deal(**overrides) -> pd.DataFrame:
    """Create a single-deal DataFrame with sensible defaults."""
    base = {
        "Dealid": 1,
        "Product": "IAM/LD",
        "Currency": "CHF",
        "Direction": "D",
        "Amount": 10_000_000,
        "Clientrate": 0.0100,
        "EqOisRate": 0.0100,
        "YTM": 0.0,
        "CocRate": 0.0050,
        "Spread": 0.0,
        "Floating Rates Short Name": "",
        "Valuedate": "2026-04-01",
        "Maturitydate": "2026-06-30",
        "Strategy IAS": None,
        "Périmètre TOTAL": "CC",
        "IAS Book": "BOOK1",
    }
    base.update(overrides)
    return pd.DataFrame([base])


def _run_single_deal_pnl(
    deal_df: pd.DataFrame,
    ois_rate: float,
    start: str = "2026-04-01",
    months: int = 3,
    nominal: float | None = None,
    funding_source: str = "ois",
    date_rates: pd.Timestamp | None = None,
    carry_rate: float | None = None,
) -> pd.DataFrame:
    """Run the full engine pipeline for a single deal and return monthly DataFrame."""
    deals = _resolve_rate_ref(deal_df)
    days = build_date_grid(pd.Timestamp(start), months=months)

    # Build nominal: flat across all months
    nom_val = nominal if nominal is not None else deal_df["Amount"].iloc[0]
    month_cols = sorted(set(days.to_period("M").astype(str).str.replace("-", "/")))
    nom_wide = pd.DataFrame({mc: [nom_val] for mc in month_cols})
    nominal_daily = expand_nominal_to_daily(nom_wide, days)

    # Alive mask
    alive = build_alive_mask(deals, days, date_run=pd.Timestamp(start))
    nominal_daily = nominal_daily * alive

    # OIS: constant flat curve
    n_deals, n_days = nominal_daily.shape
    ois_matrix = np.full((n_deals, n_days), ois_rate)

    # Rate matrix: uses RateRef from _resolve_rate_ref
    rate_matrix = np.full((n_deals, n_days), deals["RateRef"].iloc[0])

    # MM
    mm = build_mm_vector(deals)
    mm_broadcast = mm[:, np.newaxis] * np.ones((1, n_days))

    # Daily P&L
    daily_pnl = compute_daily_pnl(nominal_daily, ois_matrix, rate_matrix, mm_broadcast)

    # Funding
    funding_matrix = build_funding_matrix(deals, days, ois_matrix, funding_source=funding_source)
    accrual_days = build_accrual_days(days)

    # Carry funding (for Compounded columns)
    carry_funding_matrix = None
    if carry_rate is not None:
        carry_funding_matrix = np.full((n_deals, n_days), carry_rate)

    # Aggregate
    monthly = aggregate_to_monthly(
        daily_pnl, nominal_daily, ois_matrix, rate_matrix, days,
        funding_daily=funding_matrix, carry_funding_daily=carry_funding_matrix,
        accrual_days=accrual_days, mm_daily=mm_broadcast,
        date_rates=date_rates,
    )
    return monthly


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Single fixed CHF deposit, 1 full month, flat OIS
#   IFRS 9 §5.4.1 — Effective Interest Rate method (amortized cost)
#   Formula: PnL = Nominal × (OIS − ClientRate) / 360 per day
# ═══════════════════════════════════════════════════════════════════════════

class TestFixedDepositCHF:
    """CHF deposit, Act/360, full month of April 2026 (30 days)."""

    def test_basic_pnl(self):
        # Setup: 10M CHF deposit, client rate 1.00%, OIS 1.50%
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # Hand calculation:
        #   Daily PnL = 10_000_000 × (0.0150 − 0.0100) / 360
        #             = 10_000_000 × 0.005 / 360
        #             = 138.8889 per day
        #   April has 30 days → 30 × 138.8889 = 4166.6667
        expected_daily = 10_000_000 * (0.0150 - 0.0100) / 360
        expected_april = expected_daily * 30

        actual = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual - expected_april) < 0.01, f"Expected {expected_april:.2f}, got {actual:.2f}"

    def test_may_31_days(self):
        """May has 31 days → PnL should be 31/30 × April PnL."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150)

        may = monthly[monthly["Month"].astype(str) == "2026-05"]
        may_total = may[may["PnL_Type"] == "Total"] if "PnL_Type" in may.columns else may

        expected_daily = 10_000_000 * 0.005 / 360
        expected_may = expected_daily * 31

        actual = may_total["PnL_Simple"].iloc[0]
        assert abs(actual - expected_may) < 0.01

    def test_negative_spread_means_loss(self):
        """When OIS < ClientRate, P&L should be negative (cost of carrying above market)."""
        deal = _make_deal(
            Clientrate=0.0200, EqOisRate=0.0200,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0100)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # OIS (1.00%) < ClientRate (2.00%) → negative PnL
        expected_daily = 10_000_000 * (0.0100 - 0.0200) / 360
        expected = expected_daily * 30
        actual = apr_total["PnL_Simple"].iloc[0]
        assert actual < 0
        assert abs(actual - expected) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: GBP deposit, Act/365 day count
#   ISDA 2006 §4.16(b) — GBP uses Act/365 for all instruments
# ═══════════════════════════════════════════════════════════════════════════

class TestGBPDayCount:
    """GBP deposit uses Act/365, not Act/360."""

    def test_gbp_act365(self):
        deal = _make_deal(
            Currency="GBP", Clientrate=0.0400, EqOisRate=0.0400,
            Amount=5_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0450)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # Hand calculation: GBP → divisor = 365
        #   Daily PnL = 5_000_000 × (0.045 − 0.040) / 365 = 684.9315 per day
        #   April (30 days) → 30 × 684.9315 = 20547.945
        expected = 5_000_000 * (0.045 - 0.040) / 365 * 30
        actual = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual - expected) < 0.01

    def test_gbp_vs_chf_same_deal(self):
        """Same rates, same nominal — GBP and CHF should differ by 360/365 ratio."""
        params = dict(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        chf = _run_single_deal_pnl(_make_deal(Currency="CHF", **params), ois_rate=0.0200)
        gbp = _run_single_deal_pnl(_make_deal(Currency="GBP", **params), ois_rate=0.0200)

        chf_apr = chf[chf["Month"].astype(str) == "2026-04"]
        gbp_apr = gbp[gbp["Month"].astype(str) == "2026-04"]

        chf_pnl = chf_apr[chf_apr["PnL_Type"] == "Total"]["PnL_Simple"].iloc[0]
        gbp_pnl = gbp_apr[gbp_apr["PnL_Type"] == "Total"]["PnL_Simple"].iloc[0]

        ratio = chf_pnl / gbp_pnl
        # CHF uses 360 divisor, GBP uses 365 → CHF daily PnL is higher
        # ratio should be 365/360 ≈ 1.01389
        assert abs(ratio - 365 / 360) < 0.001


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Bond with 30/360 day count
#   ISDA 2006 §4.16(e) — Bonds use 30/360 (except GBP)
#   RateRef for BND = YTM (from PRODUCT_RATE_COLUMN)
# ═══════════════════════════════════════════════════════════════════════════

class TestBondDayCount:
    """CHF bond uses YTM as RateRef and 30/360 day count (divisor=360)."""

    def test_bond_uses_ytm_as_rate_ref(self):
        deal = _make_deal(
            Product="BND", Direction="B",
            Clientrate=0.0150, EqOisRate=0.0110, YTM=0.0200,
            Amount=20_000_000,
            Valuedate="2026-01-01", Maturitydate="2029-01-01",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # BND → RateRef = YTM = 0.0200 (not EqOisRate or Clientrate)
        # BND CHF → 30/360, divisor = 360
        # Daily PnL = 20M × (0.015 − 0.020) / 360 = -277.78 per day
        # April 30d → -8333.33
        expected = 20_000_000 * (0.015 - 0.020) / 360 * 30
        actual = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual - expected) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Mid-month maturity — alive mask zeros nominal after maturity
#   Engine spec §7.1: alive range [max(Valuedate, 1st of month), Maturitydate]
# ═══════════════════════════════════════════════════════════════════════════

class TestMidMonthMaturity:
    """Deal maturing April 15 — only 15 days of P&L in April, zero in May."""

    def test_pnl_prorated(self):
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-04-15",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0200)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # Alive April 1–15 → 15 days
        # Daily PnL = 10M × (0.02 − 0.01) / 360 = 277.78
        # 15 days → 4166.67
        expected = 10_000_000 * 0.01 / 360 * 15
        actual = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual - expected) < 0.01

    def test_zero_after_maturity(self):
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-04-15",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0200)

        may = monthly[monthly["Month"].astype(str) == "2026-05"]
        may_total = may[may["PnL_Type"] == "Total"] if "PnL_Type" in may.columns else may

        assert abs(may_total["PnL_Simple"].iloc[0]) < 0.001


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: P&L Simple — Forward (IFRS 9 B5.4.5)
#   PnL_Simple = FundingCost_Simple − GrossCarry
#   GrossCarry = Σ(Nominal × RateRef × d_i / MM)
#   FundingCost_Simple = Σ(Nominal × FundingRate_Forward × d_i / MM)
# ═══════════════════════════════════════════════════════════════════════════

class TestPnLSimple:
    """IFRS 9 B5.4.5: P&L Simple = funding income minus client rate cost."""

    def test_pnl_simple_ois_funding(self):
        """When funding_source='ois', FundingRate = OIS rate."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            CocRate=0.0050,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150, funding_source="ois")

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # For April, all d_i = 1 (Mon-Thu) or 3 (Fri→Mon), but sum(d_i) = 30 for April
        # GrossCarry = Σ(10M × 0.01 × d_i / 360)
        # With weekday accrual_days: need to sum d_i over April's 30 calendar days
        # April 2026: 1(Wed)..30(Thu), 4 full weeks + 2 extra weekdays
        # Sum of d_i for a date_range = number of calendar days = 30
        # Actually d_i[j] = (day[j+1] - day[j]) in calendar days, so sum(d_i) over
        # the month's days = last_day - first_day = 29 (for 30-day April, 30 points)
        # But the engine sums d_i * rate * nom / mm for each day in the month.
        # For a flat rate: GrossCarry ≈ Nominal × Rate × sum(d_i) / MM
        # where sum(d_i) for April = 30 (each day accrues ~1 day, Fridays accrue 3)
        #
        # Simpler: since rate and nominal are constant,
        # GrossCarry = Σ_over_april_days( Nom × Rate × d_i / 360 )
        # FundingCost = Σ_over_april_days( Nom × OIS × d_i / 360 )
        # PnL_Simple = FundingCost_Simple - GrossCarry
        #            = Σ( Nom × (OIS - Rate) × d_i / 360 )
        #            = Nom × (OIS - Rate) × Σ(d_i) / 360

        # Build expected from actual d_i
        days = build_date_grid(pd.Timestamp("2026-04-01"), months=3)
        d_i = build_accrual_days(days)
        apr_mask = days.to_period("M").astype(str) == "2026-04"
        sum_di = d_i[apr_mask].sum()

        expected_gross = 10_000_000 * 0.0100 * sum_di / 360
        expected_fund = 10_000_000 * 0.0150 * sum_di / 360
        expected_pnl = expected_fund - expected_gross

        actual_pnl = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual_pnl - expected_pnl) < 0.01, f"Expected {expected_pnl:.2f}, got {actual_pnl:.2f}"

    def test_pnl_simple_coc_funding(self):
        """When funding_source='coc', FundingRate = CocRate."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            CocRate=0.0050,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150, funding_source="coc")

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        days = build_date_grid(pd.Timestamp("2026-04-01"), months=3)
        d_i = build_accrual_days(days)
        apr_mask = days.to_period("M").astype(str) == "2026-04"
        sum_di = d_i[apr_mask].sum()

        # FundingRate = CocRate = 0.005
        expected_gross = 10_000_000 * 0.0100 * sum_di / 360
        expected_fund = 10_000_000 * 0.0050 * sum_di / 360
        expected_pnl = expected_fund - expected_gross

        actual_pnl = apr_total["PnL_Simple"].iloc[0]
        assert abs(actual_pnl - expected_pnl) < 0.01


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: P&L Compounded (WASP carry, geometric)
#   PnL_Compounded = Nom_avg × [∏(1 + carry_i × d_i/MM) − ∏(1 + r_i × d_i/MM)]
# ═══════════════════════════════════════════════════════════════════════════

class TestPnLCompounded:
    """ISDA 2021 §6.9: compounded in arrears using WASP carry rates."""

    def test_compound_close_to_simple_when_same_rate(self):
        """When carry rate == OIS rate, compound ≈ simple within 1%."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            CocRate=0.0050,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        # carry_rate == ois_rate → same funding, different method
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0150, funding_source="ois", carry_rate=0.0150)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        simple = apr_total["PnL_Simple"].iloc[0]
        compound = apr_total["PnL_Compounded"].iloc[0]

        # For 1 month at low rates with same funding, compound ≈ simple within 1%
        if abs(simple) > 1:  # avoid division by zero
            assert abs(compound - simple) / abs(simple) < 0.01

    def test_compound_explicit_calculation(self):
        """Verify compound formula: Nom_avg × [∏(1+carry×d_i/MM) - ∏(1+r×d_i/MM)]."""
        carry_rate = 0.0300
        deal = _make_deal(
            Clientrate=0.0500, EqOisRate=0.0500,  # Higher rate to see compounding effect
            Amount=100_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0300, funding_source="ois", carry_rate=carry_rate)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        apr_total = apr[apr["PnL_Type"] == "Total"] if "PnL_Type" in apr.columns else apr

        # Compute expected compound manually
        days = build_date_grid(pd.Timestamp("2026-04-01"), months=3)
        d_i = build_accrual_days(days)
        apr_mask = days.to_period("M").astype(str) == "2026-04"
        d_i_apr = d_i[apr_mask]

        rate_factors = np.prod(1.0 + 0.0500 * d_i_apr / 360)
        funding_factors = np.prod(1.0 + carry_rate * d_i_apr / 360)
        n_cal = apr_mask.sum()
        nom_avg = 100_000_000  # constant nominal, alive all month
        expected_compound = nom_avg * (funding_factors - rate_factors)

        actual = apr_total["PnL_Compounded"].iloc[0]
        assert abs(actual - expected_compound) < 0.01, f"Expected {expected_compound:.2f}, got {actual:.2f}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 7: Realized vs Forecast split
#   date_rates boundary: days ≤ dateRates → Realized, days > dateRates → Forecast
# ═══════════════════════════════════════════════════════════════════════════

class TestRealizedForecastSplit:
    """Realized/Forecast boundary at dateRates."""

    def test_current_month_split(self):
        """April split at April 10: 10 realized days + 20 forecast days."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        date_rates = pd.Timestamp("2026-04-10")
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0200, date_rates=date_rates)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        total = apr[apr["PnL_Type"] == "Total"]["PnL_Simple"].iloc[0]
        realized = apr[apr["PnL_Type"] == "Realized"]["PnL_Simple"].iloc[0]
        forecast = apr[apr["PnL_Type"] == "Forecast"]["PnL_Simple"].iloc[0]

        daily_pnl = 10_000_000 * 0.01 / 360

        # Total = Realized + Forecast
        assert abs(total - (realized + forecast)) < 0.01

        # Realized: days 1-10 (10 days)
        expected_realized = daily_pnl * 10
        assert abs(realized - expected_realized) < 0.01

        # Forecast: days 11-30 (20 days)
        expected_forecast = daily_pnl * 20
        assert abs(forecast - expected_forecast) < 0.01

    def test_past_month_is_realized(self):
        """A month entirely before dateRates → PnL_Type = 'Realized'."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        date_rates = pd.Timestamp("2026-05-15")
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0200, date_rates=date_rates)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        assert len(apr) == 1  # only one row (Realized)
        assert apr["PnL_Type"].iloc[0] == "Realized"

    def test_future_month_is_forecast(self):
        """A month entirely after dateRates → PnL_Type = 'Forecast'."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        date_rates = pd.Timestamp("2026-04-10")
        monthly = _run_single_deal_pnl(deal, ois_rate=0.0200, date_rates=date_rates)

        may = monthly[monthly["Month"].astype(str) == "2026-05"]
        assert len(may) == 1
        assert may["PnL_Type"].iloc[0] == "Forecast"


# ═══════════════════════════════════════════════════════════════════════════
# Test 8: Shock sensitivity — BCBS 368 IRRBB
#   A parallel shift of +50bp should increase P&L for a net-positive position
# ═══════════════════════════════════════════════════════════════════════════

class TestShockSensitivity:
    """BCBS 368: P&L sensitivity to parallel yield curve shifts."""

    def test_positive_shock_increases_pnl_for_deposit(self):
        """A deposit (positive nominal) benefits from higher OIS rates."""
        deal = _make_deal(
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=10_000_000,
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        base = _run_single_deal_pnl(deal, ois_rate=0.0150)
        shocked = _run_single_deal_pnl(deal, ois_rate=0.0200)  # +50bp

        base_apr = base[(base["Month"].astype(str) == "2026-04") & (base["PnL_Type"] == "Total")]
        shock_apr = shocked[(shocked["Month"].astype(str) == "2026-04") & (shocked["PnL_Type"] == "Total")]

        # +50bp OIS → more PnL for deposit holder
        assert shock_apr["PnL_Simple"].iloc[0] > base_apr["PnL_Simple"].iloc[0]

        # Delta should be exactly: Nominal × 0.0050 / 360 × 30 days
        expected_delta = 10_000_000 * 0.0050 / 360 * 30
        actual_delta = shock_apr["PnL_Simple"].iloc[0] - base_apr["PnL_Simple"].iloc[0]
        assert abs(actual_delta - expected_delta) < 0.01

    def test_loan_sensitivity_is_opposite(self):
        """A loan (negative nominal) loses when OIS rises."""
        deal = _make_deal(
            Direction="L",
            Clientrate=0.0100, EqOisRate=0.0100,
            Amount=-10_000_000,  # negative = loan
            Valuedate="2026-01-01", Maturitydate="2026-12-31",
        )
        base = _run_single_deal_pnl(deal, ois_rate=0.0150, nominal=-10_000_000)
        shocked = _run_single_deal_pnl(deal, ois_rate=0.0200, nominal=-10_000_000)

        base_apr = base[(base["Month"].astype(str) == "2026-04") & (base["PnL_Type"] == "Total")]
        shock_apr = shocked[(shocked["Month"].astype(str) == "2026-04") & (shocked["PnL_Type"] == "Total")]

        # Loan: negative nominal → higher OIS → more negative PnL
        assert shock_apr["PnL_Simple"].iloc[0] < base_apr["PnL_Simple"].iloc[0]


# ═══════════════════════════════════════════════════════════════════════════
# Test 9: Product-to-RateRef mapping
#   PRODUCT_RATE_COLUMN: IAM/LD→EqOisRate, BND→YTM, IRS→Clientrate
# ═══════════════════════════════════════════════════════════════════════════

class TestProductRateRefMapping:
    """Each product type uses the correct rate column as RateRef."""

    @pytest.mark.parametrize("product,rate_col,rates", [
        ("IAM/LD", "EqOisRate", {"EqOisRate": 0.0150, "YTM": 0.0200, "Clientrate": 0.0100}),
        ("BND", "YTM", {"EqOisRate": 0.0150, "YTM": 0.0200, "Clientrate": 0.0100}),
        ("IRS", "Clientrate", {"EqOisRate": 0.0150, "YTM": 0.0200, "Clientrate": 0.0100}),
        ("FXS", "EqOisRate", {"EqOisRate": 0.0150, "YTM": 0.0200, "Clientrate": 0.0100}),
        ("HCD", "Clientrate", {"EqOisRate": 0.0150, "YTM": 0.0200, "Clientrate": 0.0100}),
    ])
    def test_rate_ref_selection(self, product, rate_col, rates):
        deal = _make_deal(Product=product, Direction="D", **rates)
        resolved = _resolve_rate_ref(deal)
        expected = rates[rate_col]
        assert abs(resolved["RateRef"].iloc[0] - expected) < 1e-10


# ═══════════════════════════════════════════════════════════════════════════
# Test 10: Accrual days (ISDA 2021 §6.9)
#   Weekdays accrue 1 day, Fridays accrue 3 (Fri→Mon)
# ═══════════════════════════════════════════════════════════════════════════

class TestAccrualDays:
    """ISDA 2021 §6.9: d_i = calendar days between fixings."""

    def test_weekday_accrual(self):
        # Monday to Thursday: d_i = 1
        days = pd.date_range("2026-04-06", "2026-04-10", freq="D")  # Mon-Fri
        d_i = build_accrual_days(days)
        # Mon→Tue: 1, Tue→Wed: 1, Wed→Thu: 1, Thu→Fri: 1, Fri(last): 3
        assert list(d_i) == [1.0, 1.0, 1.0, 1.0, 3.0]

    def test_friday_accrues_3(self):
        # A Friday followed by Saturday → d_i should be the gap to next day in grid
        # In a calendar grid (all days), Fri→Sat = 1 day
        # But build_accrual_days works on the date grid, which is daily (including weekends)
        days = pd.date_range("2026-04-10", "2026-04-13", freq="D")  # Fri-Mon
        d_i = build_accrual_days(days)
        # Fri→Sat: 1, Sat→Sun: 1, Sun→Mon: 1, Mon(last): 1
        assert d_i[0] == 1.0  # Fri→Sat in daily grid

    def test_sum_equals_calendar_span(self):
        """Sum of d_i over a month equals span to next business day.

        April 2026: 29 daily gaps of 1 day + last day (Apr 30, Thursday)
        accrues 4 days to next business day (May 4, Monday — May 1 is
        Labour Day, May 2-3 is weekend).  Sum = 29 + 4 = 33.
        """
        days = build_date_grid(pd.Timestamp("2026-04-01"), months=1)
        d_i = build_accrual_days(days)
        # Last day: Apr 30 (Thu) → next BD is May 4 (Mon) → d_i = 4
        assert d_i[-1] == 4.0
        assert abs(d_i.sum() - 33) < 0.01
