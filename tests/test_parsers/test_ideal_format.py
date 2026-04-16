"""Tests for ideal-format parsers using mock input files."""
from pathlib import Path

import pandas as pd
import pytest

from cockpit.data.parsers import (
    parse_deals,
    parse_echeancier,
    parse_mtd,
    parse_reference_table,
    parse_schedule,
    parse_wirp,
    parse_wirp_ideal,
    _month_columns,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ideal_input"


# ---------------------------------------------------------------------------
# deals.xlsx
# ---------------------------------------------------------------------------

class TestParseDeals:
    @pytest.fixture()
    def deals(self):
        return parse_deals(FIXTURES / "deals.xlsx")

    def test_row_count(self, deals):
        assert len(deals) == 15  # 12 BOOK1 + 3 BOOK2

    def test_columns_renamed(self, deals):
        assert "Dealid" in deals.columns
        assert "Product" in deals.columns
        assert "Currency" in deals.columns
        assert "Direction" in deals.columns
        assert "IAS Book" in deals.columns
        assert "Clientrate" in deals.columns
        assert "Périmètre TOTAL" in deals.columns

    def test_deal_id_numeric(self, deals):
        assert deals["Dealid"].dtype in ("int64", "float64")
        assert deals["Dealid"].notna().all()

    def test_products_valid(self, deals):
        valid = {"IAM/LD", "BND", "FXS", "IRS", "IRS-MTM", "HCD"}
        assert deals["Product"].isin(valid).all()

    def test_currencies_valid(self, deals):
        valid = {"CHF", "EUR", "USD", "GBP"}
        assert deals["Currency"].isin(valid).all()

    def test_directions_valid(self, deals):
        assert deals["Direction"].isin({"B", "L", "D", "S"}).all()

    def test_books_valid(self, deals):
        assert deals["IAS Book"].isin({"BOOK1", "BOOK2"}).all()

    def test_rates_decimal(self, deals):
        for col in ["Clientrate", "EqOisRate", "YTM", "CocRate", "Spread"]:
            assert (deals[col].abs() <= 0.50).all(), f"{col} has values > 50%"

    def test_maturity_parsed(self, deals):
        assert pd.api.types.is_datetime64_any_dtype(deals["Maturitydate"])
        assert deals["Maturitydate"].notna().all()

    def test_perimeters_valid(self, deals):
        assert deals["Périmètre TOTAL"].isin({"CC", "WM", "CIB"}).all()

    def test_book1_count(self, deals):
        assert (deals["IAS Book"] == "BOOK1").sum() == 12

    def test_book2_count(self, deals):
        assert (deals["IAS Book"] == "BOOK2").sum() == 3

    def test_book2_has_irs_fields(self, deals):
        book2 = deals[deals["IAS Book"] == "BOOK2"]
        assert book2["pay_receive"].notna().all()
        assert book2["notional"].notna().all()
        assert book2["last_fixing_date"].notna().all()
        assert book2["next_fixing_date"].notna().all()

    def test_fixing_dates_order(self, deals):
        """last_fixing_date should be before next_fixing_date."""
        book2 = deals[deals["IAS Book"] == "BOOK2"]
        last_fix = pd.to_datetime(book2["last_fixing_date"])
        next_fix = pd.to_datetime(book2["next_fixing_date"])
        assert (last_fix < next_fix).all()

    def test_strategy_deal_present(self, deals):
        strat = deals[deals["Strategy IAS"].notna()]
        assert len(strat) == 6  # 3 hedged items + 3 IRS instruments
        strategies = strat["Strategy IAS"].unique()
        assert len(strategies) == 3  # STRAT_CHF_001, STRAT_CHF_002, STRAT_EUR_001

    def test_floating_deal(self, deals):
        floating = deals[deals["Floating Rates Short Name"] != ""]
        assert len(floating) >= 1
        assert "SARON" in floating["Floating Rates Short Name"].values

    def test_sold_bond(self, deals):
        sold = deals[(deals["Product"] == "BND") & (deals["Direction"] == "S")]
        assert len(sold) == 1
        assert sold.iloc[0]["Currency"] == "EUR"


class TestParseMtdAutoDetect:
    """parse_mtd() should auto-detect deals.xlsx ideal format."""

    def test_auto_detects_ideal_format(self):
        result = parse_mtd(FIXTURES / "deals.xlsx")
        assert len(result) == 15
        assert "Dealid" in result.columns


# ---------------------------------------------------------------------------
# rate_schedule.xlsx
# ---------------------------------------------------------------------------

class TestParseSchedule:
    @pytest.fixture()
    def schedule(self):
        return parse_schedule(FIXTURES / "rate_schedule.xlsx")

    def test_row_count(self, schedule):
        assert len(schedule) == 12

    def test_columns_renamed(self, schedule):
        assert "Dealid" in schedule.columns
        assert "Direction" in schedule.columns
        assert "Currency" in schedule.columns

    def test_deal_id_numeric(self, schedule):
        assert schedule["Dealid"].notna().all()

    def test_directions_valid(self, schedule):
        assert schedule["Direction"].isin({"B", "L", "D", "S"}).all()

    def test_month_columns_present(self, schedule):
        months = _month_columns(schedule)
        assert len(months) == 60
        assert months[0] == "2026/04"

    def test_matured_deal_zeros(self, schedule):
        """Deal 100007 (WM, matures 2026/10) should have zeros after month 7."""
        row = schedule[schedule["Dealid"] == 100007].iloc[0]
        months = _month_columns(schedule)
        # Month index 7 = 2026/11 should be zero
        assert row[months[7]] == 0.0
        assert row[months[6]] == 15_000_000  # last month alive

    def test_nominal_signs(self, schedule):
        """Loans should have negative nominal, deposits positive."""
        loans = schedule[schedule["Direction"] == "L"]
        months = _month_columns(schedule)
        for _, row in loans.iterrows():
            nonzero = [row[m] for m in months if row[m] != 0]
            if nonzero:
                assert nonzero[0] < 0, f"Loan deal {row['Dealid']} has positive nominal"


class TestParseEcheancierAutoDetect:
    def test_auto_detects_ideal_format(self):
        result = parse_echeancier(FIXTURES / "rate_schedule.xlsx")
        assert len(result) == 12
        assert "Dealid" in result.columns


# ---------------------------------------------------------------------------
# wirp.xlsx
# ---------------------------------------------------------------------------

class TestParseWirpIdeal:
    @pytest.fixture()
    def wirp(self):
        return parse_wirp_ideal(FIXTURES / "wirp.xlsx")

    def test_row_count(self, wirp):
        assert len(wirp) == 19

    def test_columns(self, wirp):
        assert "Indice" in wirp.columns
        assert "Meeting" in wirp.columns
        assert "Rate" in wirp.columns
        assert "Hike / Cut" in wirp.columns

    def test_indices_valid(self, wirp):
        assert wirp["Indice"].isin({"CHFSON", "EUREST", "USSOFR", "GBPOIS"}).all()

    def test_meeting_dates_parsed(self, wirp):
        assert pd.api.types.is_datetime64_any_dtype(wirp["Meeting"])
        assert wirp["Meeting"].notna().all()

    def test_rates_decimal(self, wirp):
        assert (wirp["Rate"].abs() <= 0.20).all()

    def test_sorted_by_index_and_date(self, wirp):
        for idx in wirp["Indice"].unique():
            sub = wirp[wirp["Indice"] == idx]
            assert sub["Meeting"].is_monotonic_increasing

    def test_four_indices(self, wirp):
        assert wirp["Indice"].nunique() == 4


class TestParseWirpAutoDetect:
    def test_auto_detects_ideal_format(self):
        result = parse_wirp(FIXTURES / "wirp.xlsx")
        assert len(result) == 19
        assert "Indice" in result.columns


# ---------------------------------------------------------------------------
# reference_table.xlsx
# ---------------------------------------------------------------------------

class TestParseReferenceTable:
    @pytest.fixture()
    def ref(self):
        return parse_reference_table(FIXTURES / "reference_table.xlsx")

    def test_row_count(self, ref):
        assert len(ref) == 8

    def test_columns(self, ref):
        assert list(ref.columns) == ["counterparty", "rating", "hqla_level", "country"]

    def test_ratings_present(self, ref):
        assert ref["rating"].notna().all()

    def test_hqla_levels_valid(self, ref):
        assert ref["hqla_level"].isin({"L1", "L2A", "L2B", "Non-HQLA"}).all()


# ---------------------------------------------------------------------------
# Cross-file consistency
# ---------------------------------------------------------------------------

class TestCrossFileConsistency:
    """Validate that deals and schedule files are joinable."""

    @pytest.fixture()
    def deals(self):
        return parse_deals(FIXTURES / "deals.xlsx")

    @pytest.fixture()
    def schedule(self):
        return parse_schedule(FIXTURES / "rate_schedule.xlsx")

    def test_book1_deals_have_schedule(self, deals, schedule):
        """Every BOOK1 deal should have a matching schedule row."""
        book1 = deals[deals["IAS Book"] == "BOOK1"]
        for _, deal in book1.iterrows():
            match = schedule[
                (schedule["Dealid"] == deal["Dealid"])
                & (schedule["Direction"] == deal["Direction"])
                & (schedule["Currency"] == deal["Currency"])
            ]
            assert len(match) >= 1, (
                f"No schedule row for deal {deal['Dealid']} "
                f"({deal['Direction']}, {deal['Currency']})"
            )

    def test_schedule_deals_exist_in_deals(self, deals, schedule):
        """Every schedule deal_id should exist in deals."""
        deal_ids = set(deals["Dealid"].values)
        for did in schedule["Dealid"].unique():
            assert did in deal_ids, f"Schedule deal {did} not in deals file"
