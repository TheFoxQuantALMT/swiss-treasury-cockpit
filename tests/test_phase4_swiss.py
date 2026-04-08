"""Tests for Phase 4: Swiss-specific enhancements."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pnl_engine.snb_reserves import compute_snb_reserves
from pnl_engine.saron import compound_saron_daily, apply_lookback_shift, validate_against_snb
from cockpit.data.parsers.scenarios import (
    get_currency_specific_scenarios,
    get_finma_scenarios,
    get_snb_reversal_scenario,
    BCBS_CURRENCY_MAGNITUDES,
)
from pnl_engine.config import FUNDING_SPREAD_BY_PRODUCT, SNB_RESERVE_RATIO


# ============================================================================
# S1: SNB Minimum Reserves
# ============================================================================

class TestSnbReserves:
    def test_basic_calculation(self):
        deals = pd.DataFrame({
            "Dealid": ["D1"],
            "Direction": ["D"],
            "Currency": ["CHF"],
            "Product": ["KK"],
            "Amount": [10_000_000],
        })
        result = compute_snb_reserves(deals, ois_rate=0.015)
        assert result["has_data"]
        assert result["sight_liabilities"] == 10_000_000
        assert result["gross_requirement"] == 250_000  # 2.5% of 10M
        assert result["opportunity_cost_annual"] > 0

    def test_hqla_offset(self):
        deals = pd.DataFrame({
            "Direction": ["D"], "Currency": ["CHF"], "Product": ["KK"], "Amount": [10_000_000],
        })
        result = compute_snb_reserves(deals, ois_rate=0.015, hqla_amount=1_000_000)
        # HQLA offset = 20% of 1M = 200K
        assert result["hqla_offset"] == 200_000
        assert result["net_requirement"] == 50_000  # 250K - 200K

    def test_empty_deals(self):
        assert not compute_snb_reserves(None)["has_data"]

    def test_non_chf_excluded(self):
        deals = pd.DataFrame({
            "Direction": ["D", "D"], "Currency": ["CHF", "EUR"],
            "Product": ["KK", "KK"], "Amount": [10_000_000, 5_000_000],
        })
        result = compute_snb_reserves(deals)
        assert result["sight_liabilities"] == 10_000_000  # EUR excluded

    def test_reserve_ratio_config(self):
        assert SNB_RESERVE_RATIO == 0.025


# ============================================================================
# S2: SARON Compounding
# ============================================================================

class TestSaronCompounding:
    def test_flat_rates(self):
        # 30 days at 1.5% flat → compounded ≈ 1.5%
        rates = np.full(30, 0.015)
        result = compound_saron_daily(rates)
        assert abs(result["compounded_rate"] - 0.015) < 0.001
        assert result["n_days"] == 30

    def test_zero_rates(self):
        rates = np.zeros(30)
        result = compound_saron_daily(rates)
        assert result["compounded_rate"] == 0.0

    def test_negative_rates(self):
        rates = np.full(30, -0.0075)
        result = compound_saron_daily(rates)
        assert result["compounded_rate"] < 0

    def test_accrued_interest(self):
        rates = np.full(30, 0.015)
        result = compound_saron_daily(rates, notional=1_000_000)
        assert result["accrued_interest"] > 0

    def test_empty_rates(self):
        result = compound_saron_daily(np.array([]))
        assert result["n_days"] == 0


class TestLookbackShift:
    def test_2day_shift(self):
        rates = np.array([0.01, 0.02, 0.03, 0.04, 0.05])
        shifted = apply_lookback_shift(rates, lookback_days=2)
        assert shifted[0] == 0.01  # flat extrapolation
        assert shifted[1] == 0.01
        assert shifted[2] == 0.01  # rate from day 0
        assert shifted[3] == 0.02
        assert shifted[4] == 0.03

    def test_zero_lookback(self):
        rates = np.array([0.01, 0.02, 0.03])
        shifted = apply_lookback_shift(rates, lookback_days=0)
        np.testing.assert_array_equal(shifted, rates)


class TestSaronValidation:
    def test_within_tolerance(self):
        result = validate_against_snb(0.01500, 0.01502, tolerance_bp=0.5)
        assert result["within_tolerance"]
        assert result["diff_bp"] < 0.5

    def test_outside_tolerance(self):
        result = validate_against_snb(0.01500, 0.01600, tolerance_bp=0.5)
        assert not result["within_tolerance"]


# ============================================================================
# S3: SNB Reversal Scenario
# ============================================================================

class TestSnbReversal:
    def test_scenario_structure(self):
        df = get_snb_reversal_scenario()
        assert not df.empty
        assert set(df.columns) >= {"scenario", "tenor", "CHF", "EUR"}
        assert (df["scenario"] == "snb_reversal").all()

    def test_chf_negative(self):
        df = get_snb_reversal_scenario()
        assert (df["CHF"] == -50).all()

    def test_eur_moderate(self):
        df = get_snb_reversal_scenario()
        assert (df["EUR"] == -25).all()

    def test_usd_gbp_zero(self):
        df = get_snb_reversal_scenario()
        assert (df["USD"] == 0).all()
        assert (df["GBP"] == 0).all()


# ============================================================================
# S4: Pfandbriefbank Funding Spread
# ============================================================================

class TestPfandbriefSpread:
    def test_mortgage_spread_defined(self):
        assert "IAM/LD" in FUNDING_SPREAD_BY_PRODUCT
        assert FUNDING_SPREAD_BY_PRODUCT["IAM/LD"] == -0.0015  # -15bp


# ============================================================================
# S5: FINMA Scenarios
# ============================================================================

class TestFinmaScenarios:
    def test_scenario_count(self):
        df = get_finma_scenarios()
        scenarios = df["scenario"].unique()
        assert len(scenarios) == 4

    def test_scenario_names(self):
        df = get_finma_scenarios()
        names = set(df["scenario"].unique())
        assert "finma_parallel_up" in names
        assert "finma_steepener" in names

    def test_chf_magnitudes(self):
        df = get_finma_scenarios()
        up = df[df["scenario"] == "finma_parallel_up"]
        assert (up["CHF"] == 150).all()
        assert (up["EUR"] == 200).all()


# ============================================================================
# S6: Currency-Specific BCBS Magnitudes
# ============================================================================

class TestCurrencySpecificBcbs:
    def test_magnitude_table(self):
        assert BCBS_CURRENCY_MAGNITUDES["CHF"]["parallel"] == 150
        assert BCBS_CURRENCY_MAGNITUDES["EUR"]["parallel"] == 200
        assert BCBS_CURRENCY_MAGNITUDES["GBP"]["parallel"] == 250

    def test_scenario_structure(self):
        df = get_currency_specific_scenarios()
        assert not df.empty
        assert set(df.columns) >= {"scenario", "tenor", "CHF", "EUR", "USD", "GBP"}

    def test_chf_smaller_than_eur(self):
        df = get_currency_specific_scenarios()
        up = df[df["scenario"] == "parallel_up"]
        assert (up["CHF"] < up["EUR"]).all()

    def test_gbp_largest(self):
        df = get_currency_specific_scenarios()
        up = df[df["scenario"] == "parallel_up"]
        assert (up["GBP"] >= up["EUR"]).all()

    def test_short_decays_to_zero(self):
        df = get_currency_specific_scenarios()
        short_up = df[df["scenario"] == "short_up"]
        # At 30Y tenor, short shock should be 0
        row_30y = short_up[short_up["tenor"] == "30Y"]
        assert row_30y.iloc[0]["CHF"] == 0
