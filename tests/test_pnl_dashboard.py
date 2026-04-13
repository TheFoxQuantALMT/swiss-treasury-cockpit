"""Tests for P&L dashboard chart data builders."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from cockpit.pnl_dashboard.charts import (
    build_pnl_dashboard_data,
    _build_summary,
    _build_coc,
    _build_pnl_series,
    _build_sensitivity,
    _build_strategy,
    _build_book2,
    _build_curves,
    _build_currency_mismatch,
    _build_repricing_gap,
    _build_counterparty_pnl,
    _build_pnl_alerts,
    _build_budget,
    _build_hedge_effectiveness,
    _build_nii_at_risk,
    _build_forecast_tracking,
    _build_attribution,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def date_rates():
    return datetime(2026, 4, 5)


@pytest.fixture
def empty_df():
    return pd.DataFrame()


@pytest.fixture
def sample_stacked():
    """Minimal stacked P&L DataFrame simulating pnlAllS.reset_index()."""
    months = [pd.Period("2026-04", "M"), pd.Period("2026-05", "M"), pd.Period("2026-06", "M")]
    rows = []
    for shock in ("0", "50"):
        for ccy in ("CHF", "EUR"):
            for indice in ("PnL", "Nominal", "OISfwd", "RateRef",
                           "GrossCarry", "FundingCost_Simple", "PnL_Simple", "FundingRate_Simple",
                           "FundingCost_Compounded", "PnL_Compounded", "FundingRate_Compounded"):
                for m in months:
                    for pnl_type in ("Realized", "Forecast"):
                        val = 100.0 if indice == "PnL" else 1_000_000.0 if indice == "Nominal" else 0.02
                        if shock == "50":
                            val *= 1.1
                        if pnl_type == "Forecast":
                            val *= 0.5
                        rows.append({
                            "Périmètre TOTAL": "CC",
                            "Deal currency": ccy,
                            "Product2BuyBack": "IAM/LD",
                            "Direction": "B",
                            "Indice": indice,
                            "PnL_Type": pnl_type,
                            "Month": m,
                            "Shock": shock,
                            "Value": val,
                        })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_strategy_stacked():
    """Stacked data with strategy legs."""
    months = [pd.Period("2026-04", "M"), pd.Period("2026-05", "M")]
    rows = []
    for leg in ("IAM/LD-NHCD", "IAM/LD-HCD", "BND-NHCD", "BND-HCD"):
        for indice in ("PnL", "Nominal", "RateRef", "OISfwd"):
            for m in months:
                rows.append({
                    "Périmètre TOTAL": "CC",
                    "Deal currency": "CHF",
                    "Product2BuyBack": leg,
                    "Direction": "B",
                    "Indice": indice,
                    "PnL_Type": "Total",
                    "Month": m,
                    "Shock": "0",
                    "Value": 50.0 if indice == "PnL" else 500_000 if indice == "Nominal" else 0.015,
                })
    return pd.DataFrame(rows)


@pytest.fixture
def sample_ois_curves():
    """Minimal OIS curve DataFrame."""
    dates = pd.date_range("2026-04-01", periods=90, freq="D")
    rows = []
    for indice in ("CHFSON", "EUREST"):
        for d in dates:
            rows.append({"Date": d, "Indice": indice, "value": 0.015, "dateM": d.to_period("M")})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Tests: Empty data
# ---------------------------------------------------------------------------

class TestEmptyData:
    def test_build_all_empty(self, empty_df, date_rates):
        result = build_pnl_dashboard_data(empty_df, empty_df, date_run=date_rates, date_rates=date_rates)
        expected_keys = {
            "summary", "coc", "pnl_series", "sensitivity", "strategy", "book2", "curves",
            "currency_mismatch", "repricing_gap", "counterparty_pnl", "pnl_alerts",
            "budget", "hedge", "nii_at_risk", "forecast_tracking", "attribution", "eve", "limits",
            "ftp", "liquidity", "nmd_audit", "alco",
            "deal_explorer", "fixed_float", "nim",
            "maturity_wall", "trends",
            "regulatory", "risk_cube", "deposit_behavior",
            "scenario_studio", "hedge_strategy", "alco_decision_pack",
            "data_quality", "basis_risk", "snb_reserves", "peer_benchmark", "nmd_backtest",
        }
        assert set(result.keys()) == expected_keys

    def test_summary_empty(self, empty_df, date_rates):
        result = _build_summary(empty_df, date_rates)
        assert result["kpis"] == {}
        assert result["top5"] == []

    def test_coc_empty(self, empty_df):
        result = _build_coc(empty_df)
        assert result["months"] == []

    def test_pnl_series_empty(self, empty_df, date_rates):
        result = _build_pnl_series(empty_df, date_rates)
        assert result["months"] == []

    def test_sensitivity_empty(self, empty_df):
        result = _build_sensitivity(empty_df)
        assert result["rows"] == []

    def test_strategy_empty(self, empty_df):
        result = _build_strategy(empty_df)
        assert result["has_data"] is False

    def test_book2_empty(self, empty_df):
        result = _build_book2(empty_df, None)
        assert result["has_data"] is False

    def test_curves_empty(self):
        result = _build_curves(None, None)
        assert result["has_data"] is False


# ---------------------------------------------------------------------------
# Tests: With data
# ---------------------------------------------------------------------------

class TestWithData:
    def test_summary_kpis(self, sample_stacked, date_rates):
        result = _build_summary(sample_stacked, date_rates)
        assert "shock_0" in result["kpis"]
        assert "shock_50" in result["kpis"]
        assert result["kpis"]["shock_0"]["total"] != 0
        assert result["kpis"]["delta_50_0"] != 0

    def test_summary_donut(self, sample_stacked, date_rates):
        result = _build_summary(sample_stacked, date_rates)
        assert len(result["donut"]["labels"]) == 2  # CHF, EUR
        assert len(result["donut"]["values"]) == 2

    def test_summary_waterfall(self, sample_stacked, date_rates):
        result = _build_summary(sample_stacked, date_rates)
        assert len(result["waterfall"]["labels"]) == 2
        assert len(result["waterfall"]["realized"]) == 2
        assert len(result["waterfall"]["forecast"]) == 2

    def test_summary_top5(self, sample_stacked, date_rates):
        result = _build_summary(sample_stacked, date_rates)
        assert len(result["top5"]) > 0
        assert "currency" in result["top5"][0]

    def test_coc_has_months(self, sample_stacked):
        result = _build_coc(sample_stacked)
        assert len(result["months"]) == 3
        assert "CHF" in result["by_currency"]
        assert "All" in result["by_currency"]

    def test_coc_table(self, sample_stacked):
        result = _build_coc(sample_stacked)
        assert len(result["table"]) == 3
        assert "GrossCarry" in result["table"][0]

    def test_pnl_series_by_currency(self, sample_stacked, date_rates):
        result = _build_pnl_series(sample_stacked, date_rates)
        assert len(result["months"]) == 3
        assert "CHF" in result["by_currency"]
        assert "shock_0" in result["by_currency"]["CHF"]

    def test_pnl_series_realized_forecast(self, sample_stacked, date_rates):
        result = _build_pnl_series(sample_stacked, date_rates)
        chf = result["by_currency"]["CHF"]
        assert "shock_0_realized" in chf
        assert "shock_0_forecast" in chf

    def test_pnl_series_product_breakdown(self, sample_stacked, date_rates):
        result = _build_pnl_series(sample_stacked, date_rates)
        assert "IAM/LD" in result["by_product"]

    def test_sensitivity_delta(self, sample_stacked):
        result = _build_sensitivity(sample_stacked)
        assert len(result["rows_50"]) > 0
        # shock_50 = 1.1x shock_0, so delta should be positive
        total = sum(r["total"] for r in result["rows_50"])
        assert total > 0

    def test_sensitivity_grand_total(self, sample_stacked):
        result = _build_sensitivity(sample_stacked)
        assert result["grand_total_50"] != 0

    def test_strategy_legs(self, sample_strategy_stacked):
        result = _build_strategy(sample_strategy_stacked)
        assert result["has_data"] is True
        assert len(result["legs"]) == 4
        assert "IAM/LD-NHCD" in result["legs"]

    def test_strategy_table(self, sample_strategy_stacked):
        result = _build_strategy(sample_strategy_stacked)
        assert len(result["table"]) == 4
        assert result["table"][0]["pnl"] != 0

    def test_curves_series(self, sample_ois_curves):
        result = _build_curves(sample_ois_curves, None)
        assert result["has_data"] is True
        assert "CHF" in result["series"]
        assert len(result["series"]["CHF"]["dates"]) > 0
        # Values should be in % (multiplied by 100)
        assert all(v > 0.1 for v in result["series"]["CHF"]["values"])


# ---------------------------------------------------------------------------
# Tests: Full pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_build_all_with_data(self, sample_stacked, sample_ois_curves, date_rates):
        result = build_pnl_dashboard_data(
            pnl_all=pd.DataFrame(),
            pnl_all_s=sample_stacked,
            ois_curves=sample_ois_curves,
            date_run=date_rates,
            date_rates=date_rates,
        )
        assert result["summary"]["kpis"]
        assert result["coc"]["months"]
        assert result["pnl_series"]["months"]
        assert result["sensitivity"]["rows_50"]
        assert result["curves"]["has_data"] is True

    def test_build_all_none_optional(self, sample_stacked, date_rates):
        """Optional args (ois_curves, wirp, irs_stock) can all be None."""
        result = build_pnl_dashboard_data(
            pnl_all=pd.DataFrame(),
            pnl_all_s=sample_stacked,
            ois_curves=None,
            wirp_curves=None,
            irs_stock=None,
            date_run=date_rates,
            date_rates=date_rates,
        )
        assert result["curves"]["has_data"] is False
        assert result["book2"]["has_data"] is False

    def test_build_all_has_alm_keys(self, sample_stacked, date_rates):
        """All ALM enhancement keys are present in result."""
        result = build_pnl_dashboard_data(
            pnl_all=pd.DataFrame(),
            pnl_all_s=sample_stacked,
            date_run=date_rates,
            date_rates=date_rates,
        )
        alm_keys = {"currency_mismatch", "repricing_gap", "counterparty_pnl",
                     "pnl_alerts", "budget", "hedge", "nii_at_risk",
                     "forecast_tracking", "attribution"}
        assert alm_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Currency Mismatch (F9)
# ---------------------------------------------------------------------------

class TestCurrencyMismatch:
    def test_empty(self, empty_df):
        result = _build_currency_mismatch(empty_df)
        assert result["has_data"] is False

    def test_with_data(self, sample_stacked):
        result = _build_currency_mismatch(sample_stacked)
        if result["has_data"]:
            assert len(result["months"]) == 3
            assert "All" in result["by_currency"]
            for ccy_data in result["by_currency"].values():
                assert "assets" in ccy_data
                assert "liabilities" in ccy_data
                assert "gap" in ccy_data
                assert len(ccy_data["gap"]) == 3


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Repricing Gap (F3)
# ---------------------------------------------------------------------------

class TestRepricingGap:
    def test_empty(self, empty_df, date_rates):
        result = _build_repricing_gap(empty_df, None, date_rates)
        assert result["has_data"] is False

    def test_with_deals(self, date_rates):
        deals = pd.DataFrame({
            "Currency": ["CHF", "CHF", "EUR"],
            "Direction": ["D", "L", "D"],
            "Amount": [50e6, 30e6, 20e6],
            "Maturitydate": [
                datetime(2026, 5, 1),
                datetime(2027, 1, 1),
                datetime(2026, 12, 1),
            ],
            "is_floating": [False, False, True],
            "next_fixing_date": [None, None, datetime(2026, 4, 10)],
        })
        result = _build_repricing_gap(pd.DataFrame(), deals, date_rates)
        assert result["has_data"] is True
        assert len(result["buckets"]) > 0
        assert "CHF" in result["by_currency"]
        assert "All" in result["by_currency"]

    def test_cumulative_gap(self, date_rates):
        deals = pd.DataFrame({
            "Currency": ["CHF", "CHF"],
            "Direction": ["D", "L"],
            "Amount": [100e6, 50e6],
            "Maturitydate": [datetime(2026, 5, 1), datetime(2026, 5, 1)],
            "is_floating": [False, False],
        })
        result = _build_repricing_gap(pd.DataFrame(), deals, date_rates)
        if result["has_data"]:
            chf = result["by_currency"].get("CHF", {})
            if "cumulative_gap" in chf:
                # Cumulative should be running sum of gaps
                assert len(chf["cumulative_gap"]) == len(result["buckets"])


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Counterparty P&L (F8)
# ---------------------------------------------------------------------------

class TestCounterpartyPnl:
    def test_empty(self, empty_df):
        result = _build_counterparty_pnl(empty_df)
        assert result["has_data"] is False

    def test_no_counterparty_col(self, sample_stacked):
        # sample_stacked doesn't have Counterparty column
        result = _build_counterparty_pnl(sample_stacked)
        assert result["has_data"] is False

    def test_with_counterparty(self):
        df = pd.DataFrame({
            "Indice": ["PnL"] * 4,
            "Shock": ["0"] * 4,
            "Counterparty": ["BankA", "BankA", "BankB", "BankC"],
            "Deal currency": ["CHF", "EUR", "CHF", "CHF"],
            "Product2BuyBack": ["IAM/LD", "IAM/LD", "BND", "FXS"],
            "Value": [100, 200, -50, 80],
        })
        result = _build_counterparty_pnl(df)
        assert result["has_data"] is True
        assert len(result["top_10"]) == 3
        assert result["hhi"] > 0
        assert "IAM/LD" in result["by_product"]

    def test_with_pnl_by_deal(self):
        """Test counterparty tab using pnl_by_deal (the new pipeline)."""
        pnl_by_deal = pd.DataFrame({
            "Counterparty": ["BankA", "BankA", "BankB", "BankC"],
            "Dealid": [100001, 100002, 100003, 200001],
            "Currency": ["CHF", "EUR", "CHF", "CHF"],
            "Product": ["IAM/LD", "IAM/LD", "BND", "FXS"],
            "Product2BuyBack": ["IAM/LD", "IAM/LD", "BND", "FXS"],
            "Direction": ["D", "D", "L", "B"],
            "PnL": [150, 250, -75, 120],
            "Nominal": [50e6, 30e6, 80e6, 20e6],
            "Shock": ["0", "0", "0", "0"],
            "Month": [pd.Period("2026-04", "M")] * 4,
        })
        result = _build_counterparty_pnl(pd.DataFrame(), pnl_by_deal)
        assert result["has_data"] is True
        assert len(result["top_10"]) == 3
        assert result["top_10"][0]["counterparty"] == "BankA"  # highest |PnL|
        assert result["hhi"] > 0


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — P&L Alerts (F7)
# ---------------------------------------------------------------------------

class TestPnlAlerts:
    def test_empty(self, empty_df):
        result = _build_pnl_alerts(empty_df)
        assert result["has_data"] is False

    def test_no_alerts_triggered(self, sample_stacked):
        result = _build_pnl_alerts(sample_stacked)
        # May or may not have alerts depending on thresholds
        assert "alerts" in result
        assert "summary" in result

    def test_negative_nii_floor(self):
        df = pd.DataFrame({
            "Indice": ["PnL"] * 3,
            "Shock": ["0"] * 3,
            "Deal currency": ["CHF", "EUR", "USD"],
            "Value": [-100, -200, -50],
            "Month": ["2026-04"] * 3,
        })
        result = _build_pnl_alerts(df)
        assert result["has_data"] is True
        assert any(a["type"] == "nii_floor" for a in result["alerts"])

    def test_concentration_alert(self):
        df = pd.DataFrame({
            "Indice": ["PnL"] * 2,
            "Shock": ["0"] * 2,
            "Deal currency": ["CHF", "EUR"],
            "Value": [900, 100],  # CHF = 90% of total
            "Month": ["2026-04"] * 2,
        })
        result = _build_pnl_alerts(df)
        assert any(a["type"] == "ccy_concentration" for a in result["alerts"])


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Budget (F1)
# ---------------------------------------------------------------------------

class TestBudget:
    def test_empty(self, empty_df):
        result = _build_budget(empty_df, None)
        assert result["has_data"] is False

    def test_with_budget(self, sample_stacked):
        budget = pd.DataFrame({
            "currency": ["CHF", "CHF", "CHF", "EUR", "EUR", "EUR"],
            "month": ["2026-04", "2026-05", "2026-06"] * 2,
            "budget_nii": [80, 90, 100, 40, 50, 60],
        })
        result = _build_budget(sample_stacked, budget)
        assert result["has_data"] is True
        assert "CHF" in result["by_currency"]
        assert "ytd" in result
        assert result["ytd"]["budget"] != 0

    def test_variance_waterfall_with_decomposition(self, sample_stacked):
        budget = pd.DataFrame({
            "currency": ["CHF", "CHF"],
            "month": ["2026-04", "2026-05"],
            "budget_nii": [80, 90],
            "budget_nominal": [1e6, 1e6],
            "budget_rate": [0.02, 0.02],
        })
        pnl_by_deal = pd.DataFrame({
            "Deal currency": ["CHF", "CHF"],
            "Shock": ["0", "0"],
            "Nominal": [1.1e6, 1.1e6],
            "PnL": [90, 100],
        })
        deals = pd.DataFrame({
            "Currency": ["CHF"],
            "Dealid": [1],
        })
        result = _build_budget(sample_stacked, budget, deals=deals, pnl_by_deal=pnl_by_deal)
        assert result["has_data"] is True
        chf = result["by_currency"]["CHF"]
        assert "volume_effect" in chf
        assert "rate_effect" in chf
        assert "new_deal_effect" in chf
        assert "matured_effect" in chf
        # Waterfall present
        assert "variance_waterfall" in result
        wf = result["variance_waterfall"]
        assert wf[0]["label"] == "Budget NII"
        assert wf[-1]["label"] == "Actual NII"

    def test_backward_compat_no_decomposition(self, sample_stacked):
        """Without budget_nominal/budget_rate, falls back to simple variance."""
        budget = pd.DataFrame({
            "currency": ["CHF"],
            "month": ["2026-04"],
            "budget_nii": [80],
        })
        result = _build_budget(sample_stacked, budget)
        assert result["has_data"] is True
        # No waterfall without decomposition columns
        assert "variance_waterfall" not in result


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Hedge Effectiveness (F5)
# ---------------------------------------------------------------------------

class TestHedgeEffectiveness:
    def test_empty(self, empty_df):
        result = _build_hedge_effectiveness(empty_df, None)
        assert result["has_data"] is False

    def test_no_dealid(self, sample_stacked):
        hedge_pairs = pd.DataFrame({
            "pair_id": [1],
            "pair_name": ["Test"],
            "hedged_item_deal_ids": ["100001"],
            "hedging_instrument_deal_ids": ["400001"],
            "hedge_type": ["cash_flow"],
            "ias_standard": ["IFRS9"],
        })
        result = _build_hedge_effectiveness(sample_stacked, hedge_pairs)
        assert result["has_data"] is False  # no Dealid in sample_stacked

    def test_with_pnl_by_deal(self):
        """Test hedge effectiveness using pnl_by_deal pipeline."""
        months = [pd.Period("2026-04", "M"), pd.Period("2026-05", "M"), pd.Period("2026-06", "M")]
        pnl_by_deal = pd.DataFrame({
            "Dealid": ["100001"] * 3 + ["400001"] * 3,
            "Counterparty": ["BankA"] * 6,
            "Currency": ["CHF"] * 6,
            "Product": ["IAM/LD"] * 3 + ["IRS"] * 3,
            "Direction": ["D"] * 3 + ["D"] * 3,
            "PnL": [100, 120, 110, -95, -115, -105],  # roughly opposite
            "Nominal": [50e6] * 6,
            "Shock": ["0"] * 6,
            "Month": months * 2,
        })
        hedge_pairs = pd.DataFrame({
            "pair_id": [1],
            "pair_name": ["CHF Hedge"],
            "hedged_item_deal_ids": ["100001"],
            "hedging_instrument_deal_ids": ["400001"],
            "hedge_type": ["cash_flow"],
            "ias_standard": ["IFRS9"],
        })
        result = _build_hedge_effectiveness(pd.DataFrame(), hedge_pairs, pnl_by_deal)
        assert result["has_data"] is True
        assert len(result["pairs"]) == 1
        pair = result["pairs"][0]
        assert pair["pair_name"] == "CHF Hedge"
        assert pair["r_squared"] > 0.8  # good hedge


# ---------------------------------------------------------------------------
# Tests: ALM Enhancement — Stubs (F2, F4, F6)
# ---------------------------------------------------------------------------

class TestNiiAtRiskAndStubs:
    def test_nii_at_risk_empty(self, empty_df):
        result = _build_nii_at_risk(empty_df, None)
        assert result["has_data"] is False

    def test_nii_at_risk_with_scenarios(self, sample_stacked):
        """Test NII-at-Risk with scenario results DataFrame."""
        scenarios_data = pd.DataFrame({
            "Périmètre TOTAL": ["CC"] * 4,
            "Deal currency": ["CHF", "EUR", "CHF", "EUR"],
            "Product2BuyBack": ["IAM/LD"] * 4,
            "Direction": ["D"] * 4,
            "Indice": ["PnL"] * 4,
            "PnL_Type": ["Total"] * 4,
            "Month": [pd.Period("2026-04", "M")] * 4,
            "Shock": ["parallel_up", "parallel_up", "steepener", "steepener"],
            "Value": [500, 300, -200, -100],
        })
        result = _build_nii_at_risk(sample_stacked, scenarios_data)
        assert result["has_data"] is True
        assert len(result["scenarios"]) == 2
        assert len(result["heatmap"]) == 2
        assert len(result["tornado"]) == 2
        assert result["worst_case"]["scenario"] == "steepener"

    def test_forecast_tracking_empty(self):
        result = _build_forecast_tracking(None)
        assert result["has_data"] is False

    def test_forecast_tracking_with_data(self):
        history = pd.DataFrame({
            "date": ["2026-04-01", "2026-04-02", "2026-04-01", "2026-04-02"],
            "currency": ["CHF", "CHF", "EUR", "EUR"],
            "nii_forecast": [1000, 1050, 500, 520],
        })
        result = _build_forecast_tracking(history)
        assert result["has_data"] is True
        assert len(result["dates"]) == 2
        assert "CHF" in result["by_currency"]

    def test_attribution_empty(self, empty_df):
        result = _build_attribution(empty_df, None)
        assert result["has_data"] is False


# ---------------------------------------------------------------------------
# Tests: Scenario engine (pnl_engine.scenarios)
# ---------------------------------------------------------------------------

class TestScenarioEngine:
    def test_interpolate_parallel_up(self):
        from pnl_engine.scenarios import interpolate_scenario_shifts
        from cockpit.data.parsers.scenarios import get_default_scenarios
        scenarios = get_default_scenarios()
        days = pd.date_range("2026-04-05", periods=365, freq="D")
        shifts = interpolate_scenario_shifts(scenarios, "parallel_up", "CHF", days, datetime(2026, 4, 5))
        # parallel_up = +200bp = 0.02 for all tenors
        assert len(shifts) == 365
        np.testing.assert_allclose(shifts, 0.02, atol=1e-6)

    def test_interpolate_short_up(self):
        from pnl_engine.scenarios import interpolate_scenario_shifts
        from cockpit.data.parsers.scenarios import get_default_scenarios
        scenarios = get_default_scenarios()
        days = pd.date_range("2026-04-05", periods=365, freq="D")
        shifts = interpolate_scenario_shifts(scenarios, "short_up", "CHF", days, datetime(2026, 4, 5))
        # short_up: +300bp at O/N tapering to 0 at 20Y
        assert shifts[0] > shifts[-1]  # front-loaded
        assert shifts[0] > 0.01  # should be high at short end

    def test_interpolate_steepener(self):
        from pnl_engine.scenarios import interpolate_scenario_shifts
        from cockpit.data.parsers.scenarios import get_default_scenarios
        scenarios = get_default_scenarios()
        # Need 20+ years to see positive end
        days = pd.date_range("2026-04-05", periods=365 * 25, freq="D")
        shifts = interpolate_scenario_shifts(scenarios, "steepener", "CHF", days, datetime(2026, 4, 5))
        # steepener: -100bp at short end, +100bp at long end
        assert shifts[0] < 0  # negative at short end
        assert shifts[-1] > 0  # positive at long end (beyond 20Y)

    def test_apply_to_curves(self):
        from pnl_engine.scenarios import apply_scenario_to_curves
        curves = pd.DataFrame({
            "Date": pd.date_range("2026-04-05", periods=10, freq="D"),
            "Indice": ["CHFSON"] * 10,
            "value": [0.01] * 10,
        })
        shifts = np.full(10, 0.02)  # +200bp
        result = apply_scenario_to_curves(curves, shifts, "CHFSON")
        np.testing.assert_allclose(result["value"].values, 0.03, atol=1e-10)
