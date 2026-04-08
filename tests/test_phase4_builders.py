"""Tests for Phase 4 chart data builders (and related builders) in pnl_dashboard/charts.py.

Covers:
  _build_nim, _build_maturity_wall, _build_risk_cube, _build_deposit_behavior,
  _build_scenario_studio, _build_hedge_strategy, _build_alco_decision_pack,
  _build_ftp, _build_trends, _build_regulatory, _build_nmd_audit, _build_liquidity
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from cockpit.pnl_dashboard.charts import (
    _build_nim,
    _build_maturity_wall,
    _build_risk_cube,
    _build_deposit_behavior,
    _build_scenario_studio,
    _build_hedge_strategy,
    _build_alco_decision_pack,
    _build_ftp,
    _build_trends,
    _build_regulatory,
    _build_nmd_audit,
    _build_liquidity,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_df():
    return pd.DataFrame()


@pytest.fixture
def sample_stacked():
    """Minimal stacked P&L DataFrame (pnlAllS format)."""
    months = [pd.Period("2026-04", "M"), pd.Period("2026-05", "M"), pd.Period("2026-06", "M")]
    rows = []
    for shock in ("0", "50"):
        for ccy in ("CHF", "EUR"):
            for indice in ("PnL", "Nominal", "OISfwd", "RateRef",
                           "GrossCarry", "FundingCost", "CoC_Simple"):
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
def sample_deals():
    """Minimal deals DataFrame with realistic columns."""
    return pd.DataFrame({
        "Dealid": [100001, 100002, 100003, 100004],
        "Product": ["IAM/LD", "IAM/LD", "BND", "IRS"],
        "Direction": ["L", "D", "L", "S"],
        "Currency": ["CHF", "CHF", "EUR", "CHF"],
        "NominalResiduel": [5_000_000, 3_000_000, 2_000_000, 1_000_000],
        "Nominal": [5_000_000, 3_000_000, 2_000_000, 1_000_000],
        "Maturitydate": [
            datetime(2027, 4, 1),
            datetime(2026, 10, 1),
            datetime(2028, 1, 1),
            datetime(2027, 1, 1),
        ],
        "Counterparty": ["BankA", "ClientX", "BankB", "BankA"],
        "FTP": [0.012, 0.010, 0.015, 0.013],
        "Clientrate": [0.025, 0.018, 0.030, 0.020],
        "Périmètre TOTAL": ["CC", "CC", "WM", "CC"],
    })


@pytest.fixture
def sample_nmd_profiles():
    return pd.DataFrame({
        "product": ["IAM/LD", "IAM/LD"],
        "currency": ["CHF", "EUR"],
        "direction": ["D", "D"],
        "tier": ["CORE", "VOLATILE"],
        "decay_rate": [0.05, 0.20],
        "deposit_beta": [0.30, 0.70],
        "floor_rate": [0.0, 0.0],
        "behavioral_maturity_years": [5.0, 2.0],
    })


@pytest.fixture
def nii_at_risk_data():
    """Pre-built nii_at_risk dict as produced by _build_nii_at_risk."""
    return {
        "has_data": True,
        "scenarios": ["parallel_up", "parallel_down", "steepener", "flattener"],
        "by_currency": {
            "CHF": {"parallel_up": 800, "parallel_down": -200, "steepener": 300, "flattener": -100},
            "EUR": {"parallel_up": 500, "parallel_down": -150, "steepener": 200, "flattener": -80},
        },
        "heatmap": [
            {"scenario": "parallel_up", "CHF": 800, "EUR": 500, "total": 1300},
            {"scenario": "parallel_down", "CHF": -200, "EUR": -150, "total": -350},
            {"scenario": "steepener", "CHF": 300, "EUR": 200, "total": 500},
            {"scenario": "flattener", "CHF": -100, "EUR": -80, "total": -180},
        ],
        "tornado": [
            {"scenario": "parallel_down", "nii": 950, "delta": -350},
            {"scenario": "flattener", "nii": 1120, "delta": -180},
            {"scenario": "steepener", "nii": 1800, "delta": 500},
            {"scenario": "parallel_up", "nii": 2600, "delta": 1300},
        ],
        "worst_case": {"scenario": "parallel_down", "nii": 950, "delta": -350},
        "base_total": 1300,
        "ear": None,
    }


# ---------------------------------------------------------------------------
# 1. _build_nim
# ---------------------------------------------------------------------------

class TestBuildNim:
    def test_empty_df(self, empty_df):
        result = _build_nim(empty_df)
        assert result["has_data"] is False

    def test_empty_df_with_deals(self, empty_df, sample_deals):
        result = _build_nim(empty_df, sample_deals)
        assert result["has_data"] is False

    def test_with_data(self, sample_stacked, sample_deals):
        result = _build_nim(sample_stacked, sample_deals)
        assert result["has_data"] is True
        assert "kpis" in result
        assert "jaws" in result
        assert "by_currency" in result
        assert "nim_bps" in result["kpis"]
        assert result["kpis"]["n_months"] > 0

    def test_nim_by_currency(self, sample_stacked, sample_deals):
        result = _build_nim(sample_stacked, sample_deals)
        assert result["has_data"] is True
        # sample_stacked has CHF and EUR
        assert "CHF" in result["by_currency"]
        assert "EUR" in result["by_currency"]
        for ccy_data in result["by_currency"].values():
            assert "nim_bps" in ccy_data
            assert "nii" in ccy_data

    def test_jaws_chart(self, sample_stacked):
        result = _build_nim(sample_stacked)
        assert result["has_data"] is True
        jaws = result["jaws"]
        assert "months" in jaws
        assert "asset_yield" in jaws
        assert "funding_cost" in jaws
        assert len(jaws["months"]) == len(jaws["asset_yield"])


# ---------------------------------------------------------------------------
# 2. _build_maturity_wall
# ---------------------------------------------------------------------------

class TestBuildMaturityWall:
    def test_none_deals(self):
        result = _build_maturity_wall(None)
        assert result["has_data"] is False

    def test_empty_deals(self, empty_df):
        result = _build_maturity_wall(empty_df)
        assert result["has_data"] is False

    def test_deals_missing_maturitydate(self):
        deals = pd.DataFrame({"Dealid": [1], "Currency": ["CHF"], "Nominal": [1e6]})
        result = _build_maturity_wall(deals)
        assert result["has_data"] is False

    def test_with_data(self, sample_deals):
        result = _build_maturity_wall(sample_deals)
        assert result["has_data"] is True
        assert len(result["months"]) > 0
        assert "by_currency" in result
        assert "by_product" in result
        assert "kpis" in result
        assert "top_maturities" in result
        assert "reinvestment_summary" in result

    def test_kpis_populated(self, sample_deals):
        result = _build_maturity_wall(sample_deals)
        assert result["has_data"] is True
        kpis = result["kpis"]
        assert "total_maturing_24m" in kpis
        assert kpis["total_maturing_24m"] > 0
        assert kpis["deal_count"] > 0

    def test_by_currency_structure(self, sample_deals):
        result = _build_maturity_wall(sample_deals)
        for ccy_data in result["by_currency"].values():
            assert "volumes" in ccy_data
            assert "total" in ccy_data
            assert len(ccy_data["volumes"]) == len(result["months"])


# ---------------------------------------------------------------------------
# 3. _build_risk_cube
# ---------------------------------------------------------------------------

class TestBuildRiskCube:
    def test_empty_df_no_pnl_by_deal(self, empty_df):
        result = _build_risk_cube(empty_df, None)
        assert result["has_data"] is False

    def test_with_stacked_df(self, sample_stacked):
        result = _build_risk_cube(sample_stacked)
        assert result["has_data"] is True
        assert "product_currency" in result
        assert "direction_currency" in result

    def test_with_pnl_by_deal(self):
        pnl_by_deal = pd.DataFrame({
            "Dealid": [100001, 100002, 100003, 100004],
            "Shock": ["0", "0", "0", "0"],
            "Month": [pd.Period("2026-04", "M")] * 4,
            "PnL": [150.0, -80.0, 200.0, -50.0],
            "Deal currency": ["CHF", "CHF", "EUR", "CHF"],
            "Product": ["IAM/LD", "BND", "IAM/LD", "FXS"],
            "Direction": ["L", "L", "D", "S"],
            "Counterparty": ["BankA", "BankB", "ClientX", "BankA"],
        })
        result = _build_risk_cube(pd.DataFrame(), pnl_by_deal)
        assert result["has_data"] is True
        pc = result["product_currency"]
        assert len(pc["products"]) > 0
        assert len(pc["currencies"]) > 0
        assert len(pc["matrix"]) == len(pc["products"])

    def test_direction_currency_matrix(self):
        pnl_by_deal = pd.DataFrame({
            "Dealid": [1, 2, 3],
            "Shock": ["0", "0", "0"],
            "PnL": [100.0, -50.0, 200.0],
            "Deal currency": ["CHF", "EUR", "CHF"],
            "Product": ["IAM/LD", "IAM/LD", "BND"],
            "Direction": ["L", "D", "L"],
            "Counterparty": ["BankA", "ClientX", "BankA"],
        })
        result = _build_risk_cube(pd.DataFrame(), pnl_by_deal)
        dc = result["direction_currency"]
        assert len(dc["directions"]) > 0
        assert len(dc["currencies"]) > 0

    def test_counterparty_product_matrix(self):
        pnl_by_deal = pd.DataFrame({
            "Dealid": [1, 2, 3, 4],
            "Shock": ["0"] * 4,
            "PnL": [100.0, -50.0, 200.0, 75.0],
            "Deal currency": ["CHF", "CHF", "EUR", "CHF"],
            "Product": ["IAM/LD", "BND", "IAM/LD", "FXS"],
            "Direction": ["L", "L", "D", "S"],
            "Counterparty": ["BankA", "BankA", "BankB", "BankC"],
        })
        result = _build_risk_cube(pd.DataFrame(), pnl_by_deal)
        assert result["has_data"] is True
        cp = result["counterparty_product"]
        assert "counterparties" in cp
        assert "matrix" in cp


# ---------------------------------------------------------------------------
# 4. _build_deposit_behavior
# ---------------------------------------------------------------------------

class TestBuildDepositBehavior:
    def test_none_deals(self):
        result = _build_deposit_behavior(None)
        assert result["has_data"] is False

    def test_empty_deals(self, empty_df):
        result = _build_deposit_behavior(empty_df)
        assert result["has_data"] is False

    def test_no_deposit_direction(self):
        # All assets (L=Loan, B=Bond) — no deposits
        deals = pd.DataFrame({
            "Dealid": [1, 2],
            "Direction": ["L", "B"],
            "Currency": ["CHF", "EUR"],
            "NominalResiduel": [1e6, 2e6],
            "Product": ["IAM/LD", "IAM/LD"],
        })
        result = _build_deposit_behavior(deals)
        assert result["has_data"] is False

    def test_with_deposit_deals(self, sample_deals):
        result = _build_deposit_behavior(sample_deals)
        assert result["has_data"] is True
        assert "volume_by_ccy" in result
        assert "volume_by_product" in result
        assert "kpis" in result
        kpis = result["kpis"]
        assert kpis["total_deposits"] > 0
        assert kpis["deal_count"] > 0

    def test_with_nmd_profiles(self, sample_deals, sample_nmd_profiles):
        result = _build_deposit_behavior(sample_deals, sample_nmd_profiles)
        assert result["has_data"] is True
        beta = result["beta_analysis"]
        assert "by_tier" in beta
        assert len(beta["by_tier"]) > 0

    def test_with_nmd_and_stacked_df(self, sample_deals, sample_nmd_profiles, sample_stacked):
        result = _build_deposit_behavior(sample_deals, sample_nmd_profiles, sample_stacked)
        assert result["has_data"] is True
        beta = result["beta_analysis"]
        # implied_beta always present
        assert "implied_beta" in beta

    def test_concentration(self, sample_deals):
        result = _build_deposit_behavior(sample_deals)
        assert result["has_data"] is True
        conc = result["concentration"]
        assert "top_10" in conc
        # sample_deals has one deposit deal (Direction=D)
        assert len(conc["top_10"]) >= 1


# ---------------------------------------------------------------------------
# 5. _build_scenario_studio
# ---------------------------------------------------------------------------

class TestBuildScenarioStudio:
    def test_no_nii_at_risk(self, empty_df):
        result = _build_scenario_studio(empty_df, nii_at_risk=None)
        assert result["has_data"] is False

    def test_empty_nii_at_risk(self, empty_df):
        result = _build_scenario_studio(empty_df, nii_at_risk={"has_data": False})
        assert result["has_data"] is False

    def test_with_nii_at_risk(self, sample_stacked, nii_at_risk_data):
        result = _build_scenario_studio(sample_stacked, nii_at_risk=nii_at_risk_data)
        assert result["has_data"] is True
        assert len(result["combined"]) == len(nii_at_risk_data["scenarios"])
        assert len(result["ranking"]) == len(nii_at_risk_data["scenarios"])
        assert "probability_weighted" in result
        assert "decision_matrix" in result

    def test_ranking_is_sorted_worst_first(self, sample_stacked, nii_at_risk_data):
        result = _build_scenario_studio(sample_stacked, nii_at_risk=nii_at_risk_data)
        combined_impacts = [r["combined_impact"] for r in result["ranking"]]
        assert combined_impacts == sorted(combined_impacts)

    def test_probability_weighted_nii(self, sample_stacked, nii_at_risk_data):
        result = _build_scenario_studio(sample_stacked, nii_at_risk=nii_at_risk_data)
        pw = result["probability_weighted"]
        assert "expected_nii" in pw
        assert "base_nii" in pw

    def test_with_eve_data(self, sample_stacked, nii_at_risk_data):
        eve_data = {
            "has_data": True,
            "scenarios": {
                "heatmap": [
                    {"scenario": "parallel_up", "CHF": -300, "total": -300},
                    {"scenario": "parallel_down", "CHF": 200, "total": 200},
                    {"scenario": "steepener", "CHF": -100, "total": -100},
                    {"scenario": "flattener", "CHF": 50, "total": 50},
                ],
            },
        }
        result = _build_scenario_studio(
            sample_stacked, nii_at_risk=nii_at_risk_data, eve_data=eve_data
        )
        assert result["has_data"] is True
        assert result["has_eve"] is True
        # combined_impact should include both delta_nii and delta_eve
        for row in result["combined"]:
            assert "delta_eve" in row


# ---------------------------------------------------------------------------
# 6. _build_hedge_strategy
# ---------------------------------------------------------------------------

class TestBuildHedgeStrategy:
    def test_none_deals(self, empty_df):
        result = _build_hedge_strategy(empty_df, deals=None)
        assert result["has_data"] is False

    def test_empty_deals(self, empty_df):
        result = _build_hedge_strategy(empty_df, deals=empty_df)
        assert result["has_data"] is False

    def test_deals_without_nominal_col(self, empty_df):
        deals = pd.DataFrame({
            "Dealid": [1],
            "Direction": ["S"],
            "Currency": ["CHF"],
        })
        # Missing NominalResiduel/Nominal → ccy_col found but nom_col not found
        result = _build_hedge_strategy(empty_df, deals=deals)
        assert result["has_data"] is False

    def test_with_swap_deal(self, sample_stacked, sample_deals):
        result = _build_hedge_strategy(sample_stacked, deals=sample_deals)
        assert result["has_data"] is True
        assert "coverage" in result
        assert "kpis" in result
        kpis = result["kpis"]
        assert "overall_hedge_ratio" in kpis
        assert kpis["hedge_instrument_count"] >= 1  # one IRS/Direction=S deal

    def test_coverage_by_currency(self, sample_stacked, sample_deals):
        result = _build_hedge_strategy(sample_stacked, deals=sample_deals)
        assert result["has_data"] is True
        for cov in result["coverage"]:
            assert "currency" in cov
            assert "hedge_ratio" in cov
            assert 0.0 <= cov["hedge_ratio"] <= 1.0

    def test_with_pnl_by_deal(self, sample_stacked, sample_deals):
        pnl_by_deal = pd.DataFrame({
            "Dealid": [100004],
            "Shock": ["0"],
            "PnL": [-50.0],
            "Deal currency": ["CHF"],
            "Product": ["IRS"],
            "Direction": ["S"],
            "Counterparty": ["BankA"],
            "Month": [pd.Period("2026-04", "M")],
        })
        result = _build_hedge_strategy(
            sample_stacked, deals=sample_deals, pnl_by_deal=pnl_by_deal
        )
        assert result["has_data"] is True
        # Hedge cost should be populated
        assert "hedge_cost" in result

    def test_with_hedge_pairs(self, sample_stacked, sample_deals):
        hedge_pairs = pd.DataFrame({
            "pair_id": [1],
            "pair_name": ["CHF Hedge"],
            "hedged_item_deal_ids": ["100001"],
            "hedging_instrument_deal_ids": ["100004"],
            "hedge_type": ["cash_flow"],
            "ias_standard": ["IFRS9"],
        })
        result = _build_hedge_strategy(
            sample_stacked, deals=sample_deals, hedge_pairs=hedge_pairs
        )
        assert result["has_data"] is True


# ---------------------------------------------------------------------------
# 7. _build_alco_decision_pack
# ---------------------------------------------------------------------------

class TestBuildAlcoDecisionPack:
    def test_empty_result(self):
        result = _build_alco_decision_pack({})
        assert result["has_data"] is False

    def test_alco_no_metrics(self):
        mock_result = {"alco": {"has_data": False, "metrics": []}}
        result = _build_alco_decision_pack(mock_result)
        assert result["has_data"] is False

    def test_with_minimal_alco(self):
        mock_result = {
            "alco": {
                "has_data": True,
                "metrics": [
                    {
                        "metric": "Total NII (Base)",
                        "value": 1200,
                        "status": "neutral",
                        "delta_1d": None,
                        "limit": None,
                        "utilization": None,
                    }
                ],
            },
            "scenario_studio": {"has_data": False},
        }
        result = _build_alco_decision_pack(mock_result)
        assert result["has_data"] is True
        assert "sections" in result
        assert "executive_summary" in result
        assert "decisions" in result
        assert len(result["sections"]) == 5

    def test_red_metric_generates_exec_summary(self):
        mock_result = {
            "alco": {
                "has_data": True,
                "metrics": [
                    {
                        "metric": "Liquidity Net 30d",
                        "value": -5_000_000,
                        "status": "red",
                        "delta_1d": None,
                        "limit": None,
                        "utilization": None,
                    }
                ],
            },
            "scenario_studio": {"has_data": False},
        }
        result = _build_alco_decision_pack(mock_result)
        assert result["has_data"] is True
        assert any(s["severity"] == "critical" for s in result["executive_summary"])

    def test_red_liquidity_generates_decision(self):
        mock_result = {
            "alco": {
                "has_data": True,
                "metrics": [
                    {
                        "metric": "Liquidity Net 30d",
                        "value": -5_000_000,
                        "status": "red",
                        "delta_1d": None,
                        "limit": None,
                        "utilization": None,
                    }
                ],
            },
            "scenario_studio": {"has_data": False},
        }
        result = _build_alco_decision_pack(mock_result)
        assert result["has_data"] is True
        assert any(d["topic"] == "Liquidity" for d in result["decisions"])

    def test_critical_and_high_counts(self):
        mock_result = {
            "alco": {
                "has_data": True,
                "metrics": [
                    {
                        "metric": "NII Sensitivity (+50bp)",
                        "value": 300,
                        "status": "neutral",
                        "delta_1d": None,
                        "limit": 250,
                        "utilization": 95.0,
                    },
                ],
            },
            "scenario_studio": {"has_data": False},
        }
        result = _build_alco_decision_pack(mock_result)
        assert result["has_data"] is True
        assert "n_critical" in result
        assert "n_high" in result
        assert "n_medium" in result


# ---------------------------------------------------------------------------
# 8. _build_ftp
# ---------------------------------------------------------------------------

class TestBuildFtp:
    def test_none_deals(self, empty_df):
        result = _build_ftp(empty_df, deals=None)
        assert result["has_data"] is False

    def test_empty_deals(self, empty_df):
        result = _build_ftp(empty_df, deals=empty_df)
        assert result["has_data"] is False

    def test_deals_without_ftp_column(self, empty_df, sample_deals):
        deals_no_ftp = sample_deals.drop(columns=["FTP"])
        result = _build_ftp(empty_df, deals=deals_no_ftp)
        assert result["has_data"] is False

    def test_with_ftp_deals(self, empty_df, sample_deals):
        result = _build_ftp(empty_df, deals=sample_deals)
        assert result["has_data"] is True
        assert "perimeters" in result
        assert "by_currency" in result
        assert "top_deals" in result
        assert "totals" in result
        totals = result["totals"]
        assert "client_margin" in totals
        assert "alm_margin" in totals
        assert "total_nii" in totals

    def test_perimeter_breakdown(self, empty_df, sample_deals):
        result = _build_ftp(empty_df, deals=sample_deals)
        assert result["has_data"] is True
        # sample_deals has CC and WM perimeters
        for peri_data in result["perimeters"].values():
            assert "client_margin" in peri_data
            assert "alm_margin" in peri_data
            assert "deal_count" in peri_data

    def test_by_currency(self, empty_df, sample_deals):
        result = _build_ftp(empty_df, deals=sample_deals)
        for ccy_data in result["by_currency"].values():
            assert "client_margin" in ccy_data
            assert "alm_margin" in ccy_data

    def test_with_date_run(self, empty_df, sample_deals):
        result = _build_ftp(empty_df, deals=sample_deals, date_run=datetime(2026, 4, 6))
        assert result["has_data"] is True

    def test_ftp_decomposition_present(self, empty_df, sample_deals):
        """FTP decomposition should include duration/credit/liquidity split."""
        result = _build_ftp(empty_df, deals=sample_deals)
        if result["has_data"]:
            assert "ftp_decomposition" in result
            decomp = result["ftp_decomposition"]
            assert "duration_contribution_bps" in decomp
            assert "credit_spread_bps" in decomp
            assert "liquidity_premium_bps" in decomp
            assert "avg_alm_margin_bps" in decomp

    def test_ftp_decomposition_in_top_deals(self, empty_df, sample_deals):
        """Top deals should include per-deal decomposition fields."""
        result = _build_ftp(empty_df, deals=sample_deals)
        if result["has_data"] and result["top_deals"]:
            deal = result["top_deals"][0]
            assert "duration_contribution_bps" in deal
            assert "credit_spread_bps" in deal
            assert "liquidity_premium_bps" in deal


# ---------------------------------------------------------------------------
# 9. _build_trends
# ---------------------------------------------------------------------------

class TestBuildTrends:
    def test_none(self):
        result = _build_trends(None)
        assert result["has_data"] is False

    def test_empty_df(self, empty_df):
        result = _build_trends(empty_df)
        assert result["has_data"] is False

    def test_single_date(self):
        kpi_history = pd.DataFrame({
            "date": ["2026-04-01"],
            "nii_total": [1200.0],
            "nim_bps": [45.0],
        })
        result = _build_trends(kpi_history)
        # has_data requires len(dates) > 1
        assert result["has_data"] is False

    def test_with_multiple_dates(self):
        kpi_history = pd.DataFrame({
            "date": ["2026-04-01", "2026-04-02", "2026-04-03"],
            "nii_total": [1200.0, 1250.0, 1180.0],
            "nim_bps": [45.0, 46.0, 44.0],
        })
        result = _build_trends(kpi_history)
        assert result["has_data"] is True
        assert len(result["dates"]) == 3
        assert "nii_total" in result["metrics"]
        assert "nim_bps" in result["metrics"]

    def test_metric_statistics(self):
        kpi_history = pd.DataFrame({
            "date": ["2026-04-01", "2026-04-02", "2026-04-03"],
            "nii_total": [1000.0, 1100.0, 1200.0],
        })
        result = _build_trends(kpi_history)
        assert result["has_data"] is True
        m = result["metrics"]["nii_total"]
        assert m["latest"] == 1200.0
        assert m["min"] == 1000.0
        assert m["max"] == 1200.0
        assert m["trend"] == "up"

    def test_trend_down(self):
        kpi_history = pd.DataFrame({
            "date": ["2026-04-01", "2026-04-02"],
            "nii_total": [1200.0, 900.0],
        })
        result = _build_trends(kpi_history)
        assert result["has_data"] is True
        assert result["metrics"]["nii_total"]["trend"] == "down"


# ---------------------------------------------------------------------------
# 10. _build_regulatory
# ---------------------------------------------------------------------------

class TestBuildRegulatory:
    def test_empty_result(self):
        result = _build_regulatory({})
        assert result["has_data"] is False
        assert result["checks"] == []

    def test_minimal_result_no_modules(self):
        mock_result = {
            "eve": {"has_data": False},
            "nii_at_risk": {"has_data": False},
            "liquidity": {"has_data": False},
            "limits": {"has_data": False},
            "counterparty_pnl": {"has_data": False},
            "summary": {"kpis": {}},
        }
        result = _build_regulatory(mock_result)
        assert result["has_data"] is False

    def test_with_nii_at_risk(self, nii_at_risk_data):
        mock_result = {
            "eve": {"has_data": False},
            "nii_at_risk": nii_at_risk_data,
            "liquidity": {"has_data": False},
            "limits": {"has_data": False},
            "counterparty_pnl": {"has_data": False},
            "summary": {"kpis": {"shock_0": {"total": 1300}}},
        }
        result = _build_regulatory(mock_result)
        assert result["has_data"] is True
        nii_checks = [c for c in result["checks"] if "NII Floor" in c["regulation"]]
        assert len(nii_checks) == 1
        assert "status" in nii_checks[0]

    def test_with_liquidity_positive(self):
        mock_result = {
            "eve": {"has_data": False},
            "nii_at_risk": {"has_data": False},
            "liquidity": {
                "has_data": True,
                "summary": {"net_30d": 5_000_000, "survival_days": None},
            },
            "limits": {"has_data": False},
            "counterparty_pnl": {"has_data": False},
            "summary": {"kpis": {}},
        }
        result = _build_regulatory(mock_result)
        assert result["has_data"] is True
        lcr_checks = [c for c in result["checks"] if "LCR" in c["regulation"]]
        assert len(lcr_checks) == 1
        assert lcr_checks[0]["status"] == "PASS"

    def test_with_liquidity_negative(self):
        mock_result = {
            "eve": {"has_data": False},
            "nii_at_risk": {"has_data": False},
            "liquidity": {
                "has_data": True,
                "summary": {"net_30d": -2_000_000, "survival_days": None},
            },
            "limits": {"has_data": False},
            "counterparty_pnl": {"has_data": False},
            "summary": {"kpis": {}},
        }
        result = _build_regulatory(mock_result)
        lcr_checks = [c for c in result["checks"] if "LCR" in c["regulation"]]
        assert len(lcr_checks) == 1
        assert lcr_checks[0]["status"] == "FAIL"

    def test_summary_counts(self, nii_at_risk_data):
        mock_result = {
            "eve": {"has_data": False},
            "nii_at_risk": nii_at_risk_data,
            "liquidity": {
                "has_data": True,
                "summary": {"net_30d": 5_000_000, "survival_days": None},
            },
            "limits": {"has_data": False},
            "counterparty_pnl": {"has_data": False},
            "summary": {"kpis": {"shock_0": {"total": 1300}}},
        }
        result = _build_regulatory(mock_result)
        assert result["has_data"] is True
        summary = result["summary"]
        assert "pass" in summary
        assert "watch" in summary
        assert "fail" in summary
        assert summary["total"] == len(result["checks"])


# ---------------------------------------------------------------------------
# 11. _build_nmd_audit
# ---------------------------------------------------------------------------

class TestBuildNmdAudit:
    def test_none_deals(self, sample_nmd_profiles):
        result = _build_nmd_audit(None, sample_nmd_profiles)
        assert result["has_data"] is False

    def test_none_profiles(self, sample_deals):
        result = _build_nmd_audit(sample_deals, None)
        assert result["has_data"] is False

    def test_empty_profiles(self, sample_deals, empty_df):
        result = _build_nmd_audit(sample_deals, empty_df)
        assert result["has_data"] is False

    def test_no_matching_deals(self):
        # Deals with direction L — no deposit, profiles expect D
        deals = pd.DataFrame({
            "Dealid": [1, 2],
            "Product": ["IAM/LD", "IAM/LD"],
            "Direction": ["L", "L"],
            "Currency": ["CHF", "EUR"],
            "Nominal": [1e6, 2e6],
        })
        profiles = pd.DataFrame({
            "product": ["IAM/LD"],
            "currency": ["CHF"],
            "direction": ["D"],
            "tier": ["CORE"],
            "decay_rate": [0.05],
            "deposit_beta": [0.30],
            "floor_rate": [0.0],
            "behavioral_maturity_years": [5.0],
        })
        result = _build_nmd_audit(deals, profiles)
        assert result["has_data"] is False

    def test_with_matching_deals(self, sample_nmd_profiles):
        # Use a deposit deal that matches the profiles fixture
        deals = pd.DataFrame({
            "Dealid": [200001, 200002],
            "Product": ["IAM/LD", "IAM/LD"],
            "Direction": ["D", "D"],
            "Currency": ["CHF", "EUR"],
            "Nominal": [3_000_000.0, 1_500_000.0],
        })
        result = _build_nmd_audit(deals, sample_nmd_profiles)
        assert result["has_data"] is True
        assert result["matched_deals"] == 2
        assert result["total_deals"] == 2
        assert len(result["tier_summary"]) > 0
        assert "chart" in result
        assert "deal_details" in result
        assert "profiles" in result

    def test_unmatched_count(self, sample_nmd_profiles):
        deals = pd.DataFrame({
            "Dealid": [1, 2, 3],
            "Product": ["IAM/LD", "IAM/LD", "UNKNOWN_PROD"],
            "Direction": ["D", "D", "D"],
            "Currency": ["CHF", "EUR", "CHF"],
            "Nominal": [1e6, 2e6, 3e6],
        })
        result = _build_nmd_audit(deals, sample_nmd_profiles)
        assert result["has_data"] is True
        assert result["unmatched_deals"] == 1

    def test_chart_structure(self, sample_nmd_profiles):
        deals = pd.DataFrame({
            "Dealid": [1, 2],
            "Product": ["IAM/LD", "IAM/LD"],
            "Direction": ["D", "D"],
            "Currency": ["CHF", "EUR"],
            "Nominal": [1e6, 2e6],
        })
        result = _build_nmd_audit(deals, sample_nmd_profiles)
        assert result["has_data"] is True
        chart = result["chart"]
        assert "currencies" in chart
        assert "datasets" in chart
        assert len(chart["datasets"]) == len(result["tier_summary"])


# ---------------------------------------------------------------------------
# 12. _build_liquidity
# ---------------------------------------------------------------------------

class TestBuildLiquidity:
    def test_none_schedule(self):
        result = _build_liquidity(None)
        assert result["has_data"] is False

    def test_empty_schedule(self, empty_df):
        result = _build_liquidity(empty_df)
        assert result["has_data"] is False

    def test_schedule_without_date_cols(self):
        df = pd.DataFrame({
            "Dealid": [1],
            "Currency": ["CHF"],
            "Direction": ["L"],
            "SomeOtherCol": [999],
        })
        result = _build_liquidity(df)
        assert result["has_data"] is False

    def test_with_monthly_schedule(self):
        schedule = pd.DataFrame({
            "Dealid": [100001, 100002],
            "Currency": ["CHF", "CHF"],
            "Direction": ["L", "D"],
            "2026/04": [500_000.0, -300_000.0],
            "2026/05": [200_000.0, -100_000.0],
            "2026/06": [1_000_000.0, -500_000.0],
        })
        result = _build_liquidity(schedule)
        assert result["has_data"] is True
        assert "by_currency" in result
        assert "CHF" in result["by_currency"]
        assert "summary" in result
        ccy_data = result["by_currency"]["CHF"]
        assert "labels" in ccy_data
        assert "inflows" in ccy_data
        assert "outflows" in ccy_data
        assert "net" in ccy_data
        assert "cumulative" in ccy_data
        assert len(ccy_data["labels"]) == 3

    def test_with_daily_schedule(self):
        schedule = pd.DataFrame({
            "Dealid": [100001],
            "Currency": ["CHF"],
            "Direction": ["L"],
            "2026/04/01": [100_000.0],
            "2026/04/15": [200_000.0],
            "2026/05/01": [500_000.0],
        })
        result = _build_liquidity(schedule)
        assert result["has_data"] is True
        assert "CHF" in result["by_currency"]
        assert len(result["by_currency"]["CHF"]["labels"]) == 3

    def test_summary_kpis(self):
        schedule = pd.DataFrame({
            "Dealid": [100001, 100002],
            "Currency": ["CHF", "EUR"],
            "Direction": ["L", "D"],
            "2026/04": [1_000_000.0, -800_000.0],
            "2026/05": [500_000.0, -200_000.0],
        })
        result = _build_liquidity(schedule)
        assert result["has_data"] is True
        summary = result["summary"]
        assert "net_30d" in summary
        assert "net_90d" in summary

    def test_top_maturities(self):
        schedule = pd.DataFrame({
            "Dealid": [100001, 100002, 100003],
            "Currency": ["CHF", "CHF", "EUR"],
            "Direction": ["L", "L", "D"],
            # Use a date in the near future (within 30 days of "now" is tricky to test
            # deterministically, so we just verify the key is present)
            "2026/04": [5_000_000.0, 2_000_000.0, -1_000_000.0],
        })
        result = _build_liquidity(schedule)
        assert result["has_data"] is True
        assert "top_maturities" in result
        assert isinstance(result["top_maturities"], list)

    def test_with_deals_reinvestment(self):
        schedule = pd.DataFrame({
            "Dealid": [100001],
            "Currency": ["CHF"],
            "Direction": ["L"],
            "2026/04": [1_000_000.0],
        })
        deals = pd.DataFrame({
            "Dealid": [100001],
            "Currency": ["CHF"],
            "Direction": ["L"],
            "Clientrate": [0.025],
            "EqOisRate": [0.015],
            "Maturitydate": [datetime(2026, 5, 1)],
        })
        result = _build_liquidity(schedule, deals)
        assert result["has_data"] is True
        assert "reinvestment" in result
