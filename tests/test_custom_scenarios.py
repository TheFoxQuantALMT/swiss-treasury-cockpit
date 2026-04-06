"""Tests for cockpit.data.parsers.custom_scenarios module."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cockpit.data.parsers.custom_scenarios import (
    custom_scenarios_to_bcbs_format,
    parse_custom_scenarios,
)


@pytest.fixture
def sample_df():
    """Sample custom scenarios DataFrame."""
    return pd.DataFrame({
        "scenario": ["SNB_reversal", "SNB_reversal", "SNB_reversal", "Hike_100", "Hike_100"],
        "tenor": [0.25, 1.0, 5.0, 0.25, 1.0],
        "CHF": [-50, -50, -25, 100, 100],
        "EUR": [-25, -25, -10, 50, 50],
        "USD": [0, 0, 0, 0, 0],
    })


@pytest.fixture
def sample_excel(tmp_path, sample_df):
    """Write sample_df to an Excel file and return the path."""
    path = tmp_path / "custom_scenarios.xlsx"
    sample_df.to_excel(path, index=False, engine="openpyxl")
    return path


class TestParseCustomScenarios:
    """Tests for parse_custom_scenarios()."""

    def test_parses_valid_file(self, sample_excel):
        df = parse_custom_scenarios(sample_excel)
        assert df is not None
        assert len(df) == 5
        assert "scenario" in df.columns
        assert "tenor" in df.columns

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = parse_custom_scenarios(tmp_path / "does_not_exist.xlsx")
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        path = tmp_path / "empty.xlsx"
        pd.DataFrame().to_excel(path, index=False, engine="openpyxl")
        result = parse_custom_scenarios(path)
        assert result is None

    def test_missing_required_columns_returns_none(self, tmp_path):
        path = tmp_path / "bad.xlsx"
        pd.DataFrame({"foo": [1], "bar": [2]}).to_excel(path, index=False, engine="openpyxl")
        result = parse_custom_scenarios(path)
        assert result is None

    def test_tenor_is_numeric(self, sample_excel):
        df = parse_custom_scenarios(sample_excel)
        assert pd.api.types.is_numeric_dtype(df["tenor"])

    def test_currency_columns_numeric(self, sample_excel):
        df = parse_custom_scenarios(sample_excel)
        for col in ("CHF", "EUR", "USD"):
            assert pd.api.types.is_numeric_dtype(df[col])

    def test_accepts_string_path(self, sample_excel):
        df = parse_custom_scenarios(str(sample_excel))
        assert df is not None

    def test_column_name_normalization(self, tmp_path):
        """Columns with leading/trailing whitespace are normalized."""
        path = tmp_path / "whitespace.xlsx"
        df = pd.DataFrame({
            " Scenario ": ["test"],
            " Tenor ": [1.0],
            "CHF": [50],
        })
        df.to_excel(path, index=False, engine="openpyxl")
        result = parse_custom_scenarios(path)
        assert result is not None
        assert "scenario" in result.columns

    def test_nan_currency_values_filled_with_zero(self, tmp_path):
        """NaN in currency columns are filled with 0."""
        path = tmp_path / "nan.xlsx"
        df = pd.DataFrame({
            "scenario": ["test"],
            "tenor": [1.0],
            "CHF": [None],
        })
        df.to_excel(path, index=False, engine="openpyxl")
        result = parse_custom_scenarios(path)
        assert result is not None
        assert result.iloc[0]["CHF"] == 0


class TestCustomScenariosToBcbsFormat:
    """Tests for custom_scenarios_to_bcbs_format()."""

    def test_converts_to_list_of_dicts(self, sample_df):
        result = custom_scenarios_to_bcbs_format(sample_df)
        assert isinstance(result, list)
        assert len(result) == 2  # SNB_reversal and Hike_100

    def test_scenario_structure(self, sample_df):
        result = custom_scenarios_to_bcbs_format(sample_df)
        for item in result:
            assert "name" in item
            assert "shocks" in item
            assert isinstance(item["shocks"], dict)

    def test_zero_shocks_excluded(self, sample_df):
        """Currencies with all-zero shocks are not included."""
        result = custom_scenarios_to_bcbs_format(sample_df)
        snb = next(s for s in result if s["name"] == "SNB_reversal")
        assert "USD" not in snb["shocks"]  # all zeros
        assert "CHF" in snb["shocks"]
        assert "EUR" in snb["shocks"]

    def test_tenor_shock_mapping(self, sample_df):
        result = custom_scenarios_to_bcbs_format(sample_df)
        snb = next(s for s in result if s["name"] == "SNB_reversal")
        chf_shocks = snb["shocks"]["CHF"]
        assert chf_shocks[0.25] == -50
        assert chf_shocks[5.0] == -25

    def test_empty_df_returns_empty_list(self):
        assert custom_scenarios_to_bcbs_format(pd.DataFrame()) == []

    def test_none_returns_empty_list(self):
        assert custom_scenarios_to_bcbs_format(None) == []
