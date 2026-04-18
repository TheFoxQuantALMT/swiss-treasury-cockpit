"""Round-trip tests for realized-daily snapshot store + MTD loader."""
from __future__ import annotations

import pandas as pd

from cockpit.engine.pnl.kpi_store import (
    load_pnl_explain_snapshot,
    load_realized_mtd,
    save_pnl_explain_snapshot,
    save_realized_daily,
)


def _mk_book1(pairs: list[tuple[str, float, float]]) -> pd.DataFrame:
    """pairs = [(ccy, accrual, ias_realized)]."""
    return pd.DataFrame([
        {"Currency": c, "PnL_Acc_Adj": a, "PnL_Realized": i}
        for c, a, i in pairs
    ])


def _mk_book2(pairs: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"Currency": c, "PnL_Realized": v} for c, v in pairs])


def test_save_realized_daily_returns_none_when_all_zero(tmp_path):
    b1 = _mk_book1([("CHF", 0.0, 0.0)])
    b2 = _mk_book2([("CHF", 0.0)])
    path = save_realized_daily(b1, b2, "2026-04-14", tmp_path)
    assert path is None


def test_save_and_load_realized_mtd_roundtrip(tmp_path):
    # Day 1: only CHF activity
    save_realized_daily(
        _mk_book1([("CHF", 100_000.0, 10_000.0), ("EUR", 0.0, 0.0)]),
        _mk_book2([("CHF", -1_000.0)]),
        "2026-04-14", tmp_path,
    )
    # Day 2: CHF + EUR
    save_realized_daily(
        _mk_book1([("CHF", 50_000.0, 5_000.0), ("EUR", 30_000.0, 2_000.0)]),
        _mk_book2([("CHF", 500.0), ("EUR", 200.0)]),
        "2026-04-15", tmp_path,
    )
    # Out-of-window day — should be ignored
    save_realized_daily(
        _mk_book1([("CHF", 999_000.0, 999_000.0)]),
        None,
        "2026-03-31", tmp_path,
    )

    result = load_realized_mtd(
        tmp_path, month_start="2026-04-01", date_run="2026-04-15",
    )
    assert result is not None
    assert result["has_data"] is True
    assert result["days_counted"] == 2

    rows_by_ccy = {r["currency"]: r for r in result["rows"]}
    assert set(rows_by_ccy) == {"CHF", "EUR"}
    # CHF totals: accrual = 100k + 50k; IAS = 10k + 5k
    assert rows_by_ccy["CHF"]["book1_accrual"] == 150_000.0
    assert rows_by_ccy["CHF"]["book1_ias"] == 15_000.0
    assert rows_by_ccy["CHF"]["book1_total"] == 165_000.0
    # Book2 MTM for CHF = -1000 + 500 = -500
    assert rows_by_ccy["CHF"]["book2_mtm"] == -500.0
    # EUR totals: day-1 was zero, so only day-2 values
    assert rows_by_ccy["EUR"]["book1_accrual"] == 30_000.0
    assert rows_by_ccy["EUR"]["book1_ias"] == 2_000.0

    assert result["totals"]["book1_accrual"] == 180_000.0
    assert result["totals"]["book1_ias"] == 17_000.0
    assert result["totals"]["book1_total"] == 197_000.0


def test_load_realized_mtd_missing_dir(tmp_path):
    # No kpi_snapshots subdir at all
    assert load_realized_mtd(tmp_path, "2026-04-01", "2026-04-18") is None


def test_load_realized_mtd_empty_window(tmp_path):
    save_realized_daily(
        _mk_book1([("CHF", 100_000.0, 0.0)]),
        None,
        "2026-03-31", tmp_path,
    )
    # Window is April — March file is out of range
    result = load_realized_mtd(tmp_path, "2026-04-01", "2026-04-18")
    assert result is not None
    assert result["has_data"] is False
    assert result["days_counted"] == 0


# ---------------------------------------------------------------------------
# P&L Explain snapshot
# ---------------------------------------------------------------------------

def _mk_pnl_by_deal(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _mk_pnl_all_s(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_save_pnl_explain_snapshot_roundtrip(tmp_path):
    by_deal = _mk_pnl_by_deal([
        {"Dealid": "D1", "Counterparty": "UBS", "Currency": "CHF", "Product": "IAM/LD",
         "Direction": "L", "Shock": "0", "PnL_Simple": 100_000, "Nominal": 10_000_000},
        {"Dealid": "D1", "Counterparty": "UBS", "Currency": "CHF", "Product": "IAM/LD",
         "Direction": "L", "Shock": "0", "PnL_Simple": 50_000, "Nominal": 10_000_000},
        # Shock != 0 should be filtered out
        {"Dealid": "D1", "Counterparty": "UBS", "Currency": "CHF", "Product": "IAM/LD",
         "Direction": "L", "Shock": "50", "PnL_Simple": 999_999, "Nominal": 10_000_000},
    ])
    all_s = _mk_pnl_all_s([
        {"Indice": "PnL_Simple", "Shock": "0", "Deal currency": "CHF", "Value": 150_000},
        {"Indice": "OISfwd", "Shock": "0", "Deal currency": "CHF", "Value": 0.005},
        {"Indice": "RateRef", "Shock": "0", "Deal currency": "CHF", "Value": 0.004},
        {"Indice": "Nominal", "Shock": "0", "Deal currency": "CHF", "Value": 10_000_000},
        # Wrong shock / wrong indice dropped
        {"Indice": "OISfwd", "Shock": "50", "Deal currency": "CHF", "Value": 0.01},
        {"Indice": "Random", "Shock": "0", "Deal currency": "CHF", "Value": 7},
    ])

    path = save_pnl_explain_snapshot(by_deal, all_s, "2026-03-31", tmp_path)
    assert path is not None and path.exists()

    loaded_by_deal, loaded_all_s, date = load_pnl_explain_snapshot(tmp_path)
    assert date == "2026-03-31"
    assert loaded_by_deal is not None
    # D1 should be aggregated to a single row with PnL_Simple = 150_000 (shock=50 filtered)
    assert len(loaded_by_deal) == 1
    assert loaded_by_deal.iloc[0]["PnL_Simple"] == 150_000
    assert loaded_by_deal.iloc[0]["Shock"] == "0"

    assert loaded_all_s is not None
    # Only the 4 shock=0 rows with expected indices survive
    assert len(loaded_all_s) == 4
    assert set(loaded_all_s["Indice"]) == {"PnL_Simple", "OISfwd", "RateRef", "Nominal"}


def test_load_pnl_explain_respects_on_or_before(tmp_path):
    by_deal = _mk_pnl_by_deal([
        {"Dealid": "D1", "Currency": "CHF", "Shock": "0",
         "PnL_Simple": 100.0, "Nominal": 1_000},
    ])
    all_s = _mk_pnl_all_s([
        {"Indice": "PnL_Simple", "Shock": "0", "Deal currency": "CHF", "Value": 100},
    ])
    save_pnl_explain_snapshot(by_deal, all_s, "2026-03-31", tmp_path)
    save_pnl_explain_snapshot(by_deal, all_s, "2026-04-15", tmp_path)
    save_pnl_explain_snapshot(by_deal, all_s, "2026-04-18", tmp_path)

    _, _, d = load_pnl_explain_snapshot(tmp_path, on_or_before="2026-04-01")
    assert d == "2026-03-31"

    _, _, d = load_pnl_explain_snapshot(tmp_path, on_or_before="2026-04-16")
    assert d == "2026-04-15"
