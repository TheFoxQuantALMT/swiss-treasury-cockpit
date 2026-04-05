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
                           "GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate"):
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
        assert set(result.keys()) == {"summary", "coc", "pnl_series", "sensitivity", "strategy", "book2", "curves"}

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
