"""Tests for cockpit.integrations.peer_benchmark module."""
from __future__ import annotations

import pytest

from cockpit.integrations.peer_benchmark import (
    FINMA_AGGREGATES,
    compute_peer_comparison,
)


class TestFinmaAggregatesStructure:
    """Validate the FINMA_AGGREGATES constant."""

    def test_expected_metrics_present(self):
        expected_keys = {
            "delta_eve_pct_tier1",
            "nii_sensitivity_pct",
            "avg_duration_years",
            "nmd_share_pct",
        }
        assert set(FINMA_AGGREGATES.keys()) == expected_keys

    def test_each_metric_has_required_fields(self):
        required = {"p25", "median", "p75", "mean", "label"}
        for key, data in FINMA_AGGREGATES.items():
            assert required.issubset(set(data.keys())), f"{key} missing fields"

    def test_percentiles_are_ordered(self):
        """p25 <= median <= p75 for all metrics (absolute values for NII)."""
        for key, data in FINMA_AGGREGATES.items():
            # NII sensitivity is negative, so ordering is reversed
            if "nii" in key:
                assert data["p75"] <= data["median"] <= data["p25"]
            else:
                assert data["p25"] <= data["median"] <= data["p75"]


class TestComputePeerComparison:
    """Tests for compute_peer_comparison()."""

    def test_empty_metrics_returns_no_data(self):
        result = compute_peer_comparison({})
        assert result["has_data"] is False

    def test_single_metric_at_median(self):
        """Bank value exactly at median should be ~50th percentile."""
        bank = {"delta_eve_pct_tier1": 6.8}  # median value
        result = compute_peer_comparison(bank)

        assert result["has_data"] is True
        assert len(result["comparisons"]) == 1
        comp = result["comparisons"][0]
        assert comp["percentile"] == 50
        assert comp["vs_median"] == 0.0
        assert comp["assessment"] == "Above median"

    def test_below_p25(self):
        """Bank value well below p25 should yield low percentile and positive assessment."""
        bank = {"delta_eve_pct_tier1": 1.0}
        result = compute_peer_comparison(bank)
        comp = result["comparisons"][0]
        assert comp["percentile"] < 25
        assert comp["severity"] == "positive"

    def test_above_p75(self):
        """Bank value above p75 should yield high percentile and negative assessment."""
        bank = {"delta_eve_pct_tier1": 15.0}
        result = compute_peer_comparison(bank)
        comp = result["comparisons"][0]
        assert comp["percentile"] > 75
        assert comp["assessment"] == "High outlier"
        assert comp["severity"] == "negative"

    def test_between_p25_and_median(self):
        """Value between p25 and median: 25-50th percentile."""
        bank = {"delta_eve_pct_tier1": 5.0}  # between 3.2 and 6.8
        result = compute_peer_comparison(bank)
        comp = result["comparisons"][0]
        assert 25 <= comp["percentile"] <= 50
        assert comp["assessment"] == "Below median"

    def test_multiple_metrics(self):
        """Passing multiple metrics returns one comparison per known metric."""
        bank = {
            "delta_eve_pct_tier1": 6.8,
            "nii_sensitivity_pct": -4.5,
            "avg_duration_years": 3.2,
            "nmd_share_pct": 38,
        }
        result = compute_peer_comparison(bank)
        assert result["has_data"] is True
        assert len(result["comparisons"]) == 4

    def test_unknown_metric_ignored(self):
        """Metrics not in FINMA_AGGREGATES are silently skipped."""
        bank = {"unknown_metric": 42.0, "delta_eve_pct_tier1": 6.8}
        result = compute_peer_comparison(bank)
        assert len(result["comparisons"]) == 1

    def test_unit_extraction(self):
        """Percent and year units are extracted from labels."""
        bank = {
            "delta_eve_pct_tier1": 6.8,
            "avg_duration_years": 3.2,
        }
        result = compute_peer_comparison(bank)
        units = {c["metric"]: c["unit"] for c in result["comparisons"]}
        assert units["ΔEVE / Tier 1 (%)"] == "%"
        assert units["Average Duration (years)"] == "Y"

    def test_custom_aggregates(self):
        """Custom aggregates dict overrides FINMA defaults."""
        custom = {
            "custom_metric": {
                "p25": 10,
                "median": 20,
                "p75": 30,
                "mean": 20,
                "label": "Custom (%)",
            }
        }
        bank = {"custom_metric": 20.0}
        result = compute_peer_comparison(bank, aggregates=custom)
        assert result["has_data"] is True
        assert result["comparisons"][0]["percentile"] == 50

    def test_vs_median_calculation(self):
        """vs_median is bank_value minus median."""
        bank = {"delta_eve_pct_tier1": 10.0}
        result = compute_peer_comparison(bank)
        comp = result["comparisons"][0]
        assert comp["vs_median"] == round(10.0 - 6.8, 2)
