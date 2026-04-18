"""Tests for the cross-book hedge-effectiveness consolidator.

Covers:
  - Empty / missing inputs → empty frame
  - Pure ORC (no Clean Price, no Book2 IRS) → NaN dFV & dMtM, ``na`` corridor
  - Pure FVH bond + IRS → effectiveness ratio 1.0 with matching ΔFV / -ΔMtM
  - ASW mirror across BOOK1 + BOOK2 → deduped (counted once)
  - Missing prior snapshot → dFV / dMtM → NaN
  - Corridor edge flagging at 0.79 / 0.80 / 1.00 / 1.25 / 1.26
  - Multi-currency strategy → ``multi_ccy`` label overrides corridor
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pnl_engine.strategy_consolidated import (
    EFFECTIVE_HIGH,
    EFFECTIVE_LOW,
    _corridor_flag,
    compute_strategy_consolidated,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _deal(
    dealid,
    product,
    ias_book,
    strategy,
    amount,
    currency="CHF",
    clean_price=np.nan,
    category2="",
    isin="",
):
    return {
        "Dealid": dealid,
        "Product": product,
        "IAS Book": ias_book,
        "Strategy IAS": strategy,
        "Amount": amount,
        "Currency": currency,
        "Clean Price": clean_price,
        "Category2": category2,
        "ISIN": isin,
        "Direction": "L" if product in ("IAM/LD",) else ("B" if product == "BND" else "L"),
    }


def _book2_row(deal, mtm):
    return {
        "Deal": deal,
        "Dealid": deal,
        "Strategy (Agapes IAS)": None,  # overwritten per test
        "MTM": mtm,
    }


# ---------------------------------------------------------------------------
# Empty / degenerate inputs
# ---------------------------------------------------------------------------

class TestEmptyInputs:
    def test_empty_deals_returns_empty(self):
        assert compute_strategy_consolidated(pd.DataFrame()).empty

    def test_none_deals_returns_empty(self):
        assert compute_strategy_consolidated(None).empty

    def test_no_strategy_column_returns_empty(self):
        df = pd.DataFrame([{"Dealid": 1, "Product": "BND"}])
        assert compute_strategy_consolidated(df).empty

    def test_all_strategies_blank_returns_empty(self):
        df = pd.DataFrame([
            _deal(1, "BND", "BOOK1", "", 10_000_000, clean_price=100.0, isin="X1"),
            _deal(2, "BND", "BOOK1", None, 5_000_000, clean_price=100.0, isin="X2"),
        ])
        assert compute_strategy_consolidated(df).empty


# ---------------------------------------------------------------------------
# Corridor-flag pure logic
# ---------------------------------------------------------------------------

class TestCorridorFlag:
    @pytest.mark.parametrize(
        "ratio,expected",
        [
            (0.79, "under"),
            (EFFECTIVE_LOW, "ok"),
            (1.00, "ok"),
            (EFFECTIVE_HIGH, "ok"),
            (1.26, "over"),
            (float("nan"), "na"),
        ],
    )
    def test_corridor_edges(self, ratio, expected):
        assert _corridor_flag(ratio, multi_ccy=False) == expected

    def test_multi_ccy_overrides(self):
        # Even a perfect 1.0 ratio is reported as multi_ccy when relationship
        # spans more than one currency
        assert _corridor_flag(1.0, multi_ccy=True) == "multi_ccy"


# ---------------------------------------------------------------------------
# ORC — no hedge instrument, no Clean Price
# ---------------------------------------------------------------------------

class TestPureORC:
    def test_pure_orc_produces_na_corridor(self):
        deals = pd.DataFrame([
            _deal(1, "IAM/LD", "BOOK1", "STRAT_ORC_001", -50_000_000,
                  currency="CHF", category2="OPR_ORC"),
        ])
        result = compute_strategy_consolidated(deals)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["strategy_ias"] == "STRAT_ORC_001"
        assert row["hedge_type"] == "CFH"
        assert row["n_hedged"] == 1
        assert row["n_hedging"] == 0
        assert pd.isna(row["hedged_clean_fv_today"])
        assert pd.isna(row["effectiveness_ratio"])
        assert row["corridor_flag"] == "na"


# ---------------------------------------------------------------------------
# Pure FVH bond + IRS
# ---------------------------------------------------------------------------

class TestPureFVH:
    def _build(self, dcp_delta=1.0, dmtm=-100_000.0, mtm_today=-500_000.0):
        """10M bond @ 102.0 today, (102.0 - dcp_delta) prev → dFV = +1% × 10M = 100k."""
        deals_today = pd.DataFrame([
            _deal(
                10, "BND", "BOOK1", "STRAT_FVH", -10_000_000,
                currency="CHF", clean_price=102.0, category2="OPR_FVH", isin="B1",
            ),
            _deal(
                11, "IRS-MTM", "BOOK2", "STRAT_FVH", -10_000_000,
                currency="CHF", category2="IRS_FVH",
            ),
        ])
        deals_prev = deals_today.copy()
        deals_prev.loc[deals_prev["Dealid"] == 10, "Clean Price"] = 102.0 - dcp_delta

        b2_today = pd.DataFrame([{
            "Deal": 11, "Dealid": 11,
            "Strategy (Agapes IAS)": "STRAT_FVH",
            "MTM": mtm_today,
        }])
        b2_prev = pd.DataFrame([{
            "Deal": 11, "Dealid": 11,
            "Strategy (Agapes IAS)": "STRAT_FVH",
            "MTM": mtm_today - dmtm,
        }])
        return deals_today, deals_prev, b2_today, b2_prev

    def test_perfect_hedge_ratio_is_one(self):
        # dFV = +1% * 10M = 100_000 ; dMTM = -100_000 ; ratio = -(-100k)/100k = 1.0
        deals_t, deals_p, b2_t, b2_p = self._build(
            dcp_delta=1.0, dmtm=-100_000.0, mtm_today=-500_000.0,
        )
        result = compute_strategy_consolidated(deals_t, b2_t, deals_p, b2_p)
        row = result.iloc[0]

        assert row["hedge_type"] == "FVH"
        assert row["n_hedged"] == 1
        assert row["n_hedging"] == 1
        assert row["n_hedging_book2"] == 1
        assert row["hedged_clean_fv_today"] == pytest.approx(10_200_000)
        assert row["hedged_clean_dFV"] == pytest.approx(100_000)
        assert row["hedging_irs_dMtM"] == pytest.approx(-100_000)
        assert row["effectiveness_ratio"] == pytest.approx(1.0)
        assert row["corridor_flag"] == "ok"

    def test_under_hedge_ratio(self):
        # dFV=100k, dMTM=-50k → ratio=0.5 → under
        deals_t, deals_p, b2_t, b2_p = self._build(
            dcp_delta=1.0, dmtm=-50_000.0, mtm_today=-400_000.0,
        )
        result = compute_strategy_consolidated(deals_t, b2_t, deals_p, b2_p)
        row = result.iloc[0]
        assert row["effectiveness_ratio"] == pytest.approx(0.5)
        assert row["corridor_flag"] == "under"

    def test_over_hedge_ratio(self):
        # dFV=100k, dMTM=-150k → ratio=1.5 → over
        deals_t, deals_p, b2_t, b2_p = self._build(
            dcp_delta=1.0, dmtm=-150_000.0, mtm_today=-600_000.0,
        )
        result = compute_strategy_consolidated(deals_t, b2_t, deals_p, b2_p)
        row = result.iloc[0]
        assert row["effectiveness_ratio"] == pytest.approx(1.5)
        assert row["corridor_flag"] == "over"


# ---------------------------------------------------------------------------
# ASW bond mirrored across books — dedup
# ---------------------------------------------------------------------------

class TestAswDedup:
    def test_asw_bond_counted_once(self):
        """Same ISIN in BOOK1 + BOOK2 → FV counted once (BOOK2 kept)."""
        # Note: both books carry Clean Price but the position should NOT double.
        deals = pd.DataFrame([
            _deal(20, "BND", "BOOK1", "STRAT_ASW", -15_000_000,
                  currency="CHF", clean_price=103.52, category2="OPP_Bond_ASW",
                  isin="CH0001234567"),
            _deal(21, "BND", "BOOK2", "STRAT_ASW", -15_000_000,
                  currency="CHF", clean_price=103.52, category2="OPP_Bond_ASW",
                  isin="CH0001234567"),
        ])
        result = compute_strategy_consolidated(deals)
        row = result.iloc[0]
        assert row["n_hedged"] == 1, "ASW bond should be counted once, not twice"
        assert row["hedged_clean_fv_today"] == pytest.approx(15_528_000)

    def test_asw_delta_counted_once(self):
        """Bond moves from 102.52 → 103.52 → dFV = 1% × 15M = 150k (not 300k)."""
        deals_today = pd.DataFrame([
            _deal(20, "BND", "BOOK1", "STRAT_ASW", -15_000_000,
                  currency="CHF", clean_price=103.52, isin="CH0001234567"),
            _deal(21, "BND", "BOOK2", "STRAT_ASW", -15_000_000,
                  currency="CHF", clean_price=103.52, isin="CH0001234567"),
        ])
        deals_prev = deals_today.copy()
        deals_prev["Clean Price"] = 102.52
        result = compute_strategy_consolidated(deals_today, None, deals_prev, None)
        row = result.iloc[0]
        assert row["hedged_clean_dFV"] == pytest.approx(150_000)


# ---------------------------------------------------------------------------
# Missing prior snapshot
# ---------------------------------------------------------------------------

class TestMissingPrior:
    def test_no_prior_deals_delta_nan(self):
        deals = pd.DataFrame([
            _deal(30, "BND", "BOOK1", "STRAT_X", -10_000_000,
                  currency="CHF", clean_price=102.0, isin="BX"),
        ])
        result = compute_strategy_consolidated(deals, None, None, None)
        row = result.iloc[0]
        assert row["hedged_clean_fv_today"] == pytest.approx(10_200_000)
        assert pd.isna(row["hedged_clean_dFV"])
        assert pd.isna(row["effectiveness_ratio"])
        assert row["corridor_flag"] == "na"

    def test_no_prior_book2_mtm_delta_nan(self):
        deals_today = pd.DataFrame([
            _deal(30, "BND", "BOOK1", "STRAT_X", -10_000_000,
                  currency="CHF", clean_price=102.0, isin="BX"),
            _deal(31, "IRS-MTM", "BOOK2", "STRAT_X", -10_000_000,
                  currency="CHF"),
        ])
        deals_prev = deals_today.copy()
        deals_prev.loc[deals_prev["Dealid"] == 30, "Clean Price"] = 101.0

        b2_today = pd.DataFrame([{
            "Deal": 31, "Dealid": 31,
            "Strategy (Agapes IAS)": "STRAT_X", "MTM": -500_000,
        }])
        # b2_prev is None → dMTM NaN → ratio NaN
        result = compute_strategy_consolidated(deals_today, b2_today, deals_prev, None)
        row = result.iloc[0]
        assert row["hedged_clean_dFV"] == pytest.approx(100_000)
        assert pd.isna(row["hedging_irs_dMtM"])
        assert pd.isna(row["effectiveness_ratio"])


# ---------------------------------------------------------------------------
# Multi-currency flag
# ---------------------------------------------------------------------------

class TestMultiCurrency:
    def test_multi_ccy_strategy_flagged(self):
        deals = pd.DataFrame([
            _deal(40, "BND", "BOOK1", "STRAT_MCC", -10_000_000,
                  currency="CHF", clean_price=100.0, isin="MC1"),
            _deal(41, "BND", "BOOK1", "STRAT_MCC", -5_000_000,
                  currency="EUR", clean_price=100.0, isin="MC2"),
        ])
        result = compute_strategy_consolidated(deals)
        row = result.iloc[0]
        assert bool(row["multi_currency"]) is True
        assert "CHF" in row["currencies"] and "EUR" in row["currencies"]
        assert row["corridor_flag"] == "multi_ccy"
