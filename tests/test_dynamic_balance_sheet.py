"""Tests for dynamic balance sheet — reinvestment of maturing deals."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pnl_engine.dynamic_balance_sheet import ProductionPlan, project_balance_sheet


@pytest.fixture
def basic_setup():
    """Create a minimal deal set with known maturity dates."""
    date_run = datetime(2026, 4, 1)
    days = pd.date_range("2026-04-01", periods=365, freq="D")
    month_cols = [f"2026/{m:02d}" for m in range(4, 13)] + [f"2027/{m:02d}" for m in range(1, 4)]

    deals = pd.DataFrame({
        "Dealid": [1, 2, 3],
        "Product": ["IAM/LD", "IAM/LD", "BND"],
        "Currency": ["CHF", "CHF", "EUR"],
        "Direction": ["D", "D", "B"],
        "Amount": [10_000_000, 5_000_000, -8_000_000],
        "Clientrate": [0.02, 0.025, 0.03],
        "EqOisRate": [0.015, 0.015, 0.02],
        "Maturitydate": [
            pd.Timestamp("2026-06-15"),  # matures month 2026/06
            pd.Timestamp("2026-08-20"),  # matures month 2026/08
            pd.Timestamp("2026-07-01"),  # matures month 2026/07
        ],
    })

    # Simple constant nominal schedule
    nominal = np.zeros((3, len(days)))
    for i in range(3):
        mat = pd.Timestamp(deals.iloc[i]["Maturitydate"])
        for j, d in enumerate(days):
            if d < mat:
                nominal[i, j] = deals.iloc[i]["Amount"]

    return deals, nominal, days, month_cols, date_run


class TestProductionPlan:
    def test_dataclass_creation(self):
        plan = ProductionPlan(
            product="IAM/LD", currency="CHF", direction="D",
            monthly_volume=5_000_000, tenor_years=3.0, rate_spread_bps=50.0,
        )
        assert plan.product == "IAM/LD"
        assert plan.rate_spread_bps == 50.0

    def test_default_spread(self):
        plan = ProductionPlan(
            product="IAM/LD", currency="CHF", direction="D",
            monthly_volume=5_000_000, tenor_years=3.0,
        )
        assert plan.rate_spread_bps == 0.0


class TestProjectBalanceSheet:
    def test_no_plans_returns_unchanged(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        result_nom, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, [], date_run,
        )
        assert result_nom is nominal
        assert result_deals is deals
        assert log == []

    def test_single_deal_replacement(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0, rate_spread_bps=50.0,
            ),
        ]
        result_nom, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )

        # Should have added synthetic deals (IAM/LD CHF D matches deals 1 & 2)
        assert len(result_deals) > len(deals)
        assert result_nom.shape[0] > nominal.shape[0]
        assert len(log) > 0

        # Synthetic deals should be marked
        synthetic = result_deals[result_deals.get("is_synthetic", False) == True]
        assert len(synthetic) > 0
        assert all(synthetic["Counterparty"] == "PRODUCTION_PLAN")

    def test_synthetic_deal_metadata(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0, rate_spread_bps=50.0,
            ),
        ]
        _, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        synthetic = result_deals[result_deals.get("is_synthetic", False) == True]
        row = synthetic.iloc[0]
        assert row["Product"] == "IAM/LD"
        assert row["Currency"] == "CHF"
        assert row["Direction"] == "D"
        assert row["Dealid"] > 900000

    def test_ois_spread_pricing(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0, rate_spread_bps=100.0,
            ),
        ]
        ois_curve = {"CHF": 0.015}
        _, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
            ois_curve=ois_curve,
        )
        # Client rate = OIS (1.5%) + spread (100bp = 1%) = 2.5%
        entry = log[0]
        assert abs(entry["client_rate"] - 0.025) < 1e-6
        assert entry["ois_rate"] == 0.015

    def test_nominal_extends_matrix(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0,
            ),
        ]
        result_nom, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        n_synthetic = len(log)
        assert result_nom.shape == (len(deals) + n_synthetic, len(days))

    def test_no_matching_deals(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        # Plan for a product/currency not in deals
        plans = [
            ProductionPlan(
                product="SAVINGS", currency="USD", direction="D",
                monthly_volume=1_000_000, tenor_years=2.0,
            ),
        ]
        result_nom, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        assert result_nom is nominal
        assert result_deals is deals
        assert log == []

    def test_projection_log_fields(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0, rate_spread_bps=50.0,
            ),
        ]
        _, _, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        entry = log[0]
        expected_fields = {
            "deal_id", "product", "currency", "direction", "maturing_month",
            "maturing_amount", "new_volume", "tenor_years", "client_rate",
            "ois_rate", "spread_bps", "start_date", "maturity_date",
        }
        assert expected_fields.issubset(set(entry.keys()))

    def test_multiple_plans(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0,
            ),
            ProductionPlan(
                product="BND", currency="EUR", direction="B",
                monthly_volume=4_000_000, tenor_years=5.0,
            ),
        ]
        _, result_deals, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        currencies = {e["currency"] for e in log}
        assert "CHF" in currencies
        assert "EUR" in currencies

    def test_already_matured_deals_ignored(self, basic_setup):
        deals, nominal, days, month_cols, date_run = basic_setup
        # Set maturity to before date_run
        deals.loc[0, "Maturitydate"] = pd.Timestamp("2026-03-01")
        plans = [
            ProductionPlan(
                product="IAM/LD", currency="CHF", direction="D",
                monthly_volume=5_000_000, tenor_years=3.0,
            ),
        ]
        _, _, log = project_balance_sheet(
            deals, nominal, days, month_cols, plans, date_run,
        )
        # Only deal 2 (2026-08) should generate a synthetic, deal 1 already matured
        maturing_months = {e["maturing_month"] for e in log}
        assert "2026/03" not in maturing_months

    def test_no_maturitydate_column(self):
        """No Maturitydate column should return unchanged."""
        deals = pd.DataFrame({"Dealid": [1], "Product": ["X"], "Currency": ["CHF"]})
        nominal = np.ones((1, 30))
        days = pd.date_range("2026-04-01", periods=30)
        plans = [ProductionPlan("X", "CHF", "D", 1e6, 3.0)]
        result_nom, result_deals, log = project_balance_sheet(
            deals, nominal, days, [], plans, datetime(2026, 4, 1),
        )
        assert result_nom is nominal
        assert log == []


class TestParseProductionPlan:
    def test_parse_roundtrip(self, tmp_path):
        """Create an Excel file and parse it back."""
        df = pd.DataFrame({
            "product": ["IAM/LD", "BND"],
            "currency": ["CHF", "EUR"],
            "direction": ["D", "B"],
            "monthly_volume": [5_000_000, 3_000_000],
            "tenor_years": [3.0, 5.0],
            "rate_spread_bps": [50.0, 75.0],
        })
        path = tmp_path / "production_plan.xlsx"
        df.to_excel(path, sheet_name="ProductionPlan", index=False)

        from cockpit.data.parsers.production_plan import parse_production_plan
        plans = parse_production_plan(path)
        assert len(plans) == 2
        assert plans[0].product == "IAM/LD"
        assert plans[0].monthly_volume == 5_000_000
        assert plans[1].rate_spread_bps == 75.0

    def test_missing_columns(self, tmp_path):
        df = pd.DataFrame({"product": ["X"], "currency": ["CHF"]})
        path = tmp_path / "bad.xlsx"
        df.to_excel(path, index=False)

        from cockpit.data.parsers.production_plan import parse_production_plan
        with pytest.raises(ValueError, match="missing"):
            parse_production_plan(path)

    def test_default_spread(self, tmp_path):
        df = pd.DataFrame({
            "product": ["IAM/LD"],
            "currency": ["CHF"],
            "direction": ["D"],
            "monthly_volume": [5_000_000],
            "tenor_years": [3.0],
        })
        path = tmp_path / "production_plan.xlsx"
        df.to_excel(path, sheet_name="ProductionPlan", index=False)

        from cockpit.data.parsers.production_plan import parse_production_plan
        plans = parse_production_plan(path)
        assert plans[0].rate_spread_bps == 0.0

    def test_filters_unsupported_currencies(self, tmp_path):
        df = pd.DataFrame({
            "product": ["IAM/LD", "IAM/LD"],
            "currency": ["CHF", "JPY"],
            "direction": ["D", "D"],
            "monthly_volume": [5e6, 3e6],
            "tenor_years": [3.0, 3.0],
        })
        path = tmp_path / "production_plan.xlsx"
        df.to_excel(path, sheet_name="ProductionPlan", index=False)

        from cockpit.data.parsers.production_plan import parse_production_plan
        plans = parse_production_plan(path)
        assert len(plans) == 1
        assert plans[0].currency == "CHF"
