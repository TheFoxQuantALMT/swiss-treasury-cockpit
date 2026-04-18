"""Tests for bank-native (K+EUR Daily PnL) parsers using the 30-deal fixture."""
from pathlib import Path

import pandas as pd
import pytest

from cockpit.data.parsers import (
    BankNativeInputs,
    discover_bank_native_input,
    parse_bank_native_deals,
    parse_bank_native_schedule,
    parse_bank_native_wirp,
    _month_columns,
)
from pnl_engine.config import (
    CATEGORY2_FVH_ALL,
    SUPPORTED_CURRENCIES,
    VALID_CATEGORY2,
    VALID_DIRECTIONS,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "bank_native"


@pytest.fixture(scope="module")
def inputs() -> BankNativeInputs:
    return discover_bank_native_input(FIXTURES)


# ---------------------------------------------------------------------------
# Folder discovery
# ---------------------------------------------------------------------------

class TestDiscover:
    def test_position_date(self, inputs):
        assert inputs.position_date == pd.Timestamp("2026-04-14")

    def test_variant(self, inputs):
        assert inputs.variant == "00"

    def test_files_resolved(self, inputs):
        assert inputs.pnl_workbook.exists()
        assert inputs.wirp.exists()
        assert inputs.rate_schedule.exists()

    def test_explicit_date(self):
        out = discover_bank_native_input(FIXTURES, position_date=pd.Timestamp("2026-04-14"))
        assert out.position_date == pd.Timestamp("2026-04-14")

    def test_missing_date_raises(self):
        with pytest.raises(FileNotFoundError):
            discover_bank_native_input(FIXTURES, position_date=pd.Timestamp("2099-01-01"))

    def test_missing_root_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            discover_bank_native_input(tmp_path / "nope")


# ---------------------------------------------------------------------------
# Daily P&L workbook
# ---------------------------------------------------------------------------

class TestParseDeals:
    @pytest.fixture(scope="class")
    def deals(self, inputs):
        return parse_bank_native_deals(inputs.pnl_workbook)

    def test_row_count(self, deals):
        assert len(deals) == 30  # 18 Book1 + 12 Book2

    def test_book_split(self, deals):
        counts = deals["IAS Book"].value_counts().to_dict()
        assert counts == {"BOOK1": 18, "BOOK2": 12}

    def test_canonical_columns_present(self, deals):
        for col in [
            "Dealid", "Product", "Currency", "Direction", "IAS Book",
            "Amount", "Clientrate", "Maturitydate", "Périmètre TOTAL",
            # Bank-native additions
            "Category2", "FxRate",
        ]:
            assert col in deals.columns, f"missing column {col}"

    def test_dealid_string(self, deals):
        assert pd.api.types.is_string_dtype(deals["Dealid"])
        assert deals["Dealid"].notna().all()
        assert (deals["Dealid"].str.len() > 0).all()

    def test_directions_valid(self, deals):
        assert deals["Direction"].isin(VALID_DIRECTIONS).all()

    def test_currencies_valid(self, deals):
        assert deals["Currency"].isin(SUPPORTED_CURRENCIES).all()

    def test_category2_valid(self, deals):
        assert deals["Category2"].isin(VALID_CATEGORY2).all()

    def test_category2_book_partition(self, deals):
        # IRS_FVH / IRS_FVO appear only in BOOK2; OPP_CASH / OPR_nFVH only in BOOK1
        b1_only = {"OPP_CASH", "OPP_Bond_nASW", "OPR_nFVH", "Other"}
        b2_only = {"IRS_FVH", "IRS_FVO"}
        b1 = set(deals.loc[deals["IAS Book"] == "BOOK1", "Category2"].unique())
        b2 = set(deals.loc[deals["IAS Book"] == "BOOK2", "Category2"].unique())
        assert b2_only.isdisjoint(b1)
        assert b1_only.isdisjoint(b2)

    def test_fvh_all_union_present(self, deals):
        # The Synthesis "FVH All" line is the union of these three
        present = set(deals["Category2"].unique())
        assert CATEGORY2_FVH_ALL.issubset(present)

    def test_rates_decimal(self, deals):
        # FxRate ≈ 1, others ≤ 50%
        for col in ["Clientrate", "EqOisRate", "YTM", "CocRate", "Spread"]:
            if col in deals.columns:
                assert (deals[col].abs() <= 0.50).all(), f"{col} > 50% — likely percent not decimal"

    def test_fxrate_reasonable(self, deals):
        # CHF rows must be exactly 1.0; others within sensible band
        chf = deals[deals["Currency"] == "CHF"]
        assert (chf["FxRate"] == 1.0).all()
        non_chf = deals[deals["Currency"] != "CHF"]
        assert ((non_chf["FxRate"] > 0.5) & (non_chf["FxRate"] < 2.0)).all()

    def test_signed_nominals(self, deals):
        # Assets (L/B/S) negative; Liabilities (D) positive
        from pnl_engine.config import ASSET_DIRECTIONS, LIABILITY_DIRECTIONS
        assets = deals[deals["Direction"].isin(ASSET_DIRECTIONS)]
        liabs = deals[deals["Direction"].isin(LIABILITY_DIRECTIONS)]
        assert (assets["Amount"] <= 0).all(), "asset deals should have negative nominals"
        assert (liabs["Amount"] >= 0).all(), "liability deals should have positive nominals"

    def test_maturity_parsed(self, deals):
        assert pd.api.types.is_datetime64_any_dtype(deals["Maturitydate"])
        assert deals["Maturitydate"].notna().all()

    def test_pnl_realized_present(self, deals):
        # Realized PnL column exists and at least some rows are non-zero
        assert "PnL_Realized" in deals.columns
        assert deals["PnL_Realized"].abs().sum() > 0

    def test_floating_index_known(self, deals):
        from pnl_engine.config import FLOAT_NAME_TO_WASP
        floats = deals[deals["Floating Rates Short Name"].astype(str).ne("")]
        if len(floats) > 0:
            assert floats["Floating Rates Short Name"].isin(FLOAT_NAME_TO_WASP).all()

    def test_current_fixing_rate_for_floaters(self, deals):
        # Non-floating deals → NaN; floating → finite
        is_float = deals["Floating Rates Short Name"].astype(str).ne("")
        fixed_cfr = deals.loc[~is_float, "current_fixing_rate"]
        float_cfr = deals.loc[is_float, "current_fixing_rate"]
        assert fixed_cfr.isna().all()
        assert float_cfr.notna().all()

    def test_position_date_filter(self, inputs):
        out = parse_bank_native_deals(inputs.pnl_workbook, date_run=pd.Timestamp("2026-04-14"))
        assert len(out) == 30
        # Filter to a date with no rows → both sheets empty (concat may still succeed)
        out_empty = parse_bank_native_deals(inputs.pnl_workbook, date_run=pd.Timestamp("2099-01-01"))
        assert len(out_empty) == 0


# ---------------------------------------------------------------------------
# WIRP
# ---------------------------------------------------------------------------

class TestParseWirp:
    @pytest.fixture(scope="class")
    def wirp(self, inputs):
        return parse_bank_native_wirp(inputs.wirp)

    def test_indices_mapped_to_wasp(self, wirp):
        # SARON→CHFSON, ESTR→EUREST, SOFR→USSOFR, SONIA→GBPOIS
        assert set(wirp["Indice"].unique()) == {"CHFSON", "EUREST", "USSOFR", "GBPOIS"}

    def test_meeting_parsed(self, wirp):
        assert pd.api.types.is_datetime64_any_dtype(wirp["Meeting"])
        assert wirp["Meeting"].notna().all()

    def test_rates_decimal(self, wirp):
        assert (wirp["Rate"].abs() <= 0.20).all()

    def test_sorted(self, wirp):
        # Sorted by (Indice, Meeting)
        sorted_by = wirp.sort_values(["Indice", "Meeting"]).reset_index(drop=True)
        pd.testing.assert_frame_equal(wirp, sorted_by)


# ---------------------------------------------------------------------------
# Rate schedule (wide monthly)
# ---------------------------------------------------------------------------

class TestParseSchedule:
    @pytest.fixture(scope="class")
    def schedule(self, inputs):
        return parse_bank_native_schedule(inputs.rate_schedule)

    def test_row_count(self, schedule):
        assert len(schedule) == 30  # all 30 deals projected

    def test_dealid_string(self, schedule):
        assert pd.api.types.is_string_dtype(schedule["Dealid"])

    def test_currency_supported(self, schedule):
        assert schedule["Currency"].isin(SUPPORTED_CURRENCIES).all()

    def test_direction_derived(self, schedule):
        assert "Direction" in schedule.columns
        # S maps to L (asset, no bond keyword), so only B/L/D survive
        assert schedule["Direction"].isin({"B", "L", "D"}).all()

    def test_monthly_columns_60(self, schedule):
        months = _month_columns(schedule)
        assert len(months) == 60  # 5-year horizon

    def test_monthly_columns_format(self, schedule):
        import re
        for col in _month_columns(schedule):
            assert re.match(r"^\d{4}/\d{2}$", col)
