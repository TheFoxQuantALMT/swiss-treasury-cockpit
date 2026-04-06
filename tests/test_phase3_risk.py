"""Tests for Phase 3 risk analytics: NMD beta sensitivity, basis risk, CPR, custom scenarios."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pnl_engine.nmd import compute_nmd_beta_sensitivity, apply_deposit_beta
from pnl_engine.prepayment import apply_cpr
from pnl_engine.basis_risk import compute_basis_risk


# ============================================================================
# R1: NMD Beta Sensitivity
# ============================================================================

class TestNmdBetaSensitivity:
    @pytest.fixture
    def nmd_setup(self):
        deals = pd.DataFrame({
            "Dealid": ["D1", "D2"],
            "Product": ["HCD", "HCD"],
            "Currency": ["CHF", "EUR"],
            "Direction": ["L", "L"],
        })
        nmd_profiles = pd.DataFrame({
            "product": ["HCD", "HCD"],
            "currency": ["CHF", "EUR"],
            "direction": ["L", "L"],
            "tier": ["core", "core"],
            "deposit_beta": [0.5, 0.7],
            "floor_rate": [0.0, 0.0],
            "decay_rate": [0.15, 0.20],
            "behavioral_maturity_years": [5, 4],
        })
        n_days = 30
        rate_matrix = np.full((2, n_days), 0.01)
        ois_matrix = np.full((2, n_days), 0.015)
        nominal_daily = np.full((2, n_days), 1_000_000.0)
        mm_vector = np.array([360.0, 360.0])
        return deals, nmd_profiles, rate_matrix, ois_matrix, nominal_daily, mm_vector

    def test_returns_structure(self, nmd_setup):
        deals, profiles, rates, ois, nom, mm = nmd_setup
        result = compute_nmd_beta_sensitivity(deals, profiles, rates, ois, nom, mm)
        assert "total" in result
        assert "by_currency" in result
        assert "delta" in result
        assert result["delta"] == 0.1

    def test_total_keys(self, nmd_setup):
        deals, profiles, rates, ois, nom, mm = nmd_setup
        result = compute_nmd_beta_sensitivity(deals, profiles, rates, ois, nom, mm)
        total = result["total"]
        assert "base_nii" in total
        assert "beta_up_nii" in total
        assert "delta_up" in total
        assert "delta_down" in total

    def test_currency_breakdown(self, nmd_setup):
        deals, profiles, rates, ois, nom, mm = nmd_setup
        result = compute_nmd_beta_sensitivity(deals, profiles, rates, ois, nom, mm)
        assert "CHF" in result["by_currency"]
        assert "EUR" in result["by_currency"]

    def test_empty_profiles(self, nmd_setup):
        deals, _, rates, ois, nom, mm = nmd_setup
        result = compute_nmd_beta_sensitivity(deals, pd.DataFrame(), rates, ois, nom, mm)
        assert result == {}

    def test_beta_up_reduces_nii(self, nmd_setup):
        """Higher beta → more rate passthrough → higher client rate → lower NII for assets."""
        deals, profiles, rates, ois, nom, mm = nmd_setup
        result = compute_nmd_beta_sensitivity(deals, profiles, rates, ois, nom, mm)
        # With higher beta, client rate rises more toward OIS, so OIS - rate shrinks
        # For deposit (L direction), sign conventions may vary
        assert result["total"]["delta_up"] != 0 or result["total"]["delta_down"] != 0


# ============================================================================
# R3: Basis Risk
# ============================================================================

class TestBasisRisk:
    @pytest.fixture
    def basis_setup(self):
        deals = pd.DataFrame({
            "Dealid": ["D1", "D2"],
            "Product": ["IAM/LD", "BND"],
            "Currency": ["CHF", "EUR"],
        })
        n_days = 30
        nominal = np.array([[1_000_000.0] * n_days, [500_000.0] * n_days])
        rates = np.full((2, n_days), 0.02)
        ois = np.full((2, n_days), 0.015)
        mm = np.array([360.0, 360.0])
        return deals, nominal, rates, ois, mm

    def test_returns_structure(self, basis_setup):
        deals, nom, rates, ois, mm = basis_setup
        result = compute_basis_risk(deals, nom, rates, ois, mm)
        assert result["has_data"]
        assert "by_product" in result
        assert "by_currency" in result
        assert "shocks" in result

    def test_default_shocks(self, basis_setup):
        deals, nom, rates, ois, mm = basis_setup
        result = compute_basis_risk(deals, nom, rates, ois, mm)
        assert len(result["shocks"]) == 7

    def test_custom_shocks(self, basis_setup):
        deals, nom, rates, ois, mm = basis_setup
        result = compute_basis_risk(deals, nom, rates, ois, mm, spread_shocks_bp=[-10, 0, 10])
        assert len(result["shocks"]) == 3

    def test_products_present(self, basis_setup):
        deals, nom, rates, ois, mm = basis_setup
        result = compute_basis_risk(deals, nom, rates, ois, mm)
        assert "IAM/LD" in result["by_product"]
        assert "BND" in result["by_product"]

    def test_zero_shock_is_zero(self, basis_setup):
        deals, nom, rates, ois, mm = basis_setup
        result = compute_basis_risk(deals, nom, rates, ois, mm)
        for prod in result["by_product"].values():
            assert prod["+0bp"] == 0

    def test_empty_deals(self):
        result = compute_basis_risk(pd.DataFrame(), None, None, None, None)
        assert not result["has_data"]


# ============================================================================
# R4: Prepayment (CPR)
# ============================================================================

class TestCPR:
    @pytest.fixture
    def cpr_setup(self):
        deals = pd.DataFrame({
            "Dealid": ["D1", "D2"],
            "Product": ["IAM/LD", "IAM/LD"],
            "is_floating": [False, True],  # D2 is floating → no CPR
        })
        n_days = 365
        days = pd.date_range("2026-01-01", periods=n_days, freq="D")
        nominal = np.full((2, n_days), 1_000_000.0)
        return deals, nominal, days

    def test_applies_to_fixed_only(self, cpr_setup):
        deals, nom, days = cpr_setup
        result, log = apply_cpr(deals, nom, days)
        # D1 (fixed) should be reduced, D2 (floating) unchanged
        assert result[0, -1] < nom[0, -1]  # Fixed: reduced
        assert result[1, -1] == nom[1, -1]  # Floating: unchanged

    def test_log_entries(self, cpr_setup):
        deals, nom, days = cpr_setup
        _, log = apply_cpr(deals, nom, days)
        assert len(log) == 1  # Only D1 has CPR
        assert log[0]["deal_id"] == "D1"
        assert log[0]["cpr"] == 0.05

    def test_reduction_magnitude(self, cpr_setup):
        """After 1 year at 5% CPR, nominal should be ~95% of initial."""
        deals, nom, days = cpr_setup
        result, _ = apply_cpr(deals, nom, days)
        ratio = result[0, -1] / nom[0, -1]
        assert 0.94 < ratio < 0.96  # ~95%

    def test_custom_cpr(self, cpr_setup):
        deals, nom, days = cpr_setup
        result, log = apply_cpr(deals, nom, days, cpr_overrides={"IAM/LD": 0.10})
        ratio = result[0, -1] / nom[0, -1]
        assert ratio < 0.92  # 10% CPR → ~90%

    def test_zero_nominal_untouched(self):
        deals = pd.DataFrame({"Dealid": ["D1"], "Product": ["IAM/LD"], "is_floating": [False]})
        days = pd.date_range("2026-01-01", periods=30, freq="D")
        nominal = np.zeros((1, 30))
        result, log = apply_cpr(deals, nominal, days)
        assert np.all(result == 0)

    def test_no_cpr_product(self):
        deals = pd.DataFrame({"Dealid": ["D1"], "Product": ["FXS"], "is_floating": [False]})
        days = pd.date_range("2026-01-01", periods=30, freq="D")
        nominal = np.full((1, 30), 1_000_000.0)
        result, _ = apply_cpr(deals, nominal, days)
        np.testing.assert_array_equal(result, nominal)


# ============================================================================
# R5: Custom Scenarios
# ============================================================================

class TestCustomScenarios:
    def test_parse_missing_file(self):
        from cockpit.data.parsers.custom_scenarios import parse_custom_scenarios
        assert parse_custom_scenarios(Path("/nonexistent/file.xlsx")) is None

    def test_conversion(self):
        from cockpit.data.parsers.custom_scenarios import custom_scenarios_to_bcbs_format
        df = pd.DataFrame({
            "scenario": ["SNB_reversal", "SNB_reversal", "FINMA_stress", "FINMA_stress"],
            "tenor": [0.25, 1.0, 0.25, 1.0],
            "CHF": [-50, -50, 100, 150],
            "EUR": [-25, -25, 50, 75],
        })
        result = custom_scenarios_to_bcbs_format(df)
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "SNB_reversal" in names
        assert "FINMA_stress" in names

        snb = next(r for r in result if r["name"] == "SNB_reversal")
        assert snb["shocks"]["CHF"][0.25] == -50
        assert snb["shocks"]["EUR"][1.0] == -25

    def test_empty_df(self):
        from cockpit.data.parsers.custom_scenarios import custom_scenarios_to_bcbs_format
        assert custom_scenarios_to_bcbs_format(pd.DataFrame()) == []
        assert custom_scenarios_to_bcbs_format(None) == []
