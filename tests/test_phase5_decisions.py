"""Tests for Phase 5: Decision intelligence modules."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pnl_engine.hedge_optimizer import recommend_hedge
from pnl_engine.locked_in_nii import compute_locked_in_nii
from pnl_engine.sensitivity_explain import explain_sensitivity_change
from pnl_engine.what_if import simulate_deal, simulate_batch
from cockpit.decisions import DecisionStore


# ============================================================================
# D1: Hedge Optimizer
# ============================================================================

class TestHedgeOptimizer:
    def test_basic_recommendation(self):
        result = recommend_hedge({"CHF": 15000, "EUR": 8000})
        assert result["has_data"]
        assert len(result["recommendations"]) == 2

    def test_recommends_payer_for_positive_dv01(self):
        result = recommend_hedge({"CHF": 15000})
        rec = result["recommendations"][0]
        assert rec["direction"] == "payer"
        assert rec["notional"] > 0

    def test_with_target(self):
        result = recommend_hedge(
            {"CHF": 15000},
            target_dv01={"CHF": 5000},
        )
        rec = result["recommendations"][0]
        # Should hedge 10000 DV01 worth
        assert rec["excess_dv01"] == 10000

    def test_within_limits(self):
        result = recommend_hedge(
            {"CHF": 5000},
            max_dv01={"CHF": 10000},
            target_dv01={"CHF": 5000},
        )
        rec = result["recommendations"][0]
        assert rec["action"] == "none"

    def test_empty_portfolio(self):
        result = recommend_hedge({})
        assert not result["has_data"]


# ============================================================================
# D2: Locked-in NII
# ============================================================================

class TestLockedInNii:
    @pytest.fixture
    def locked_setup(self):
        deals = pd.DataFrame({
            "Dealid": ["D1", "D2"],
            "Currency": ["CHF", "CHF"],
            "is_floating": [False, True],
        })
        n_days = 365
        nominal = np.full((2, n_days), 1_000_000.0)
        rates = np.full((2, n_days), 0.02)
        ois = np.full((2, n_days), 0.015)
        mm = np.array([360.0, 360.0])
        return deals, nominal, rates, ois, mm

    def test_returns_structure(self, locked_setup):
        deals, nom, rates, ois, mm = locked_setup
        result = compute_locked_in_nii(deals, nom, rates, ois, mm)
        assert result["has_data"]
        assert "locked_nii" in result
        assert "locked_pct" in result
        assert "by_currency" in result

    def test_locked_less_than_total(self, locked_setup):
        deals, nom, rates, ois, mm = locked_setup
        result = compute_locked_in_nii(deals, nom, rates, ois, mm)
        # Both deals have same NII, but only D1 is fixed → locked ≈ 50%
        assert 40 < result["locked_pct"] < 60

    def test_all_fixed(self):
        deals = pd.DataFrame({"Dealid": ["D1"], "Currency": ["CHF"], "is_floating": [False]})
        nom = np.full((1, 30), 1_000_000.0)
        rates = np.full((1, 30), 0.02)
        ois = np.full((1, 30), 0.015)
        mm = np.array([360.0])
        result = compute_locked_in_nii(deals, nom, rates, ois, mm)
        assert result["locked_pct"] == 100.0

    def test_empty(self):
        assert not compute_locked_in_nii(None, None, None, None, None)["has_data"]


# ============================================================================
# D3: Sensitivity Explain
# ============================================================================

class TestSensitivityExplain:
    def test_basic_waterfall(self):
        result = explain_sensitivity_change(
            {"CHF": -5000, "EUR": -3000},
            {"CHF": -4000, "EUR": -3500},
        )
        assert result["has_data"]
        assert len(result["waterfall"]) == 2
        assert result["total_change"] == -500  # (-8000) - (-7500)

    def test_empty_input(self):
        assert not explain_sensitivity_change({}, {})["has_data"]

    def test_with_deals(self):
        curr = pd.DataFrame({"Dealid": ["D1", "D2", "D3"]})
        prev = pd.DataFrame({"Dealid": ["D1", "D2", "D4"]})
        result = explain_sensitivity_change(
            {"CHF": -5000}, {"CHF": -4000},
            current_deals=curr, previous_deals=prev,
        )
        wf = result["waterfall"][0]
        assert "new_deals" in wf
        assert "maturing" in wf
        assert "rate_effect" in wf


# ============================================================================
# D4: What-If Simulator
# ============================================================================

class TestWhatIf:
    def test_single_deal(self):
        result = simulate_deal(
            notional=10_000_000,
            client_rate=0.025,
            ois_rate=0.015,
            maturity_years=3.0,
            direction="B",
        )
        assert result["annual_nii"] != 0
        assert result["spread_bp"] == -100.0  # OIS 1.5% - Client 2.5% = -100bp
        assert result["dv01_contribution"] > 0

    def test_liability(self):
        result = simulate_deal(
            notional=5_000_000,
            client_rate=0.01,
            ois_rate=0.015,
            maturity_years=2.0,
            direction="L",
        )
        # Liability: sign is -1, spread = OIS - rate = 0.5% > 0
        # NII = -5M × 0.005 / 360 × 365 < 0 (cost for bank)
        assert result["direction"] == "L"

    def test_floating_with_beta(self):
        result = simulate_deal(
            notional=10_000_000,
            client_rate=0.02,
            ois_rate=0.015,
            maturity_years=5.0,
            is_floating=True,
            deposit_beta=0.5,
        )
        # Effective rate = 0.5 × 0.015 = 0.75%
        assert result["is_floating"]

    def test_batch(self):
        deals = [
            {"notional": 10_000_000, "client_rate": 0.025, "maturity_years": 3, "currency": "CHF", "direction": "B"},
            {"notional": 5_000_000, "client_rate": 0.02, "maturity_years": 2, "currency": "EUR", "direction": "B"},
        ]
        result = simulate_batch(deals, {"CHF": 0.015, "EUR": 0.025})
        assert result["has_data"]
        assert result["n_deals"] == 2
        assert result["total_annual_nii"] != 0


# ============================================================================
# D5: Decision Audit Trail
# ============================================================================

class TestDecisionStore:
    @pytest.fixture
    def store(self, tmp_path):
        return DecisionStore(tmp_path / "decisions")

    def test_record_and_load(self, store):
        store.record("NII Sensitivity", "Reduce duration", priority="high",
                      date=datetime(2026, 4, 5))
        decisions = store.load()
        assert len(decisions) == 1
        assert decisions[0]["topic"] == "NII Sensitivity"

    def test_multiple_records(self, store):
        store.record("Topic A", "Desc A", date=datetime(2026, 4, 5))
        store.record("Topic B", "Desc B", date=datetime(2026, 4, 5))
        assert len(store.load()) == 2

    def test_load_by_month(self, store):
        store.record("April", "April decision", date=datetime(2026, 4, 5))
        store.record("March", "March decision", date=datetime(2026, 3, 15))
        assert len(store.load("2026-04")) == 1
        assert len(store.load("2026-03")) == 1

    def test_update_status(self, store):
        store.record("Topic", "Desc", status="open", date=datetime(2026, 4, 5))
        store.update_status("2026-04-05", "Topic", "closed")
        decisions = store.load()
        assert decisions[0]["status"] == "closed"

    def test_load_recent(self, store):
        for i in range(5):
            store.record(f"Topic {i}", f"Desc {i}", date=datetime(2026, 4, i + 1))
        recent = store.load_recent(3)
        assert len(recent) == 3

    def test_summary(self, store):
        store.record("A", "A", priority="high", status="open", date=datetime(2026, 4, 5))
        store.record("B", "B", priority="critical", status="closed", date=datetime(2026, 4, 5))
        s = store.summary()
        assert s["total"] == 2
        assert s["by_status"]["open"] == 1
        assert s["by_priority"]["critical"] == 1
