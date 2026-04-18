"""Tests for the daily reconciliation module (Phase 5, approach B)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cockpit.engine.reconciliation import (
    DEFAULT_TOLERANCES_BPS,
    FALLBACK_TOLERANCE_BPS,
    RECONCILIATION_SHEET_NAME,
    export_reconciliation,
    reconcile_daily,
)


def _deals(rows: list[dict]) -> pd.DataFrame:
    """rows: dicts with IAS Book, Category2, PnL_Realized, Amount_CHF (+ Dealid)."""
    base = {"Dealid": "D?"}
    return pd.DataFrame([{**base, **r} for r in rows])


def _synthesis(rows: list[tuple[str, str, float]], month_col: str = "2026/04") -> pd.DataFrame:
    """rows: list of (Book, Category2, month_value)."""
    return pd.DataFrame(
        [{"IAS Book": b, "Category2": c, month_col: v} for b, c, v in rows]
    )


class TestReconcileDaily:
    def test_green_when_realized_matches_prorata(self):
        # 30 days in April; month forecast 3000 → daily 100; realized 100 → delta 0 → Green
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 100.0, "Amount_CHF": -10_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 3000.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")].iloc[0]
        assert row["Status"] == "Green"
        assert abs(row["Delta_CHF"]) < 1e-6

    def test_red_when_large_delta(self):
        # OPP_CASH tolerance = 5 bps. Big deviation → Red.
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 50_000.0, "Amount_CHF": -10_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 3000.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")].iloc[0]
        assert row["Status"] == "Red"

    def test_notional_uses_absolute_value(self):
        # Assets have negative Amount_CHF; notional must come out positive
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 0.0, "Amount_CHF": -5_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")].iloc[0]
        assert row["Notional_CHF"] == 5_000_000.0

    def test_groupby_sums_across_deals(self):
        deals = _deals([
            {"IAS Book": "BOOK1", "Category2": "OPP_CASH", "PnL_Realized": 30.0, "Amount_CHF": -1_000_000.0},
            {"IAS Book": "BOOK1", "Category2": "OPP_CASH", "PnL_Realized": 70.0, "Amount_CHF": -2_000_000.0},
        ])
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")].iloc[0]
        assert row["Realized_CHF"] == 100.0
        assert row["Notional_CHF"] == 3_000_000.0

    def test_missing_month_column_warns_and_uses_zero_forecast(self):
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 10.0, "Amount_CHF": -1_000_000.0,
        }])
        # Synthesis for a different month
        syn = _synthesis([("BOOK1", "OPP_CASH", 9999.0)], month_col="2099/12")
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")].iloc[0]
        assert row["Forecast_Daily_CHF"] == 0.0
        assert row["Delta_CHF"] == 10.0

    def test_bucket_missing_from_synthesis_gets_zero_forecast(self):
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "Other",
            "PnL_Realized": 5.0, "Amount_CHF": -500_000.0,
        }])
        # Synthesis has only OPP_CASH
        syn = _synthesis([("BOOK1", "OPP_CASH", 3000.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[out["Category2"] == "Other"].iloc[0]
        assert row["Forecast_Daily_CHF"] == 0.0

    def test_total_row_present_and_aggregates(self):
        deals = _deals([
            {"IAS Book": "BOOK1", "Category2": "OPP_CASH", "PnL_Realized": 10.0, "Amount_CHF": -1_000_000.0},
            {"IAS Book": "BOOK2", "Category2": "IRS_FVH", "PnL_Realized": 20.0, "Amount_CHF": 2_000_000.0},
        ])
        syn = _synthesis([
            ("BOOK1", "OPP_CASH", 300.0),
            ("BOOK2", "IRS_FVH", 600.0),
        ])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        total = out[out["Category2"] == "Total"].iloc[0]
        assert total["Realized_CHF"] == 30.0
        assert total["Notional_CHF"] == 3_000_000.0

    def test_tolerance_override_applied(self):
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 100.0, "Amount_CHF": -10_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        out = reconcile_daily(
            deals, syn,
            position_date=pd.Timestamp("2026-04-15"),
            tolerances_bps={"OPP_CASH": 0.0},  # zero tolerance → any delta is Red
        )
        row = out[out["Category2"] == "OPP_CASH"].iloc[0]
        assert row["Tolerance_bps"] == 0.0
        assert row["Status"] == "Red"

    def test_unknown_category_uses_fallback_tolerance(self):
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "UNKNOWN_BUCKET",
            "PnL_Realized": 0.0, "Amount_CHF": -1_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "UNKNOWN_BUCKET", 0.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[out["Category2"] == "UNKNOWN_BUCKET"].iloc[0]
        assert row["Tolerance_bps"] == FALLBACK_TOLERANCE_BPS

    def test_zero_notional_gives_zero_bps(self):
        # Avoid div-by-zero when a bucket has no notional
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 100.0, "Amount_CHF": 0.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[out["Category2"] == "OPP_CASH"].iloc[0]
        assert row["Delta_bps_annualized"] == 0.0

    def test_amber_band(self):
        # Pick a delta that lands between 1x and 2x tolerance
        # OPP_CASH tolerance = 5 bps, notional = 10M, days = 30
        # For delta to equal 7.5 bps annualized: delta_CHF * 365 / 10M * 1e4 = 7.5
        # → delta_CHF = 7.5 * 10M / 365 / 1e4 = 20.55
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 20.55, "Amount_CHF": -10_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        row = out[out["Category2"] == "OPP_CASH"].iloc[0]
        assert row["Status"] == "Amber"

    def test_missing_required_column_raises(self):
        deals = pd.DataFrame({"IAS Book": ["BOOK1"], "Category2": ["OPP_CASH"]})
        syn = _synthesis([("BOOK1", "OPP_CASH", 0.0)])
        with pytest.raises(ValueError):
            reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))


class TestExport:
    def test_roundtrip(self, tmp_path: Path):
        deals = _deals([{
            "IAS Book": "BOOK1", "Category2": "OPP_CASH",
            "PnL_Realized": 100.0, "Amount_CHF": -10_000_000.0,
        }])
        syn = _synthesis([("BOOK1", "OPP_CASH", 3000.0)])
        out = reconcile_daily(deals, syn, position_date=pd.Timestamp("2026-04-15"))
        path = tmp_path / "reconciliation_20260415.xlsx"
        export_reconciliation(out, path)
        assert path.exists()
        loaded = pd.read_excel(path, sheet_name=RECONCILIATION_SHEET_NAME)
        assert "Status" in loaded.columns
        assert (loaded["Category2"] == "Total").any()
