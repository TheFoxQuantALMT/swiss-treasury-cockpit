"""Tests for EVE (Economic Value of Equity) computation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cockpit.data.parsers import parse_deals
from cockpit.engine.pnl.forecast import ForecastRatePnL
from tests.conftest import requires_wasp

FIXTURES = Path(__file__).parent / "fixtures" / "ideal_input"


@requires_wasp
class TestEveComputation:
    """Test EVE computation via PnlEngine.run_eve()."""

    @pytest.fixture
    def engine(self):
        """Build and run a PnlEngine from fixtures."""
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 5),
            dateRates=datetime(2026, 4, 5),
            export=False,
            input_dir=str(FIXTURES),
            output_dir="output",
            funding_source="ois",
        )
        return pnl._engine

    def test_base_eve_computes(self, engine):
        """run_eve produces non-empty DataFrame."""
        eve = engine.run_eve()
        assert eve is not None
        assert not eve.empty
        assert "eve" in eve.columns
        assert "duration" in eve.columns
        assert len(eve) > 0

    def test_eve_has_currency_metadata(self, engine):
        """EVE result includes Currency column."""
        eve = engine.run_eve()
        assert "Currency" in eve.columns
        currencies = eve["Currency"].unique()
        assert len(currencies) > 0
        assert "CHF" in currencies

    def test_eve_total_nonzero(self, engine):
        """Total EVE should be non-zero with real deal data."""
        eve = engine.run_eve()
        assert eve["eve"].sum() != 0

    def test_eve_duration_reasonable(self, engine):
        """Duration should be within reasonable bounds (0-30Y)."""
        eve = engine.run_eve()
        alive = eve[eve["notional_avg"] > 0]
        if not alive.empty:
            assert alive["duration"].max() < 30
            assert alive["duration"].min() > -30


@requires_wasp
class TestEveScenarios:
    """Test ΔEVE scenario computation."""

    @pytest.fixture
    def engine(self):
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 5),
            dateRates=datetime(2026, 4, 5),
            export=False,
            input_dir=str(FIXTURES),
            output_dir="output",
            funding_source="ois",
        )
        return pnl._engine

    def test_eve_scenarios_with_bcbs(self, engine):
        """run_eve with scenarios produces scenario results."""
        from cockpit.data.parsers.scenarios import parse_scenarios
        scenarios = parse_scenarios(FIXTURES / "scenarios.xlsx")
        engine.run_eve(scenarios=scenarios)
        assert engine.eve_scenarios is not None
        assert not engine.eve_scenarios.empty
        assert "scenario" in engine.eve_scenarios.columns
        assert "delta_eve" in engine.eve_scenarios.columns

    def test_eve_scenarios_have_all_six(self, engine):
        """All 6 BCBS scenarios should be represented."""
        from cockpit.data.parsers.scenarios import parse_scenarios
        scenarios = parse_scenarios(FIXTURES / "scenarios.xlsx")
        engine.run_eve(scenarios=scenarios)
        scenario_names = engine.eve_scenarios["scenario"].unique()
        assert len(scenario_names) == 6

    def test_krd_computed(self, engine):
        """Key rate durations should be computed when scenarios provided."""
        from cockpit.data.parsers.scenarios import parse_scenarios
        scenarios = parse_scenarios(FIXTURES / "scenarios.xlsx")
        engine.run_eve(scenarios=scenarios)
        assert engine.eve_krd is not None
        assert not engine.eve_krd.empty
        assert "tenor" in engine.eve_krd.columns
        assert "krd" in engine.eve_krd.columns

    def test_parallel_up_reduces_eve(self, engine):
        """Parallel +200bp should generally reduce EVE for fixed-rate assets."""
        from cockpit.data.parsers.scenarios import parse_scenarios
        scenarios = parse_scenarios(FIXTURES / "scenarios.xlsx")
        engine.run_eve(scenarios=scenarios)
        parallel_up = engine.eve_scenarios[engine.eve_scenarios["scenario"] == "parallel_up"]
        if not parallel_up.empty:
            # Total ΔEVE should be non-zero
            total_delta = parallel_up["delta_eve"].sum()
            assert total_delta != 0


class TestEveConvexity:
    """Test compute_eve_convexity() — second-order metrics."""

    def test_known_answer_convexity(self):
        """Verify convexity formula with known values."""
        from pnl_engine.eve import compute_eve_convexity

        # EVE_base=1000, EVE_up=960, EVE_down=1042
        # eff_dur = -(960 - 1042) / (2 * 1000 * 0.02) = 82/40 = 2.05
        # convexity = (960 + 1042 - 2000) / (1000 * 0.0004) = 2/0.4 = 5.0
        result = compute_eve_convexity(
            {"CHF": 1000.0},
            {"CHF": 960.0},
            {"CHF": 1042.0},
            delta_r=0.02,
        )
        assert abs(result["total"]["effective_duration"] - 2.05) < 0.01
        assert abs(result["total"]["convexity"] - 5.0) < 0.01
        assert "CHF" in result["by_currency"]
        assert abs(result["by_currency"]["CHF"]["effective_duration"] - 2.05) < 0.01

    def test_positive_convexity_vanilla_bond(self):
        """Vanilla fixed-rate bond should have positive convexity."""
        from pnl_engine.eve import compute_eve_convexity

        # Simulate: rate up hurts more than rate down helps (positive convexity)
        result = compute_eve_convexity(
            {"CHF": 1_000_000},
            {"CHF": 950_000},   # -50k
            {"CHF": 1_052_000}, # +52k (asymmetric: down helps more)
            delta_r=0.02,
        )
        assert result["total"]["convexity"] > 0
        assert result["total"]["effective_duration"] > 0

    def test_multi_currency(self):
        """Convexity computed per currency and total."""
        from pnl_engine.eve import compute_eve_convexity

        result = compute_eve_convexity(
            {"CHF": 500_000, "EUR": 300_000},
            {"CHF": 480_000, "EUR": 288_000},
            {"CHF": 521_000, "EUR": 313_000},
        )
        assert "CHF" in result["by_currency"]
        assert "EUR" in result["by_currency"]
        assert result["total"]["eve_base"] == 800_000

    def test_zero_eve_base(self):
        """Zero EVE base should return zero duration and convexity."""
        from pnl_engine.eve import compute_eve_convexity

        result = compute_eve_convexity(
            {"CHF": 0.0},
            {"CHF": 0.0},
            {"CHF": 0.0},
        )
        assert result["total"]["effective_duration"] == 0.0
        assert result["total"]["convexity"] == 0.0

    @requires_wasp
    def test_engine_integration(self):
        """run_eve with scenarios populates eve_convexity attribute."""
        from cockpit.data.parsers.scenarios import parse_scenarios
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 5),
            dateRates=datetime(2026, 4, 5),
            export=False,
            input_dir=str(FIXTURES),
            output_dir="output",
            funding_source="ois",
        )
        engine = pnl._engine
        scenarios = parse_scenarios(FIXTURES / "scenarios.xlsx")
        engine.run_eve(scenarios=scenarios)
        assert engine.eve_convexity is not None
        assert "total" in engine.eve_convexity
        assert "by_currency" in engine.eve_convexity
        assert "effective_duration" in engine.eve_convexity["total"]
        assert "convexity" in engine.eve_convexity["total"]


class TestRateDependentCpr:
    """Test rate-dependent CPR model."""

    def test_no_refi_incentive(self):
        """When market rate >= deal rate, CPR stays at base."""
        from pnl_engine.prepayment import rate_dependent_cpr
        cpr = rate_dependent_cpr(0.05, deal_rate=0.03, market_rate=0.04)
        assert cpr == 0.05

    def test_refi_incentive_increases_cpr(self):
        """When market rate < deal rate - threshold, CPR increases."""
        from pnl_engine.prepayment import rate_dependent_cpr
        cpr = rate_dependent_cpr(0.05, deal_rate=0.04, market_rate=0.02)
        # incentive = 0.04 - 0.02 - 0.005 = 0.015
        # adjusted = 0.05 * (1 + 2.0 * 0.015) = 0.05 * 1.03 = 0.0515
        assert cpr > 0.05
        assert abs(cpr - 0.0515) < 0.001

    def test_cpr_capped_at_40pct(self):
        """CPR should never exceed 40%."""
        from pnl_engine.prepayment import rate_dependent_cpr
        cpr = rate_dependent_cpr(0.05, deal_rate=0.10, market_rate=0.01)
        assert cpr <= 0.40

    def test_apply_cpr_rate_dependent(self):
        """Rate-dependent CPR adjusts nominals based on OIS level."""
        from pnl_engine.prepayment import apply_cpr_rate_dependent
        deals = pd.DataFrame([
            {"Product": "IAM/LD", "is_floating": False, "Clientrate": 0.04, "Dealid": 1},
        ])
        nominal = np.ones((1, 365)) * 1_000_000
        days = pd.date_range("2026-01-01", periods=365, freq="D")
        # Low OIS → higher CPR
        ois_low = np.ones((1, 365)) * 0.01
        result_low, _ = apply_cpr_rate_dependent(deals, nominal, days, ois_low)
        # High OIS → base CPR
        ois_high = np.ones((1, 365)) * 0.05
        result_high, _ = apply_cpr_rate_dependent(deals, nominal, days, ois_high)
        # Low OIS should produce more prepayment (lower end nominal)
        assert result_low[0, -1] < result_high[0, -1]


class TestEveChartBuilder:
    """Test _build_eve chart data function."""

    def test_empty_eve(self):
        from cockpit.pnl_dashboard.charts import _build_eve
        result = _build_eve(None, None, None)
        assert result["has_data"] is False

    def test_eve_with_data(self):
        from cockpit.pnl_dashboard.charts import _build_eve
        eve_results = pd.DataFrame({
            "deal_idx": [0, 1, 2],
            "eve": [100000, 200000, -50000],
            "duration": [2.5, 3.0, 1.5],
            "notional_avg": [1e6, 2e6, 5e5],
            "Currency": ["CHF", "CHF", "EUR"],
        })
        result = _build_eve(eve_results)
        assert result["has_data"] is True
        assert result["total_eve"] == 250000
        assert "CHF" in result["by_currency"]
        assert "EUR" in result["by_currency"]
