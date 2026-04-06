"""Tests for cockpit.data.quality."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from cockpit.data.quality import (
    DataQualityReport,
    QualityCheck,
    build_quality_report,
    check_deal_rate_match,
    check_field_coverage,
    check_orphan_deals,
    check_rate_staleness,
    is_rate_stale,
)


class TestIsRateStale:
    def test_fresh_rate(self):
        assert not is_rate_stale(datetime(2026, 4, 4), datetime(2026, 4, 5))

    def test_stale_rate(self):
        assert is_rate_stale(datetime(2026, 3, 30), datetime(2026, 4, 5))

    def test_string_date(self):
        assert not is_rate_stale("2026-04-04", datetime(2026, 4, 5))

    def test_bad_string(self):
        assert is_rate_stale("not-a-date", datetime(2026, 4, 5))

    def test_none(self):
        assert is_rate_stale(None, datetime(2026, 4, 5))

    def test_custom_max_age(self):
        assert not is_rate_stale(datetime(2026, 4, 1), datetime(2026, 4, 5), max_age_days=5)
        assert is_rate_stale(datetime(2026, 3, 30), datetime(2026, 4, 5), max_age_days=5)


class TestCheckDealRateMatch:
    def test_no_deals(self):
        result = check_deal_rate_match(None, pd.DataFrame())
        assert result.status == "warn"

    def test_no_echeancier(self):
        deals = pd.DataFrame({"Dealid": ["1"], "Direction": ["B"], "Currency": ["CHF"]})
        result = check_deal_rate_match(deals, None)
        assert result.status == "fail"

    def test_full_match(self):
        deals = pd.DataFrame({"Dealid": ["1", "2"], "Direction": ["B", "L"], "Currency": ["CHF", "EUR"]})
        ech = pd.DataFrame({"Dealid": ["1", "2"], "Direction": ["B", "L"], "Currency": ["CHF", "EUR"]})
        result = check_deal_rate_match(deals, ech)
        assert result.status == "pass"
        assert result.value == 100.0

    def test_partial_match(self):
        deals = pd.DataFrame({"Dealid": ["1", "2", "3"], "Direction": ["B", "L", "B"], "Currency": ["CHF", "EUR", "USD"]})
        ech = pd.DataFrame({"Dealid": ["1"], "Direction": ["B"], "Currency": ["CHF"]})
        result = check_deal_rate_match(deals, ech)
        assert result.status == "fail"  # 33% < 80%


class TestCheckOrphanDeals:
    def test_no_orphans(self):
        deals = pd.DataFrame({"Dealid": ["1", "2"]})
        ech = pd.DataFrame({"Dealid": ["1", "2", "3"]})
        result = check_orphan_deals(deals, ech)
        assert result.status == "pass"
        assert result.value == 0

    def test_some_orphans(self):
        deals = pd.DataFrame({"Dealid": ["1", "2", "3"]})
        ech = pd.DataFrame({"Dealid": ["1"]})
        result = check_orphan_deals(deals, ech)
        assert result.value == 2


class TestCheckFieldCoverage:
    def test_full_coverage(self):
        deals = pd.DataFrame({"Dealid": ["1"], "Currency": ["CHF"], "Amount": [100]})
        cov = check_field_coverage(deals)
        assert cov["Dealid"] == 100.0
        assert cov["Currency"] == 100.0

    def test_partial_coverage(self):
        deals = pd.DataFrame({"Dealid": ["1", None], "Currency": ["CHF", "EUR"]})
        cov = check_field_coverage(deals)
        assert cov["Dealid"] == 50.0
        assert cov["Currency"] == 100.0

    def test_empty(self):
        assert check_field_coverage(None) == {}


class TestCheckRateStaleness:
    def test_fresh_curves(self):
        curves = pd.DataFrame({"date": [datetime(2026, 4, 4)], "rate": [0.01]})
        result = check_rate_staleness(curves, datetime(2026, 4, 5))
        assert result.status == "pass"

    def test_stale_curves(self):
        curves = pd.DataFrame({"date": [datetime(2026, 3, 30)], "rate": [0.01]})
        result = check_rate_staleness(curves, datetime(2026, 4, 5))
        assert result.status == "fail"

    def test_no_curves(self):
        result = check_rate_staleness(None, datetime(2026, 4, 5))
        assert result.status == "warn"


class TestBuildQualityReport:
    def test_empty_report(self):
        report = build_quality_report(datetime(2026, 4, 5))
        assert isinstance(report, DataQualityReport)
        assert report.n_fail == 0  # no deals = warn, not fail

    def test_full_report(self):
        deals = pd.DataFrame({
            "Dealid": ["1", "2"],
            "Direction": ["B", "L"],
            "Currency": ["CHF", "EUR"],
            "Amount": [100, 200],
            "Product": ["IAM/LD", "BND"],
        })
        ech = pd.DataFrame({
            "Dealid": ["1", "2"],
            "Direction": ["B", "L"],
            "Currency": ["CHF", "EUR"],
        })
        curves = pd.DataFrame({"date": [datetime(2026, 4, 4)], "rate": [0.01]})
        report = build_quality_report(datetime(2026, 4, 5), deals, ech, curves)
        assert report.n_pass >= 2
        d = report.to_dict()
        assert "checks" in d
        assert "coverage" in d

    def test_report_to_dict(self):
        report = DataQualityReport(
            date_run=datetime(2026, 4, 5),
            checks=[QualityCheck("Test", "pass", 100, "OK")],
        )
        d = report.to_dict()
        assert d["overall_status"] == "pass"
        assert d["n_pass"] == 1
