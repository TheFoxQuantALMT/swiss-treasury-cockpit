"""Tests for repricing gap analysis (pnl_engine.repricing)."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from pnl_engine.repricing import compute_repricing_gap, _assign_bucket, _repricing_days


class TestAssignBucket:
    def test_overnight(self):
        assert _assign_bucket(0) == "O/N"
        assert _assign_bucket(1) == "O/N"

    def test_one_week(self):
        assert _assign_bucket(5) == "1W"
        assert _assign_bucket(7) == "1W"

    def test_one_month(self):
        assert _assign_bucket(15) == "1M"
        assert _assign_bucket(30) == "1M"

    def test_three_month(self):
        assert _assign_bucket(60) == "3M"
        assert _assign_bucket(90) == "3M"

    def test_beyond_5y(self):
        assert _assign_bucket(2000) == ">5Y"
        assert _assign_bucket(float("inf")) == ">5Y"


class TestRepricingDays:
    @pytest.fixture
    def ref_date(self):
        return datetime(2026, 4, 5)

    def test_fixed_rate_uses_maturity(self, ref_date):
        row = pd.Series({"is_floating": False, "Maturitydate": "2027-04-05"})
        assert _repricing_days(row, ref_date) == 365

    def test_floating_uses_next_fixing(self, ref_date):
        row = pd.Series({"is_floating": True, "next_fixing_date": "2026-04-12"})
        assert _repricing_days(row, ref_date) == 7

    def test_floating_no_fixing_date(self, ref_date):
        row = pd.Series({"is_floating": True})
        assert _repricing_days(row, ref_date) == 0

    def test_no_maturity(self, ref_date):
        row = pd.Series({"is_floating": False})
        assert _repricing_days(row, ref_date) == float("inf")


class TestComputeRepricingGap:
    def test_empty_deals(self):
        result = compute_repricing_gap(None, pd.DataFrame(), datetime(2026, 4, 5))
        assert result.empty

    def test_missing_columns(self):
        deals = pd.DataFrame({"foo": [1]})
        result = compute_repricing_gap(deals, pd.DataFrame(), datetime(2026, 4, 5))
        assert result.empty

    def test_basic_gap(self):
        deals = pd.DataFrame([
            {"Dealid": "1", "Direction": "B", "Currency": "CHF", "Amount": 1_000_000,
             "is_floating": False, "Maturitydate": "2026-07-05", "Product": "IAM/LD"},
            {"Dealid": "2", "Direction": "L", "Currency": "CHF", "Amount": 600_000,
             "is_floating": False, "Maturitydate": "2026-07-05", "Product": "IAM/LD"},
        ])
        result = compute_repricing_gap(deals, pd.DataFrame(), datetime(2026, 4, 5))
        assert not result.empty
        assert "currency" in result.columns
        assert "gap" in result.columns
        assert "cumulative_gap" in result.columns
        # 91 days → 6M bucket (>90, <=180)
        bucket_6m = result[(result["currency"] == "CHF") & (result["bucket"] == "6M")]
        assert len(bucket_6m) == 1
        assert bucket_6m.iloc[0]["assets"] == 1_000_000
        assert bucket_6m.iloc[0]["liabilities"] == 600_000
        assert bucket_6m.iloc[0]["gap"] == 400_000

    def test_multiple_currencies(self):
        deals = pd.DataFrame([
            {"Dealid": "1", "Direction": "B", "Currency": "CHF", "Amount": 1_000_000,
             "is_floating": False, "Maturitydate": "2027-04-05", "Product": "IAM/LD"},
            {"Dealid": "2", "Direction": "B", "Currency": "EUR", "Amount": 500_000,
             "is_floating": False, "Maturitydate": "2027-04-05", "Product": "IAM/LD"},
        ])
        result = compute_repricing_gap(deals, pd.DataFrame(), datetime(2026, 4, 5))
        currencies = result["currency"].unique()
        assert "CHF" in currencies
        assert "EUR" in currencies

    def test_cumulative_gap(self):
        deals = pd.DataFrame([
            {"Dealid": "1", "Direction": "B", "Currency": "CHF", "Amount": 100,
             "is_floating": True, "next_fixing_date": "2026-04-06", "Product": "IAM/LD"},
            {"Dealid": "2", "Direction": "B", "Currency": "CHF", "Amount": 200,
             "is_floating": False, "Maturitydate": "2026-05-05", "Product": "IAM/LD"},
        ])
        result = compute_repricing_gap(deals, pd.DataFrame(), datetime(2026, 4, 5))
        chf = result[result["currency"] == "CHF"].sort_values("bucket_order")
        # Cumulative should increase
        cum = chf["cumulative_gap"].values
        assert cum[-1] == chf["gap"].sum()
