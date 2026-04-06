"""Tests for NMD (Non-Maturing Deposits) behavioral model."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pnl_engine.nmd import apply_nmd_decay, apply_deposit_beta, get_behavioral_maturity

FIXTURES = Path(__file__).parent / "fixtures" / "ideal_input"


class TestNmdDecay:
    """Test exponential decay of nominal schedules."""

    @pytest.fixture
    def nmd_profiles(self):
        return pd.DataFrame([
            {"product": "IAM/LD", "currency": "CHF", "direction": "D", "tier": "core",
             "behavioral_maturity_years": 5.0, "decay_rate": 0.20, "deposit_beta": 0.5, "floor_rate": 0.0},
        ])

    @pytest.fixture
    def deals(self):
        return pd.DataFrame([
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "D"},
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "L"},  # Loan, should not match
        ])

    @pytest.fixture
    def nominal_daily(self):
        """2 deals × 365 days, first has 1M nominal, second 500K."""
        n = np.zeros((2, 365))
        n[0, :] = 1_000_000
        n[1, :] = 500_000
        return n

    @pytest.fixture
    def days(self):
        return pd.date_range("2026-04-05", periods=365, freq="D")

    def test_decay_applied_to_deposit(self, deals, nmd_profiles, nominal_daily, days):
        result, match_log = apply_nmd_decay(deals, nmd_profiles, nominal_daily, days, datetime(2026, 4, 5))
        # First deal (deposit, CHF, D) should decay
        assert result[0, 0] == 1_000_000  # Initial unchanged
        assert result[0, -1] < 1_000_000  # End should be decayed
        # Exponential decay: at 1 year, value ≈ 1M * exp(-0.20 * 1) ≈ 818,731
        expected_1y = 1_000_000 * np.exp(-0.20 * 1.0)
        np.testing.assert_allclose(result[0, -1], expected_1y, rtol=0.02)
        # Match log should contain the matched deal
        assert len(match_log) == 1
        assert match_log[0]["applied"] is True
        assert match_log[0]["tier"] == "core"
        assert match_log[0]["decay_rate"] == 0.20

    def test_loan_not_decayed(self, deals, nmd_profiles, nominal_daily, days):
        result, match_log = apply_nmd_decay(deals, nmd_profiles, nominal_daily, days, datetime(2026, 4, 5))
        # Second deal (loan) should not be touched
        np.testing.assert_array_equal(result[1], nominal_daily[1])

    def test_empty_profiles_no_change(self, deals, nominal_daily, days):
        result, match_log = apply_nmd_decay(deals, pd.DataFrame(), nominal_daily, days, datetime(2026, 4, 5))
        np.testing.assert_array_equal(result, nominal_daily)
        assert match_log == []

    def test_none_profiles_no_change(self, deals, nominal_daily, days):
        result, match_log = apply_nmd_decay(deals, None, nominal_daily, days, datetime(2026, 4, 5))
        np.testing.assert_array_equal(result, nominal_daily)
        assert match_log == []


class TestDepositBeta:
    """Test deposit beta adjustment of client rates."""

    def test_beta_reduces_rate_passthrough(self):
        nmd_profiles = pd.DataFrame([
            {"product": "IAM/LD", "currency": "CHF", "direction": "D",
             "deposit_beta": 0.5, "floor_rate": 0.0},
        ])
        deals = pd.DataFrame([
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "D"},
        ])
        rate_matrix = np.array([[0.02]])  # 2% client rate
        ois_matrix = np.array([[0.04]])   # 4% OIS

        result = apply_deposit_beta(rate_matrix, deals, nmd_profiles, ois_matrix)
        # Effective = floor + beta * max(0, OIS - floor) = 0 + 0.5 * 0.04 = 0.02
        np.testing.assert_allclose(result[0, 0], 0.02)

    def test_beta_1_no_change(self):
        nmd_profiles = pd.DataFrame([
            {"product": "IAM/LD", "currency": "CHF", "direction": "D",
             "deposit_beta": 1.0, "floor_rate": 0.0},
        ])
        deals = pd.DataFrame([
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "D"},
        ])
        rate_matrix = np.array([[0.02]])
        ois_matrix = np.array([[0.04]])

        result = apply_deposit_beta(rate_matrix, deals, nmd_profiles, ois_matrix)
        # beta=1.0 means no adjustment
        np.testing.assert_array_equal(result, rate_matrix)

    def test_floor_rate(self):
        nmd_profiles = pd.DataFrame([
            {"product": "IAM/LD", "currency": "CHF", "direction": "D",
             "deposit_beta": 0.5, "floor_rate": 0.01},
        ])
        deals = pd.DataFrame([
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "D"},
        ])
        rate_matrix = np.array([[0.02]])
        ois_matrix = np.array([[0.04]])

        result = apply_deposit_beta(rate_matrix, deals, nmd_profiles, ois_matrix)
        # Effective = floor + beta * max(0, OIS - floor) = 0.01 + 0.5 * (0.04 - 0.01) = 0.025
        np.testing.assert_allclose(result[0, 0], 0.025)


class TestBehavioralMaturity:
    """Test behavioral maturity lookup."""

    def test_behavioral_maturity_returned(self):
        nmd_profiles = pd.DataFrame([
            {"product": "IAM/LD", "currency": "CHF", "direction": "D",
             "behavioral_maturity_years": 5.0},
        ])
        deals = pd.DataFrame([
            {"Product": "IAM/LD", "Currency": "CHF", "Direction": "D"},
            {"Product": "BND", "Currency": "CHF", "Direction": "B"},
        ])
        result = get_behavioral_maturity(deals, nmd_profiles)
        assert result.iloc[0] == 5.0
        assert np.isnan(result.iloc[1])  # No match for bonds


class TestNmdParser:
    """Test nmd_profiles.xlsx parser."""

    def test_parse_nmd_profiles(self):
        from cockpit.data.parsers.nmd_profiles import parse_nmd_profiles
        path = FIXTURES / "nmd_profiles.xlsx"
        if not path.exists():
            pytest.skip("nmd_profiles.xlsx not generated")
        df = parse_nmd_profiles(path)
        assert not df.empty
        assert "product" in df.columns
        assert "decay_rate" in df.columns
        assert "deposit_beta" in df.columns
        assert all(df["decay_rate"] >= 0)
        assert all(df["deposit_beta"] >= 0)
        assert all(df["deposit_beta"] <= 1.0)


class TestLimitsParser:
    """Test limits.xlsx parser."""

    def test_parse_limits(self):
        from cockpit.data.parsers.limits import parse_limits
        path = FIXTURES / "limits.xlsx"
        if not path.exists():
            pytest.skip("limits.xlsx not generated")
        df = parse_limits(path)
        assert not df.empty
        assert "metric" in df.columns
        assert "limit_value" in df.columns
        assert "warning_pct" in df.columns
        assert all(df["warning_pct"] > 0)


class TestAlertThresholdsParser:
    """Test alert_thresholds.xlsx parser."""

    def test_parse_alert_thresholds(self):
        from cockpit.data.parsers.alert_thresholds import parse_alert_thresholds
        path = FIXTURES / "alert_thresholds.xlsx"
        if not path.exists():
            pytest.skip("alert_thresholds.xlsx not generated")
        result = parse_alert_thresholds(path)
        assert isinstance(result, dict)
        assert "ALL" in result
        assert "CHF" in result
        assert "annual_nii_floor" in result["ALL"]
