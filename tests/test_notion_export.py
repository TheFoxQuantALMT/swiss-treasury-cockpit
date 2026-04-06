"""Tests for cockpit.integrations.notion_export module."""
from __future__ import annotations

import pytest

from cockpit.integrations.notion_export import (
    build_notion_blocks,
    build_notion_page_properties,
)


@pytest.fixture
def sample_decision_pack():
    return {
        "executive_summary": [
            {"text": "CHF duration exceeds limit", "severity": "critical"},
            {"text": "EUR NII sensitivity within bounds", "severity": "info"},
        ],
        "decisions": [
            {"topic": "CHF Duration", "description": "Reduce by 0.5Y", "priority": "critical"},
            {"topic": "EUR Hedge", "description": "Extend hedge tenor", "priority": "medium"},
        ],
        "n_critical": 1,
        "n_high": 0,
        "n_medium": 1,
    }


@pytest.fixture
def empty_decision_pack():
    return {
        "executive_summary": [],
        "decisions": [],
        "n_critical": 0,
        "n_high": 0,
        "n_medium": 0,
    }


class TestBuildNotionBlocks:
    """Tests for build_notion_blocks()."""

    def test_returns_list(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        assert isinstance(blocks, list)
        assert len(blocks) > 0

    def test_first_block_is_heading(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        assert blocks[0]["type"] == "heading_1"
        assert "ALCO Decision Pack" in blocks[0]["heading_1"]["rich_text"][0]["text"]["content"]
        assert "2026-04-04" in blocks[0]["heading_1"]["rich_text"][0]["text"]["content"]

    def test_executive_summary_items(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        bullet_items = [b for b in blocks if b["type"] == "bulleted_list_item"]
        # 2 executive summary + 2 decisions = 4 bullets
        assert len(bullet_items) == 4

    def test_critical_gets_red_emoji(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        bullet_items = [b for b in blocks if b["type"] == "bulleted_list_item"]
        first_text = bullet_items[0]["bulleted_list_item"]["rich_text"][0]["text"]["content"]
        assert first_text.startswith("\U0001f534")  # red circle

    def test_has_divider(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        dividers = [b for b in blocks if b["type"] == "divider"]
        assert len(dividers) == 1

    def test_counts_paragraph(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        paragraphs = [b for b in blocks if b["type"] == "paragraph"]
        assert len(paragraphs) == 1
        text = paragraphs[0]["paragraph"]["rich_text"][0]["text"]["content"]
        assert "Critical: 1" in text
        assert "Medium: 1" in text

    def test_empty_pack_still_has_heading_and_counts(self, empty_decision_pack):
        blocks = build_notion_blocks(empty_decision_pack, "2026-04-04")
        types = [b["type"] for b in blocks]
        assert "heading_1" in types
        assert "divider" in types
        assert "paragraph" in types
        # No bullets for empty lists
        assert "bulleted_list_item" not in types

    def test_all_blocks_have_object_field(self, sample_decision_pack):
        blocks = build_notion_blocks(sample_decision_pack, "2026-04-04")
        for block in blocks:
            assert block.get("object") == "block"


class TestBuildNotionPageProperties:
    """Tests for build_notion_page_properties()."""

    def test_title_contains_date(self):
        props = build_notion_page_properties("2026-04-04", {"n_critical": 0, "n_high": 0})
        title_text = props["Name"]["title"][0]["text"]["content"]
        assert "2026-04-04" in title_text

    def test_date_property(self):
        props = build_notion_page_properties("2026-04-04", {"n_critical": 0, "n_high": 0})
        assert props["Date"]["date"]["start"] == "2026-04-04"

    def test_critical_sets_open_status(self):
        props = build_notion_page_properties("2026-04-04", {"n_critical": 2, "n_high": 0})
        assert props["Status"]["select"]["name"] == "Open"
        assert props["Priority"]["select"]["name"] == "Critical"

    def test_no_critical_high_sets_review(self):
        props = build_notion_page_properties("2026-04-04", {"n_critical": 0, "n_high": 1})
        assert props["Status"]["select"]["name"] == "Review"
        assert props["Priority"]["select"]["name"] == "High"

    def test_no_critical_no_high_normal(self):
        props = build_notion_page_properties("2026-04-04", {"n_critical": 0, "n_high": 0})
        assert props["Priority"]["select"]["name"] == "Normal"
