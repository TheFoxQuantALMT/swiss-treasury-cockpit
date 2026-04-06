"""Tests for cockpit.export.excel_export module."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cockpit.export.excel_export import export_dashboard_to_excel


@pytest.fixture
def minimal_dashboard_data():
    """Minimal dashboard_data dict with one populated section."""
    return {
        "summary": {
            "kpis": {
                "0": {"total_nii": 1_000_000, "currency": "CHF"},
                "50": {"total_nii": 950_000, "currency": "CHF"},
            }
        },
    }


@pytest.fixture
def full_dashboard_data():
    """Dashboard data with multiple sections populated."""
    return {
        "summary": {
            "kpis": {
                "0": {"total_nii": 1_000_000},
            }
        },
        "sensitivity": {
            "rows": [
                {"currency": "CHF", "shock": 0, "nii": 100},
                {"currency": "EUR", "shock": 50, "nii": 80},
            ]
        },
        "eve": {
            "has_data": True,
            "by_currency": {
                "CHF": {"eve_base": 500, "eve_up": 480},
                "EUR": {"eve_base": 300, "eve_up": 290},
            },
        },
        "pnl_alerts": {
            "alerts": [
                {"type": "threshold", "message": "CHF NII below limit"},
            ]
        },
        "limits": {
            "has_data": True,
            "limit_items": [
                {"metric": "NII", "limit": 1_000_000, "actual": 900_000},
            ],
        },
        "ftp": {
            "has_data": True,
            "by_perimeter": [
                {"perimeter": "CC", "margin": 0.5},
            ],
        },
    }


def test_export_produces_xlsx(tmp_path, minimal_dashboard_data):
    """Export creates an .xlsx file and returns its path."""
    out = tmp_path / "test.xlsx"
    result = export_dashboard_to_excel(minimal_dashboard_data, out, date_run="2026-04-04")

    assert result is not None
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_export_contains_summary_sheet(tmp_path, minimal_dashboard_data):
    """Exported workbook has a Summary sheet with the KPI data."""
    out = tmp_path / "test.xlsx"
    export_dashboard_to_excel(minimal_dashboard_data, out, date_run="2026-04-04")

    xl = pd.ExcelFile(out, engine="openpyxl")
    assert "Summary" in xl.sheet_names
    df = pd.read_excel(xl, sheet_name="Summary")
    assert "shock" in df.columns
    assert len(df) == 2


def test_export_metadata_sheet(tmp_path, minimal_dashboard_data):
    """Metadata sheet is always written with date_run."""
    out = tmp_path / "test.xlsx"
    export_dashboard_to_excel(minimal_dashboard_data, out, date_run="2026-04-04")

    df = pd.read_excel(out, sheet_name="Metadata", engine="openpyxl")
    assert df.iloc[0]["date_run"] == "2026-04-04"
    assert df.iloc[0]["export_type"] == "dashboard"


def test_export_all_sections(tmp_path, full_dashboard_data):
    """All sections produce their respective sheets."""
    out = tmp_path / "test.xlsx"
    export_dashboard_to_excel(full_dashboard_data, out, date_run="2026-04-04")

    xl = pd.ExcelFile(out, engine="openpyxl")
    for name in ("Summary", "Sensitivity", "EVE", "Alerts", "Limits", "FTP", "Metadata"):
        assert name in xl.sheet_names, f"Missing sheet: {name}"


def test_export_empty_data_returns_file(tmp_path):
    """Empty dashboard_data still produces a file (with Metadata sheet only)."""
    out = tmp_path / "empty.xlsx"
    result = export_dashboard_to_excel({}, out, date_run="2026-01-01")

    assert result is not None
    assert out.exists()
    xl = pd.ExcelFile(out, engine="openpyxl")
    assert "Metadata" in xl.sheet_names


def test_export_accepts_string_path(tmp_path, minimal_dashboard_data):
    """Function accepts str path, not just Path objects."""
    out = str(tmp_path / "str_path.xlsx")
    result = export_dashboard_to_excel(minimal_dashboard_data, out, date_run="2026-04-04")
    assert result is not None
    assert Path(out).exists()


def test_export_invalid_path_returns_none(minimal_dashboard_data):
    """Writing to an invalid directory returns None gracefully."""
    result = export_dashboard_to_excel(
        minimal_dashboard_data,
        "/nonexistent/dir/file.xlsx",
        date_run="2026-04-04",
    )
    assert result is None
