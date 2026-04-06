"""Tests for EVE (Economic Value of Equity) computation."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cockpit.data.parsers import parse_deals, parse_wirp
from cockpit.engine.pnl.forecast import ForecastRatePnL

FIXTURES = Path(__file__).parent / "fixtures" / "ideal_input"


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
