"""Phase 3a: dual-book load-data via bank-native files.

Verifies that ``ForecastRatePnL.load_data()`` picks up the bank-native triple
and populates Book1/Book2 attributes correctly. Does NOT run the engine
(WASP-dependent), only the loading/filtering path.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from cockpit.engine.pnl.forecast import ForecastRatePnL

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "bank_native"


@pytest.fixture(scope="module")
def loaded() -> ForecastRatePnL:
    pnl = ForecastRatePnL(
        dateRun=datetime(2026, 4, 14),
        export=False,
        input_dir=FIXTURE_ROOT,
        auto_run=False,
    )
    pnl.load_data()
    return pnl


class TestDetection:
    def test_detects_root_with_yyyypp_tree(self):
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 14), export=False,
            input_dir=FIXTURE_ROOT, auto_run=False,
        )
        inputs = pnl._detect_bank_native_input()
        assert inputs is not None
        assert inputs.position_date == pd.Timestamp("2026-04-14")
        assert inputs.pnl_workbook.exists()

    def test_detects_day_dir_directly(self):
        day_dir = FIXTURE_ROOT / "202624" / "2026041400"
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 14), export=False,
            input_dir=day_dir, auto_run=False,
        )
        inputs = pnl._detect_bank_native_input()
        assert inputs is not None
        assert inputs.day_dir == day_dir

    def test_returns_none_on_missing(self, tmp_path):
        pnl = ForecastRatePnL(
            dateRun=datetime(2026, 4, 14), export=False,
            input_dir=tmp_path, auto_run=False,
        )
        assert pnl._detect_bank_native_input() is None


class TestLoadBankNative:
    def test_pnldata_is_book1_plus_synthesized_hcd(self, loaded):
        # 18 native BOOK1 rows + HCD rows synthesized from BOOK2 hedge
        # counter-deals sharing a Strategy IAS with a BOOK1 item.
        assert loaded.pnlData is not None
        assert (loaded.pnlData["IAS Book"] == "BOOK1").all()
        native = loaded.pnlData[loaded.pnlData["Product"] != "HCD"]
        hcd = loaded.pnlData[loaded.pnlData["Product"] == "HCD"]
        assert len(native) == 18
        # Every HCD row must trace to a BOOK1 Strategy IAS
        book1_strats = set(native.loc[native["Strategy IAS"].notna(), "Strategy IAS"])
        assert set(hcd["Strategy IAS"]).issubset(book1_strats)
        assert len(hcd) > 0  # fixture has overlapping strategies

    def test_irsstock_is_book2_irs_only(self, loaded):
        assert loaded.irsStock is not None
        assert len(loaded.irsStock) == 7  # IRS_FVH=3 + IRS_FVO=4
        # Renamed columns for WASP MTM path
        assert "Deal" in loaded.irsStock.columns
        assert "Notional" in loaded.irsStock.columns
        assert "Pay/Receive" in loaded.irsStock.columns

    def test_book2_non_irs_deferred(self, loaded):
        # OPP_Bond_ASW (3) + OPR_FVH (2) = 5 deferred
        assert len(loaded.book2NonIrs) == 5
        assert set(loaded.book2NonIrs["Category2"]) == {"OPP_Bond_ASW", "OPR_FVH"}

    def test_schedule_wired(self, loaded):
        assert loaded.scheduleData is not None
        assert len(loaded.scheduleData) == 30

    def test_wirp_wired(self, loaded):
        assert loaded.wirpData is not None
        assert set(loaded.wirpData["Indice"].unique()) == {
            "CHFSON", "EUREST", "USSOFR", "GBPOIS"
        }

    def test_fx_reapply_applied(self, loaded):
        # Amount_CHF = Amount × FxRate (per-deal, as-of-date snapshot)
        both = pd.concat([loaded.pnlData, loaded.book2NonIrs], ignore_index=True)
        reconstructed = both["Amount"].astype(float) * both["FxRate"].astype(float)
        pd.testing.assert_series_equal(
            both["Amount_CHF"].astype(float),
            reconstructed,
            check_names=False,
            rtol=1e-9,
        )

    def test_pay_receive_derived(self, loaded):
        irs = loaded.irsStock
        # L/B/S → RECEIVE, D → PAY
        is_recv = irs["Direction"].isin(["L", "B", "S"])
        assert (irs.loc[is_recv, "Pay/Receive"] == "RECEIVE").all()
        assert (irs.loc[~is_recv, "Pay/Receive"] == "PAY").all()

    def test_disjoint_book_split(self, loaded):
        # Native BOOK1 (excluding synthesized HCD) ∩ BOOK2 = ∅ on Dealid.
        # Synthesized HCD rows intentionally share dealids with BOOK2 hedge
        # deals — they're the same economic deal viewed as an accrual leg.
        native = loaded.pnlData[loaded.pnlData["Product"] != "HCD"]
        book1_ids = set(native["Dealid"])
        book2_ids = set(loaded.irsStock["Deal"]) | set(loaded.book2NonIrs["Dealid"])
        assert book1_ids.isdisjoint(book2_ids)
