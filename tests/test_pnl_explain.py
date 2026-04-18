"""Tests for P&L Explain — waterfall decomposition of NII changes."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from cockpit.engine.pnl.pnl_explain import compute_pnl_explain


def _make_pnl_by_deal(deal_ids, pnl_values, currencies=None, shock="0"):
    """Helper: create a pnl_by_deal DataFrame."""
    n = len(deal_ids)
    return pd.DataFrame({
        "Dealid": [str(d) for d in deal_ids],
        "Counterparty": ["CPTY"] * n,
        "Currency": currencies or ["CHF"] * n,
        "Product": ["IAM/LD"] * n,
        "Direction": ["D"] * n,
        "Périmètre TOTAL": ["CC"] * n,
        "Month": [pd.Period("2026-04")] * n,
        "PnL_Simple": pnl_values,
        "Nominal": [1e6] * n,
        "Shock": [shock] * n,
    })


def _make_pnl_all_s(currencies, pnl_values, ois_values, nominal_values):
    """Helper: create a minimal pnlAllS DataFrame."""
    rows = []
    for i, ccy in enumerate(currencies):
        for indice, val in [("PnL_Simple", pnl_values[i]), ("OISfwd", ois_values[i]), ("Nominal", nominal_values[i]), ("RateRef", 0.01)]:
            rows.append({
                "Périmètre TOTAL": "CC",
                "Deal currency": ccy,
                "Product2BuyBack": "IAM/LD",
                "Direction": "D",
                "Indice": indice,
                "PnL_Type": "Total",
                "Month": "2026-04",
                "Shock": "0",
                "Value": val,
            })
    return pd.DataFrame(rows)


def _make_deals(deal_ids, value_dates, maturity_dates, currencies=None):
    """Helper: create a deals DataFrame."""
    n = len(deal_ids)
    return pd.DataFrame({
        "Dealid": [str(d) for d in deal_ids],
        "Valuedate": value_dates,
        "Maturitydate": maturity_dates,
        "Product": ["IAM/LD"] * n,
        "Currency": currencies or ["CHF"] * n,
        "Direction": ["D"] * n,
    })


class TestPnlExplainBasic:
    """Test basic P&L explain functionality."""

    def test_identical_portfolios_zero_delta(self):
        """Same portfolio → ΔNII = 0."""
        pbd = _make_pnl_by_deal([1, 2, 3], [100, 200, 300])
        pnl_s = _make_pnl_all_s(["CHF"], [600], [0.01], [3e6])
        deals = _make_deals([1, 2, 3],
                           ["2025-01-01"] * 3,
                           ["2027-01-01"] * 3)

        result = compute_pnl_explain(
            pbd, pbd, pnl_s, pnl_s, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert result["has_data"]
        assert result["summary"]["delta"] == 0
        assert len(result["waterfall"]) == 7

    def test_waterfall_reconciles(self):
        """Waterfall first + effects = last."""
        pbd_prev = _make_pnl_by_deal([1, 2], [100, 200])
        pbd_curr = _make_pnl_by_deal([1, 2], [150, 250])
        pnl_s_prev = _make_pnl_all_s(["CHF"], [300], [0.01], [2e6])
        pnl_s_curr = _make_pnl_all_s(["CHF"], [400], [0.015], [2e6])
        deals = _make_deals([1, 2], ["2025-01-01"] * 2, ["2027-01-01"] * 2)

        result = compute_pnl_explain(
            pbd_curr, pbd_prev, pnl_s_curr, pnl_s_prev, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        wf = result["waterfall"]
        assert wf[0]["type"] == "base"
        assert wf[-1]["type"] == "total"
        # Sum of effects should equal delta
        effects_sum = sum(s["value"] for s in wf if s["type"] == "effect")
        assert abs(wf[-1]["value"] - wf[0]["value"] - effects_sum) < 2  # rounding tolerance


class TestNewAndMaturedDeals:
    """Test detection of new and matured deals."""

    def test_new_deal_detected(self):
        """Deal in current but not in prev → new deal."""
        pbd_prev = _make_pnl_by_deal([1, 2], [100, 200])
        pbd_curr = _make_pnl_by_deal([1, 2, 3], [100, 200, 500])
        pnl_s = _make_pnl_all_s(["CHF"], [800], [0.01], [3e6])
        deals = _make_deals([1, 2, 3],
                           ["2025-01-01", "2025-01-01", "2026-04-10"],
                           ["2027-01-01", "2027-01-01", "2028-01-01"])

        result = compute_pnl_explain(
            pbd_curr, pbd_prev, pnl_s, pnl_s, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert result["summary"]["n_new"] >= 1
        assert result["summary"]["new_deal_effect"] == 500
        assert len(result["new_deals"]) >= 1

    def test_matured_deal_detected(self):
        """Deal in prev but not in current → matured."""
        pbd_prev = _make_pnl_by_deal([1, 2, 3], [100, 200, 300])
        pbd_curr = _make_pnl_by_deal([1, 2], [100, 200])
        pnl_s_prev = _make_pnl_all_s(["CHF"], [600], [0.01], [3e6])
        pnl_s_curr = _make_pnl_all_s(["CHF"], [300], [0.01], [2e6])
        deals = _make_deals([1, 2],
                           ["2025-01-01"] * 2,
                           ["2027-01-01"] * 2)

        result = compute_pnl_explain(
            pbd_curr, pbd_prev, pnl_s_curr, pnl_s_prev, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert result["summary"]["n_matured"] >= 1
        assert result["summary"]["matured_deal_effect"] == -300  # lost the P&L
        assert len(result["matured_deals"]) >= 1

    def test_existing_deal_pnl_drop_goes_to_residual(self):
        """Deal present in both runs with lower curr P&L (e.g., nearing maturity)
        is treated as existing; its P&L drop flows into the residual, not
        into `matured`. Set-membership is the clean criterion for classification."""
        pbd_prev = _make_pnl_by_deal([1, 2], [100, 200])
        pbd_curr = _make_pnl_by_deal([1, 2], [100, 50])  # deal 2 runs off
        pnl_s = _make_pnl_all_s(["CHF"], [300], [0.01], [2e6])
        deals = _make_deals([1, 2], ["2025-01-01"] * 2, ["2027-01-01"] * 2)

        result = compute_pnl_explain(
            pbd_curr, pbd_prev, pnl_s, pnl_s, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert result["summary"]["n_matured"] == 0
        assert result["summary"]["n_existing"] == 2
        # Δexisting = -150 should fully land in residual (rates unchanged).
        assert result["summary"]["rate_effect"] == 0
        assert result["summary"]["spread_effect"] == 0
        assert result["summary"]["residual_effect"] == -150


class TestEmptyInputs:
    """Test graceful handling of empty/None inputs."""

    def test_none_prev(self):
        pbd = _make_pnl_by_deal([1], [100])
        pnl_s = _make_pnl_all_s(["CHF"], [100], [0.01], [1e6])
        result = compute_pnl_explain(pbd, None, pnl_s, pnl_s, None,
                                     datetime(2026, 4, 5), datetime(2026, 4, 4))
        assert not result["has_data"]

    def test_none_curr(self):
        pbd = _make_pnl_by_deal([1], [100])
        pnl_s = _make_pnl_all_s(["CHF"], [100], [0.01], [1e6])
        result = compute_pnl_explain(None, pbd, pnl_s, pnl_s, None,
                                     datetime(2026, 4, 5), datetime(2026, 4, 4))
        assert not result["has_data"]

    def test_empty_dataframes(self):
        result = compute_pnl_explain(
            pd.DataFrame(), pd.DataFrame(),
            pd.DataFrame(), pd.DataFrame(), None,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert not result["has_data"]


class TestMultiCurrency:
    """Test P&L explain across multiple currencies."""

    def test_rate_effect_by_currency(self):
        """Rate movement in EUR should show in by_currency breakdown."""
        pbd = _make_pnl_by_deal([1, 2], [100, 200], ["CHF", "EUR"])
        pnl_s_prev = _make_pnl_all_s(["CHF", "EUR"], [100, 200], [0.01, 0.02], [1e6, 2e6])
        pnl_s_curr = _make_pnl_all_s(["CHF", "EUR"], [100, 250], [0.01, 0.025], [1e6, 2e6])
        deals = _make_deals([1, 2], ["2025-01-01"] * 2, ["2027-01-01"] * 2, ["CHF", "EUR"])

        result = compute_pnl_explain(
            pbd, pbd, pnl_s_curr, pnl_s_prev, deals,
            datetime(2026, 4, 5), datetime(2026, 4, 4),
        )
        assert "CHF" in result["by_currency"]
        assert "EUR" in result["by_currency"]
        # EUR OIS moved from 200bp to 250bp
        assert result["by_currency"]["EUR"]["ois_curr"] > result["by_currency"]["EUR"]["ois_prev"]
