"""Tests for the bank-native Synthesis exporter (Phase 4)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cockpit.export.synthesis import (
    FVH_ALL_LABEL,
    SYNTHESIS_SHEET_NAME,
    build_synthesis,
    export_synthesis_to_excel,
)


def _build(pnl, deals, shock="0"):
    return build_synthesis(pnl, deals, shock=shock)


def _make_pnl_by_deal(rows: list[tuple[str, str, float]], shock: str = "0") -> pd.DataFrame:
    """rows: list of (Dealid, 'YYYY-MM', PnL)."""
    return pd.DataFrame(
        [
            {"Dealid": d, "Month": pd.Period(m, freq="M"), "PnL": v, "Shock": shock}
            for d, m, v in rows
        ]
    )


def _make_deals(mapping: dict[str, tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Dealid": d, "IAS Book": b, "Category2": c} for d, (b, c) in mapping.items()]
    )


class TestBuildSynthesis:
    def test_empty_returns_empty_frame(self):
        out = _build(pd.DataFrame(), _make_deals({}))
        assert out.empty

    def test_shape_has_book_category_plus_months(self):
        pnl = _make_pnl_by_deal([("D1", "2026-04", 100.0), ("D1", "2026-05", 50.0)])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        assert list(out.columns[:2]) == ["IAS Book", "Category2"]
        assert "2026/04" in out.columns
        assert "2026/05" in out.columns

    def test_aggregates_across_deals(self):
        pnl = _make_pnl_by_deal([
            ("D1", "2026-04", 100.0),
            ("D2", "2026-04", 50.0),
            ("D3", "2026-04", 7.0),
        ])
        deals = _make_deals({
            "D1": ("BOOK1", "OPP_CASH"),
            "D2": ("BOOK1", "OPP_CASH"),
            "D3": ("BOOK1", "Other"),
        })
        out = _build(pnl, deals)
        opp_cash = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")]
        other = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "Other")]
        assert opp_cash["2026/04"].iloc[0] == 150.0
        assert other["2026/04"].iloc[0] == 7.0

    def test_filters_by_shock(self):
        pnl = pd.concat([
            _make_pnl_by_deal([("D1", "2026-04", 100.0)], shock="0"),
            _make_pnl_by_deal([("D1", "2026-04", 9999.0)], shock="50"),
        ], ignore_index=True)
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = build_synthesis(pnl, deals, shock="0")
        assert out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")]["2026/04"].iloc[0] == 100.0

    def test_fvh_all_is_union_across_books(self):
        # Book1 OPP_Bond_ASW + Book1 OPR_FVH + Book2 OPP_Bond_ASW + Book2 OPR_FVH + Book2 IRS_FVH
        pnl = _make_pnl_by_deal([
            ("A1", "2026-04", 10.0),
            ("A2", "2026-04", 20.0),
            ("A3", "2026-04", 30.0),
            ("A4", "2026-04", 40.0),
            ("A5", "2026-04", 50.0),
            # A non-FVH bucket that must NOT contribute
            ("N1", "2026-04", 999.0),
        ])
        deals = _make_deals({
            "A1": ("BOOK1", "OPP_Bond_ASW"),
            "A2": ("BOOK1", "OPR_FVH"),
            "A3": ("BOOK2", "OPP_Bond_ASW"),
            "A4": ("BOOK2", "OPR_FVH"),
            "A5": ("BOOK2", "IRS_FVH"),
            "N1": ("BOOK1", "OPP_CASH"),
        })
        out = _build(pnl, deals)
        fvh = out[out["Category2"] == FVH_ALL_LABEL]
        assert len(fvh) == 1
        assert fvh["2026/04"].iloc[0] == 10 + 20 + 30 + 40 + 50

    def test_fvh_row_is_last(self):
        pnl = _make_pnl_by_deal([("D1", "2026-04", 1.0)])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        assert out["Category2"].iloc[-1] == FVH_ALL_LABEL

    def test_missing_buckets_filled_with_zero(self):
        pnl = _make_pnl_by_deal([("D1", "2026-04", 100.0)])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        # OPR_nFVH not present in input → row of zeros
        row = out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPR_nFVH")]
        assert len(row) == 1
        assert row["2026/04"].iloc[0] == 0.0

    def test_orphan_deals_dropped(self):
        pnl = _make_pnl_by_deal([
            ("D1", "2026-04", 100.0),
            ("UNKNOWN", "2026-04", 999.0),
        ])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        assert out[(out["IAS Book"] == "BOOK1") & (out["Category2"] == "OPP_CASH")]["2026/04"].iloc[0] == 100.0

    def test_month_labels_sorted(self):
        pnl = _make_pnl_by_deal([
            ("D1", "2026-06", 3.0),
            ("D1", "2026-04", 1.0),
            ("D1", "2026-05", 2.0),
        ])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        month_cols = [c for c in out.columns if c not in {"IAS Book", "Category2"}]
        assert month_cols == sorted(month_cols)

    def test_requires_taxonomy_columns(self):
        pnl = _make_pnl_by_deal([("D1", "2026-04", 1.0)])
        with pytest.raises(ValueError):
            build_synthesis(pnl, pd.DataFrame({"Dealid": ["D1"]}), shock="0")

    def test_requires_pnl_columns(self):
        with pytest.raises(ValueError):
            build_synthesis(
                pd.DataFrame({"Dealid": ["D1"]}),
                _make_deals({"D1": ("BOOK1", "OPP_CASH")}),
                shock="0",
            )


class TestExport:
    def test_roundtrip(self, tmp_path: Path):
        pnl = _make_pnl_by_deal([("D1", "2026-04", 42.0)])
        deals = _make_deals({"D1": ("BOOK1", "OPP_CASH")})
        out = _build(pnl, deals)
        path = tmp_path / "2026_04_Daily_Forecast.xlsx"
        export_synthesis_to_excel(out, path)
        assert path.exists()
        loaded = pd.read_excel(path, sheet_name=SYNTHESIS_SHEET_NAME)
        assert (loaded["Category2"] == FVH_ALL_LABEL).any()
