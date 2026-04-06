"""Tests for Phase 6: Integration & workflow modules."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cockpit.integrations.notion_export import build_notion_blocks, build_notion_page_properties
from cockpit.integrations.peer_benchmark import compute_peer_comparison, FINMA_AGGREGATES
from cockpit.export.excel_export import export_dashboard_to_excel


# ============================================================================
# I1: Notion Export
# ============================================================================

class TestNotionExport:
    @pytest.fixture
    def decision_pack(self):
        return {
            "has_data": True,
            "executive_summary": [
                {"text": "NII sensitivity: -5,000 — ACTION REQUIRED", "severity": "critical"},
                {"text": "Liquidity: Net 30d positive — Monitor closely", "severity": "warning"},
            ],
            "decisions": [
                {"topic": "NII Sensitivity", "description": "Reduce duration", "priority": "high"},
                {"topic": "Liquidity", "description": "Arrange contingent funding", "priority": "critical"},
            ],
            "n_critical": 1,
            "n_high": 1,
            "n_medium": 0,
        }

    def test_blocks_structure(self, decision_pack):
        blocks = build_notion_blocks(decision_pack, "2026-04-05")
        assert len(blocks) > 0
        # First block is heading
        assert blocks[0]["type"] == "heading_1"
        # Should have exec summary bullets and decision bullets
        bullet_blocks = [b for b in blocks if b["type"] == "bulleted_list_item"]
        assert len(bullet_blocks) == 4  # 2 exec + 2 decisions

    def test_properties(self, decision_pack):
        props = build_notion_page_properties("2026-04-05", decision_pack)
        assert "Name" in props
        assert props["Date"]["date"]["start"] == "2026-04-05"
        assert props["Priority"]["select"]["name"] == "Critical"

    def test_empty_pack(self):
        blocks = build_notion_blocks({"executive_summary": [], "decisions": [], "n_critical": 0, "n_high": 0, "n_medium": 0}, "2026-04-05")
        # Still has heading + divider + counts
        assert len(blocks) >= 2


# ============================================================================
# I2: Peer Benchmark
# ============================================================================

class TestPeerBenchmark:
    def test_basic_comparison(self):
        result = compute_peer_comparison({
            "delta_eve_pct_tier1": 7.0,
            "nii_sensitivity_pct": -5.0,
        })
        assert result["has_data"]
        assert len(result["comparisons"]) == 2

    def test_below_median(self):
        result = compute_peer_comparison({"delta_eve_pct_tier1": 3.0})
        comp = result["comparisons"][0]
        assert comp["percentile"] < 50
        assert comp["vs_median"] < 0

    def test_above_p75(self):
        result = compute_peer_comparison({"delta_eve_pct_tier1": 15.0})
        comp = result["comparisons"][0]
        assert comp["percentile"] > 75

    def test_empty_metrics(self):
        assert not compute_peer_comparison({})["has_data"]

    def test_finma_aggregates_loaded(self):
        assert "delta_eve_pct_tier1" in FINMA_AGGREGATES
        assert "median" in FINMA_AGGREGATES["delta_eve_pct_tier1"]


# ============================================================================
# I4: Excel Export
# ============================================================================

class TestExcelExport:
    def test_basic_export(self, tmp_path):
        data = {
            "summary": {"kpis": {"shock_0": {"total": 100000, "realized": 60000, "forecast": 40000}}},
            "sensitivity": {"rows": [{"currency": "CHF", "shock_0": 100, "shock_50": 95}]},
            "eve": {"has_data": False},
            "pnl_alerts": {"alerts": []},
            "limits": {"has_data": False},
            "ftp": {"has_data": False},
        }
        out = tmp_path / "test.xlsx"
        result = export_dashboard_to_excel(data, out, "2026-04-05")
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

    def test_with_alerts(self, tmp_path):
        data = {
            "summary": {"kpis": {}},
            "sensitivity": {"rows": []},
            "eve": {"has_data": False},
            "pnl_alerts": {"alerts": [{"severity": "high", "metric": "Test", "message": "Alert"}]},
            "limits": {"has_data": False},
            "ftp": {"has_data": False},
        }
        result = export_dashboard_to_excel(data, tmp_path / "alerts.xlsx")
        assert result is not None
        # Verify alerts sheet exists
        xl = pd.ExcelFile(result)
        assert "Alerts" in xl.sheet_names

    def test_empty_data(self, tmp_path):
        result = export_dashboard_to_excel({}, tmp_path / "empty.xlsx")
        assert result is not None
        # Should at least have Metadata sheet
        xl = pd.ExcelFile(result)
        assert "Metadata" in xl.sheet_names
