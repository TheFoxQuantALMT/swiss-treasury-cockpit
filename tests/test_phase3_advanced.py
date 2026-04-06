"""Tests for Phase 3 advanced risk: NMD backtest, reverse stress, replication portfolio."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pnl_engine.nmd_backtest import backtest_nmd_model
from pnl_engine.reverse_stress import bisect_breach_shock, reverse_stress_nii, reverse_stress_eve
from pnl_engine.replication import build_replication_portfolio


# ============================================================================
# R2: NMD Back-test
# ============================================================================

class TestNmdBacktest:
    @pytest.fixture
    def backtest_data(self):
        # Simulate 12 months of data following exponential decay
        dates = pd.date_range("2025-04-01", periods=12, freq="ME")
        decay = 0.15
        initial = 1_000_000
        actual = initial * np.exp(-decay * np.arange(12) / 12)
        # Add some noise
        noise = np.random.default_rng(42).normal(0, 5000, 12)
        actual_noisy = actual + noise

        balances = pd.DataFrame({
            "date": dates,
            "product": "HCD",
            "currency": "CHF",
            "direction": "L",
            "balance": actual_noisy,
        })
        profiles = pd.DataFrame({
            "product": ["HCD"],
            "currency": ["CHF"],
            "direction": ["L"],
            "decay_rate": [0.15],
            "deposit_beta": [0.5],
            "behavioral_maturity_years": [5],
        })
        return balances, profiles

    def test_returns_structure(self, backtest_data):
        balances, profiles = backtest_data
        result = backtest_nmd_model(balances, profiles)
        assert result["has_data"]
        assert len(result["groups"]) == 1
        assert "r_squared" in result["groups"][0]

    def test_good_fit(self, backtest_data):
        balances, profiles = backtest_data
        result = backtest_nmd_model(balances, profiles)
        # With noise but correct decay rate, R² should be high
        assert result["groups"][0]["r_squared"] > 0.9

    def test_empty_input(self):
        assert not backtest_nmd_model(None, None)["has_data"]
        assert not backtest_nmd_model(pd.DataFrame(), pd.DataFrame())["has_data"]

    def test_no_matching_profile(self):
        balances = pd.DataFrame({
            "date": pd.date_range("2025-01-01", periods=3, freq="ME"),
            "product": "HCD", "currency": "CHF", "direction": "L",
            "balance": [100, 95, 90],
        })
        profiles = pd.DataFrame({
            "product": ["HCD"], "currency": ["EUR"], "direction": ["L"],
            "decay_rate": [0.15],
        })
        result = backtest_nmd_model(balances, profiles)
        assert not result["has_data"]


# ============================================================================
# R6: Reverse Stress Test
# ============================================================================

class TestBisectBreachShock:
    def test_linear_function(self):
        # f(x) = 100 - 0.5x, breach when < 50
        result = bisect_breach_shock(lambda x: 100 - 0.5 * x, 50.0)
        assert result["converged"]
        assert abs(result["breach_shock_bp"] - 100.0) < 2.0

    def test_no_breach(self):
        # f(x) = 100 (constant) > threshold 50
        result = bisect_breach_shock(lambda x: 100.0, 50.0)
        assert result["breach_shock_bp"] is None

    def test_already_breached(self):
        # f(0) = 40 < 50 → already breached
        result = bisect_breach_shock(lambda x: 40.0, 50.0)
        assert result["breach_shock_bp"] == 0.0

    def test_direction_above(self):
        # f(x) = x, breach when > 100
        result = bisect_breach_shock(lambda x: x, 100.0, direction="above", high_bp=200.0)
        assert result["converged"]
        assert abs(result["breach_shock_bp"] - 100.0) < 2.0


class TestReverseStressNii:
    def test_simple_case(self):
        result = reverse_stress_nii(
            base_nii=1_000_000,
            sensitivity_per_bp=-500,  # NII drops 500 per bp
            limit=800_000,
        )
        assert result["converged"]
        # Need 400 bp shock: 1M - 500*400 = 800K
        assert abs(result["breach_shock_bp"] - 400.0) < 2.0

    def test_no_breach_possible(self):
        result = reverse_stress_nii(
            base_nii=1_000_000,
            sensitivity_per_bp=100,  # NII increases with shock
            limit=800_000,
        )
        assert result["breach_shock_bp"] is None


class TestReverseStressEve:
    def test_dv01_based(self):
        result = reverse_stress_eve(
            base_eve=10_000_000,
            tier1_capital=5_000_000,
            dv01=3000,  # 3K per bp
        )
        assert result["converged"]
        # Limit: 15% of 5M = 750K, DV01=3K → breach at ~250bp
        assert abs(result["breach_shock_bp"] - 250.0) < 2.0

    def test_no_tier1(self):
        result = reverse_stress_eve(base_eve=10_000_000, tier1_capital=0, dv01=3000)
        assert result["breach_shock_bp"] is None


# ============================================================================
# R7: Replication Portfolio
# ============================================================================

class TestReplicationPortfolio:
    def test_exponential_decay(self):
        """Replicate an exponential decay cashflow profile."""
        day_years = np.linspace(0, 10, 3650)
        cf = np.exp(-0.15 * day_years)
        result = build_replication_portfolio(cf, day_years, total_nominal=1_000_000)
        assert result["has_data"]
        assert len(result["portfolio"]) == 5
        assert sum(w["weight"] for w in result["portfolio"]) == pytest.approx(1.0, abs=0.01)
        assert result["r_squared"] > 0.3  # Reasonable fit for step-function approximation

    def test_short_maturity_profile(self):
        """Profile that decays fast should concentrate in short tenors."""
        day_years = np.linspace(0, 10, 3650)
        cf = np.exp(-1.0 * day_years)  # Very fast decay
        result = build_replication_portfolio(cf, day_years)
        assert result["has_data"]
        # 1Y weight should be highest
        weights = {p["tenor"]: p["weight"] for p in result["portfolio"]}
        assert weights[1.0] >= weights[7.0]

    def test_empty_input(self):
        result = build_replication_portfolio(np.array([]), np.array([]))
        assert not result["has_data"]

    def test_wam(self):
        day_years = np.linspace(0, 10, 3650)
        cf = np.exp(-0.15 * day_years)
        result = build_replication_portfolio(cf, day_years)
        assert 0 < result["weighted_avg_maturity"] < 7.0

    def test_nominal_allocation(self):
        day_years = np.linspace(0, 10, 3650)
        cf = np.exp(-0.15 * day_years)
        result = build_replication_portfolio(cf, day_years, total_nominal=5_000_000)
        total_allocated = sum(p["nominal"] for p in result["portfolio"])
        assert abs(total_allocated - 5_000_000) < 100  # Allow rounding
