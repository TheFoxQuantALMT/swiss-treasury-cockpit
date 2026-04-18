"""Generate bank-native mock input Excel files mirroring the production layout.

Produces the folder layout:

    tests/fixtures/bank_native/
        202624/
            2026040014/
                K+EUR Daily Rate PnL GVA_20260414.xlsx   (sheets: Book1_Daily_PnL, Book2_Daily_PnL)
                20260414_WIRP.xlsx                        (1 sheet: WIRP)
                20260414_rate_schedule.xlsx               (1 sheet: Operation_Propres EoM)

Coverage: 18 Book1 deals × 12 Book2 deals = 30 deals covering every @Category2
bucket, both directions (L/B/D/S), 4 currencies (CHF/EUR/USD/GBP), fixed /
overnight-floater / term-floater rate types, and Strategy IAS linkage between
Book1 hedged items and Book2 hedging IRS.

Usage:
    uv run python -m tests.fixtures.generate_bank_native
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POSITION_DATE = date(2026, 4, 14)          # Tuesday; BD-1 = 2026-04-13 (Monday)
YEAR_PERIOD = "202624"                     # year 2026 + period index 24
DAY_VARIANT = "2026041400"                 # YYYYMMDD + 2-digit variant (00 = intraday run #1)
DATE_STR = "20260414"

# CHF per 1 unit of deal ccy, as-of position date. Applied consistently — engine
# must re-derive @Amount_CHF = amount × FxRate for forecasts (see memory).
FX = {"CHF": 1.0000, "EUR": 0.9450, "USD": 0.8900, "GBP": 1.1000}

# Mock as-of-date OIS levels per ccy (decimal, annualized).
OIS = {"CHF": 0.0110, "EUR": 0.0235, "USD": 0.0425, "GBP": 0.0410}

# ---------------------------------------------------------------------------
# Column order — preserves bank-native names exactly (including @ prefix).
# Sheet names: Book1_Daily_PnL and Book2_Daily_PnL.
# ---------------------------------------------------------------------------

BOOK1_COLUMNS = [
    "Position Date", "@KeyID", "Portfolio Short Name", "Folder Short Name",
    "Deal Currency", "@Cur_Agg", "Source Product Code", "Source Sub Product Type",
    "@Category", "@Category2", "Deal ID", "IAM Deal ID", "@Direction", "@indexation",
    "Strategy IAS", "Rate Reference", "ISIN Code", "Optimus Reporting FxRate",
    "Trade Date", "Value Date", "Rate Start Date", "Rate End Date",
    "Maturity Date", "Liquidation Date", "CRDS Counterparty Code",
    "Calculated initial Amount (Measure)", "@Amount_CHF", "@NbBasis",
    "Nominal Interest Rate", "Yield To Maturity", "BD - 1 - Rate",
    "CoC/SellDown Carry Rate", "@EqOISRate2", "Credit Spread FIFO",
    "@PnL_Acc_Estim_Unadj", "@PnL_CoC_Estim_Unadj", "@Nb_Day_Adj",
    "@PnL_Acc_Estim_Adj", "@PnL_CoC_Estim_Adj", "[Daily] PnL IAS - ORC",
]

BOOK2_COLUMNS = [
    "Position Date", "@KeyID", "Portfolio Short Name", "Folder Short Name",
    "Deal Currency", "@Cur_Agg", "Source Product Code", "Source Sub Product Type",
    "@Category", "@Category2", "Deal ID", "@Direction", "@indexation",
    "Strategy IAS", "Rate Reference", "ISIN Code", "Optimus Reporting FxRate",
    "Trade Date", "Value Date", "Rate Start Date", "Rate End Date",
    "Maturity Date", "Liquidation Date", "CRDS Counterparty Code",
    "Calculated initial Amount (Measure)", "@Amount_CHF",
    "Nominal Interest Rate", "Yield To Maturity", "BD - 1 - Rate",
    "CoC/SellDown Carry Rate", "@EqOISRate2", "Credit Spread FIFO",
    "@PnL_Acc_Estim_Unadj", "@PnL_CoC_Estim_Unadj", "@Nb_Day_Adj",
    "@PnL_Acc_Estim_Adj", "@PnL_CoC_Estim_Adj", "[Daily] PnL MTM",
]

RATE_SCHEDULE_META_COLUMNS = [
    "Situation_Date", "Legal entity name", "Balancesheet / Off balancesheet",
    "Business - level 1", "Asset / Liability",
    "Chart of account - level 2", "Chart of account - level 3",
    "Chart of account - level 4", "Chart of account - level 5",
    "Sub Perimeter Name", "Trade Date", "Value Date", "Maturity Date",
    "Deal Currency", "Amount", "Rate", "Portfolio", "Branch", "Folder",
    "Deal Number KND", "Rate Type", "Rate index - level 1",
    "Rate index - level Code", "Post-counted interest flag",
]

# Wide monthly bucket columns — 5-year forecast horizon (60 months) per user convention.
FORECAST_MONTHS = 60
_month_cols = [
    f"{POSITION_DATE.year + (POSITION_DATE.month - 1 + i) // 12:04d}/"
    f"{(POSITION_DATE.month - 1 + i) % 12 + 1:02d}"
    for i in range(FORECAST_MONTHS)
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_pnl_acc(amount: float, client_rate: float, ois_rate: float, nb_basis: int = 360) -> float:
    """Daily IAS accrual P&L: amount × (client - ois) / day-count. Nominal is already signed."""
    return round(amount * (client_rate - ois_rate) / nb_basis, 2)


def _mock_pnl_coc(amount: float, ois_rate: float, coc_rate: float, nb_basis: int = 360) -> float:
    """Daily CoC/carry P&L: amount × (ois - coc) / day-count."""
    return round(amount * (ois_rate - coc_rate) / nb_basis, 2)


def _b1(**kw) -> dict:
    """Book1 row builder — fills FX-derived and mock-P&L fields; expects business params explicit."""
    ccy = kw["ccy"]
    amount = kw["amount"]
    client_rate = kw["client_rate"]
    ois = kw.get("ois_rate", OIS[ccy])
    coc = kw.get("coc_rate", ois - 0.0030)
    bd1 = kw.get("bd1_rate", ois - 0.0002)
    nb_basis = kw.get("nb_basis", 360)
    pnl_acc = _mock_pnl_acc(amount, client_rate, ois, nb_basis)
    pnl_coc = _mock_pnl_coc(amount, ois, coc, nb_basis)
    return {
        "Position Date": POSITION_DATE, "@KeyID": kw["key_id"],
        "Portfolio Short Name": kw.get("portfolio", "CC-TREAS"),
        "Folder Short Name": kw.get("folder", f"{ccy}-{kw['sub_product'][:6]}"),
        "Deal Currency": ccy, "@Cur_Agg": ccy,
        "Source Product Code": kw["product"], "Source Sub Product Type": kw["sub_product"],
        "@Category": kw["category"], "@Category2": kw["category2"],
        "Deal ID": kw["deal_id"], "IAM Deal ID": kw.get("iam_deal_id", ""),
        "@Direction": kw["direction"], "@indexation": kw["indexation"],
        "Strategy IAS": kw.get("strategy_ias", ""), "Rate Reference": kw.get("rate_ref", ""),
        "ISIN Code": kw.get("isin", ""), "Optimus Reporting FxRate": FX[ccy],
        "Trade Date": kw["trade_date"], "Value Date": kw["value_date"],
        "Rate Start Date": kw.get("rate_start", kw["value_date"]),
        "Rate End Date": kw.get("rate_end", kw["maturity"]),
        "Maturity Date": kw["maturity"], "Liquidation Date": None,
        "CRDS Counterparty Code": kw["counterparty"],
        "Calculated initial Amount (Measure)": amount,
        "@Amount_CHF": round(amount * FX[ccy], 2), "@NbBasis": nb_basis,
        "Nominal Interest Rate": client_rate, "Yield To Maturity": kw.get("ytm", 0.0),
        "BD - 1 - Rate": bd1, "CoC/SellDown Carry Rate": coc,
        "@EqOISRate2": ois, "Credit Spread FIFO": kw.get("spread", 0.0),
        "@PnL_Acc_Estim_Unadj": pnl_acc, "@PnL_CoC_Estim_Unadj": pnl_coc,
        "@Nb_Day_Adj": kw.get("nb_day_adj", 1),
        "@PnL_Acc_Estim_Adj": pnl_acc, "@PnL_CoC_Estim_Adj": pnl_coc,
        "[Daily] PnL IAS - ORC": kw.get("pnl_realized", round(pnl_acc + pnl_coc, 2)),
    }


def _b2(**kw) -> dict:
    """Book2 row builder — same as _b1 minus IAM Deal ID and @NbBasis; realized col is PnL MTM."""
    ccy = kw["ccy"]
    amount = kw["amount"]
    client_rate = kw["client_rate"]
    ois = kw.get("ois_rate", OIS[ccy])
    coc = kw.get("coc_rate", ois - 0.0030)
    bd1 = kw.get("bd1_rate", ois - 0.0002)
    nb_basis = 360
    pnl_acc = _mock_pnl_acc(amount, client_rate, ois, nb_basis)
    pnl_coc = _mock_pnl_coc(amount, ois, coc, nb_basis)
    return {
        "Position Date": POSITION_DATE, "@KeyID": kw["key_id"],
        "Portfolio Short Name": kw.get("portfolio", "CC-MTM"),
        "Folder Short Name": kw.get("folder", f"{ccy}-{kw['sub_product'][:6]}"),
        "Deal Currency": ccy, "@Cur_Agg": ccy,
        "Source Product Code": kw["product"], "Source Sub Product Type": kw["sub_product"],
        "@Category": kw["category"], "@Category2": kw["category2"],
        "Deal ID": kw["deal_id"], "@Direction": kw["direction"], "@indexation": kw["indexation"],
        "Strategy IAS": kw.get("strategy_ias", ""), "Rate Reference": kw.get("rate_ref", ""),
        "ISIN Code": kw.get("isin", ""), "Optimus Reporting FxRate": FX[ccy],
        "Trade Date": kw["trade_date"], "Value Date": kw["value_date"],
        "Rate Start Date": kw.get("rate_start", kw["value_date"]),
        "Rate End Date": kw.get("rate_end", kw["maturity"]),
        "Maturity Date": kw["maturity"], "Liquidation Date": None,
        "CRDS Counterparty Code": kw["counterparty"],
        "Calculated initial Amount (Measure)": amount,
        "@Amount_CHF": round(amount * FX[ccy], 2),
        "Nominal Interest Rate": client_rate, "Yield To Maturity": kw.get("ytm", 0.0),
        "BD - 1 - Rate": bd1, "CoC/SellDown Carry Rate": coc,
        "@EqOISRate2": ois, "Credit Spread FIFO": kw.get("spread", 0.0),
        "@PnL_Acc_Estim_Unadj": pnl_acc, "@PnL_CoC_Estim_Unadj": pnl_coc,
        "@Nb_Day_Adj": kw.get("nb_day_adj", 1),
        "@PnL_Acc_Estim_Adj": pnl_acc, "@PnL_CoC_Estim_Adj": pnl_coc,
        "[Daily] PnL MTM": kw.get("pnl_realized", round((pnl_acc + pnl_coc) * 3.5, 2)),
    }


# ---------------------------------------------------------------------------
# Book1 — 18 deals covering every @Category2 × direction × rate-type edge case
# ---------------------------------------------------------------------------

BOOK1_ROWS = [
    # === OPP_CASH (5): deposits/loans/MM, fixed + overnight floater ===
    _b1(key_id="B1-001", deal_id="100001", iam_deal_id="IAM-100001",
        category="OPP", category2="OPP_CASH", ccy="CHF", direction="D",
        product="IAM/LD", sub_product="DEPOSIT", indexation="FIXED",
        trade_date=date(2025, 1, 15), value_date=date(2025, 1, 17),
        maturity=date(2026, 7, 17), counterparty="THCCBFIGE",
        amount=50_000_000.0, client_rate=0.0125),
    _b1(key_id="B1-002", deal_id="100002", category="OPP", category2="OPP_CASH",
        ccy="EUR", direction="D", product="IAM/LD", sub_product="DEPOSIT",
        indexation="FIXED",
        trade_date=date(2025, 3, 1), value_date=date(2025, 3, 3),
        maturity=date(2027, 3, 3), counterparty="BKCCBFIGE",
        amount=30_000_000.0, client_rate=0.0250),
    _b1(key_id="B1-003", deal_id="100003", iam_deal_id="IAM-100003",
        category="OPP", category2="OPP_CASH", ccy="CHF", direction="L",
        product="IAM/LD", sub_product="LOAN", indexation="FIXED",
        trade_date=date(2024, 6, 10), value_date=date(2024, 6, 12),
        maturity=date(2027, 6, 12), counterparty="THCCBFIGE",
        amount=-80_000_000.0, client_rate=0.0095),
    _b1(key_id="B1-004", deal_id="100004", category="OPP", category2="OPP_CASH",
        ccy="USD", direction="L", product="IAM/LD", sub_product="LOAN",
        indexation="FLOAT", rate_ref="SOFR",
        trade_date=date(2025, 11, 1), value_date=date(2025, 11, 3),
        rate_start=date(2026, 4, 12), rate_end=date(2026, 4, 15),
        maturity=date(2028, 11, 3), counterparty="BKUSDOUSNY",
        amount=-25_000_000.0, client_rate=0.0450, spread=0.0025),
    _b1(key_id="B1-005", deal_id="100005", category="OPP", category2="OPP_CASH",
        ccy="CHF", direction="D", product="IAM/LD", sub_product="DEPOSIT",
        indexation="FLOAT", rate_ref="SARON",
        trade_date=date(2025, 9, 1), value_date=date(2025, 9, 3),
        rate_start=date(2026, 4, 13), rate_end=date(2026, 4, 14),
        maturity=date(2027, 9, 3), counterparty="THCCBFIGE",
        amount=40_000_000.0, client_rate=0.0115, spread=0.0005),

    # === OPP_Bond_nASW (3): plain-vanilla bonds, no asset-swap ===
    _b1(key_id="B1-006", deal_id="200001", category="OPP", category2="OPP_Bond_nASW",
        ccy="CHF", direction="B", product="BND", sub_product="GOVT_BOND",
        indexation="FIXED", isin="CH0012345678",
        trade_date=date(2024, 1, 20), value_date=date(2024, 1, 22),
        maturity=date(2029, 1, 22), counterparty="BKCHSIXSWX",
        amount=-20_000_000.0, client_rate=0.0150, ytm=0.0175),
    _b1(key_id="B1-007", deal_id="200002", category="OPP", category2="OPP_Bond_nASW",
        ccy="EUR", direction="B", product="BND", sub_product="GOVT_BOND",
        indexation="FIXED", isin="DE0001102624",
        trade_date=date(2024, 3, 10), value_date=date(2024, 3, 12),
        maturity=date(2029, 3, 12), counterparty="BKEUROCLRBE",
        amount=-20_000_000.0, client_rate=0.0250, ytm=0.0285, spread=0.0015),
    _b1(key_id="B1-008", deal_id="200003", category="OPP", category2="OPP_Bond_nASW",
        ccy="EUR", direction="S", product="BND", sub_product="CORP_BOND",
        indexation="FIXED", isin="FR0013999999",
        trade_date=date(2025, 6, 15), value_date=date(2025, 6, 17),
        maturity=date(2030, 6, 17), counterparty="BKEURLCHGB",
        amount=-15_000_000.0, client_rate=0.0275, ytm=0.0310),   # S asset (negative, per DIRECTION_SIDE)

    # === OPP_Bond_ASW (2): accrual leg of asset-swap ===
    _b1(key_id="B1-009", deal_id="300001", iam_deal_id="IAM-300001",
        category="OPP", category2="OPP_Bond_ASW", ccy="CHF", direction="B",
        product="BND", sub_product="CORP_BOND_ASW", indexation="FIXED",
        strategy_ias="STRAT_CHF_ASW_001", isin="CH0001234567",
        trade_date=date(2024, 6, 1), value_date=date(2024, 6, 3),
        maturity=date(2031, 6, 3), counterparty="BKCHSIXSWX",
        amount=-15_000_000.0, client_rate=0.0175, ytm=0.0200, spread=0.0065),
    _b1(key_id="B1-010", deal_id="300002", iam_deal_id="IAM-300002",
        category="OPP", category2="OPP_Bond_ASW", ccy="EUR", direction="B",
        product="BND", sub_product="CORP_BOND_ASW", indexation="FIXED",
        strategy_ias="STRAT_EUR_ASW_001", isin="XS2345678901",
        trade_date=date(2025, 2, 10), value_date=date(2025, 2, 12),
        maturity=date(2030, 2, 12), counterparty="BKEUROCLRBE",
        amount=-25_000_000.0, client_rate=0.0310, ytm=0.0335, spread=0.0080),

    # === OPR_FVH (3): hedged items with Strategy IAS linkage ===
    _b1(key_id="B1-011", deal_id="400001", iam_deal_id="IAM-400001",
        category="OPR", category2="OPR_FVH", ccy="CHF", direction="L",
        product="IAM/LD", sub_product="LOAN", indexation="FIXED",
        strategy_ias="STRAT_CHF_FVH_001",
        trade_date=date(2024, 9, 1), value_date=date(2024, 9, 3),
        maturity=date(2029, 9, 3), counterparty="THCCBFIGE",
        amount=-60_000_000.0, client_rate=0.0145),
    _b1(key_id="B1-012", deal_id="400002", iam_deal_id="IAM-400002",
        category="OPR", category2="OPR_FVH", ccy="EUR", direction="D",
        product="IAM/LD", sub_product="DEPOSIT", indexation="FIXED",
        strategy_ias="STRAT_EUR_FVH_001",
        trade_date=date(2024, 11, 15), value_date=date(2024, 11, 17),
        maturity=date(2029, 11, 17), counterparty="BKCCBFIGE",
        amount=45_000_000.0, client_rate=0.0290),
    _b1(key_id="B1-013", deal_id="400003", iam_deal_id="IAM-400003",
        category="OPR", category2="OPR_FVH", ccy="CHF", direction="B",
        product="BND", sub_product="CORP_BOND", indexation="FIXED",
        strategy_ias="STRAT_CHF_FVH_002", isin="CH0002468135",
        trade_date=date(2025, 4, 10), value_date=date(2025, 4, 14),
        maturity=date(2032, 4, 14), counterparty="BKCHSIXSWX",
        amount=-30_000_000.0, client_rate=0.0195, ytm=0.0220, spread=0.0050),

    # === OPR_nFVH (3): open-risk floaters (SARON3M term, ESTR6M term, SONIA overnight) ===
    _b1(key_id="B1-014", deal_id="500001", category="OPR", category2="OPR_nFVH",
        ccy="CHF", direction="L", product="IAM/LD", sub_product="LOAN",
        indexation="FLOAT", rate_ref="SARON3M",
        trade_date=date(2025, 7, 14), value_date=date(2025, 7, 16),
        rate_start=date(2026, 1, 16), rate_end=date(2026, 4, 16),   # current 3M fix window
        maturity=date(2030, 7, 16), counterparty="THCCBFIGE",
        amount=-35_000_000.0, client_rate=0.0135, spread=0.0020),
    _b1(key_id="B1-015", deal_id="500002", category="OPR", category2="OPR_nFVH",
        ccy="EUR", direction="L", product="IAM/LD", sub_product="LOAN",
        indexation="FLOAT", rate_ref="ESTR6M",
        trade_date=date(2025, 4, 10), value_date=date(2025, 4, 14),
        rate_start=date(2025, 10, 14), rate_end=date(2026, 4, 14),   # current 6M fix window
        maturity=date(2031, 4, 14), counterparty="BKEURLCHGB",
        amount=-20_000_000.0, client_rate=0.0265, spread=0.0030),
    _b1(key_id="B1-016", deal_id="500003", category="OPR", category2="OPR_nFVH",
        ccy="GBP", direction="D", product="IAM/LD", sub_product="DEPOSIT",
        indexation="FLOAT", rate_ref="SONIA",
        trade_date=date(2025, 12, 1), value_date=date(2025, 12, 3),
        rate_start=date(2026, 4, 11), rate_end=date(2026, 4, 14),   # overnight with lookback
        maturity=date(2027, 12, 3), counterparty="BKGBPLCHLN",
        amount=10_000_000.0, client_rate=0.0415),

    # === Other (2): catch-all ===
    _b1(key_id="B1-017", deal_id="600001", category="OPP", category2="Other",
        ccy="USD", direction="D", product="IAM/LD", sub_product="DEPOSIT",
        indexation="FIXED",
        trade_date=date(2025, 5, 20), value_date=date(2025, 5, 22),
        maturity=date(2027, 5, 22), counterparty="BKUSDOUSNY",
        amount=12_000_000.0, client_rate=0.0435),
    _b1(key_id="B1-018", deal_id="600002", category="OPP", category2="Other",
        ccy="CHF", direction="L", product="IAM/LD", sub_product="LOAN",
        indexation="FIXED",
        trade_date=date(2024, 2, 1), value_date=date(2024, 2, 5),
        maturity=date(2026, 8, 5), counterparty="THCCBFIGE",
        amount=-8_000_000.0, client_rate=0.0105),
]

# ---------------------------------------------------------------------------
# Book2 — 12 deals: MtM legs of ASW, FVH hedging IRS, IRS_FVO
# ---------------------------------------------------------------------------

BOOK2_ROWS = [
    # === OPP_Bond_ASW (3): MtM side of the accrual ASW bonds ===
    _b2(key_id="B2-001", deal_id="350001", category="OPP", category2="OPP_Bond_ASW",
        ccy="CHF", direction="B", product="BND", sub_product="CORP_BOND_ASW",
        indexation="FLOAT", strategy_ias="STRAT_CHF_ASW_001", rate_ref="SARON3M",
        isin="CH0001234567",
        trade_date=date(2024, 6, 1), value_date=date(2024, 6, 3),
        rate_start=date(2026, 3, 3), rate_end=date(2026, 6, 3),
        maturity=date(2031, 6, 3), counterparty="BKCHSIXSWX",
        amount=-15_000_000.0, client_rate=0.0115, spread=0.0065),
    _b2(key_id="B2-002", deal_id="350002", category="OPP", category2="OPP_Bond_ASW",
        ccy="EUR", direction="B", product="BND", sub_product="CORP_BOND_ASW",
        indexation="FLOAT", strategy_ias="STRAT_EUR_ASW_001", rate_ref="ESTR6M",
        isin="XS2345678901",
        trade_date=date(2025, 2, 10), value_date=date(2025, 2, 12),
        rate_start=date(2025, 8, 12), rate_end=date(2026, 2, 12),
        maturity=date(2030, 2, 12), counterparty="BKEUROCLRBE",
        amount=-25_000_000.0, client_rate=0.0245, spread=0.0080),
    _b2(key_id="B2-003", deal_id="350003", category="OPP", category2="OPP_Bond_ASW",
        ccy="CHF", direction="S", product="BND", sub_product="CORP_BOND_ASW",
        indexation="FLOAT", rate_ref="SARON3M", isin="CH0009876543",
        trade_date=date(2025, 8, 15), value_date=date(2025, 8, 19),
        rate_start=date(2026, 2, 19), rate_end=date(2026, 5, 19),
        maturity=date(2029, 8, 19), counterparty="BKCHSIXSWX",
        amount=-10_000_000.0, client_rate=0.0120, spread=0.0055),   # S asset (negative, per DIRECTION_SIDE)

    # === OPR_FVH (2): MtM mark on FVH hedging designation ===
    _b2(key_id="B2-004", deal_id="700001", category="OPR", category2="OPR_FVH",
        ccy="CHF", direction="L", product="IAM/LD", sub_product="LOAN",
        indexation="FIXED", strategy_ias="STRAT_CHF_FVH_001",
        trade_date=date(2024, 9, 1), value_date=date(2024, 9, 3),
        maturity=date(2029, 9, 3), counterparty="THCCBFIGE",
        amount=-60_000_000.0, client_rate=0.0145),
    _b2(key_id="B2-005", deal_id="700002", category="OPR", category2="OPR_FVH",
        ccy="EUR", direction="D", product="IAM/LD", sub_product="DEPOSIT",
        indexation="FIXED", strategy_ias="STRAT_EUR_FVH_001",
        trade_date=date(2024, 11, 15), value_date=date(2024, 11, 17),
        maturity=date(2029, 11, 17), counterparty="BKCCBFIGE",
        amount=45_000_000.0, client_rate=0.0290),

    # === IRS_FVH (3): IRS designated as fair-value hedging instrument ===
    _b2(key_id="B2-006", deal_id="800001", category="OPR", category2="IRS_FVH",
        ccy="CHF", direction="D", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", strategy_ias="STRAT_CHF_FVH_001", rate_ref="SARON3M",
        trade_date=date(2024, 9, 1), value_date=date(2024, 9, 3),
        rate_start=date(2026, 3, 3), rate_end=date(2026, 6, 3),
        maturity=date(2029, 9, 3), counterparty="BKCHSIXSWX",
        amount=60_000_000.0, client_rate=0.0120),   # pay-float (hedges fixed-rate asset)
    _b2(key_id="B2-007", deal_id="800002", category="OPR", category2="IRS_FVH",
        ccy="EUR", direction="L", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", strategy_ias="STRAT_EUR_FVH_001", rate_ref="ESTR6M",
        trade_date=date(2024, 11, 15), value_date=date(2024, 11, 17),
        rate_start=date(2025, 11, 17), rate_end=date(2026, 5, 17),
        maturity=date(2029, 11, 17), counterparty="BKEURLCHGB",
        amount=-45_000_000.0, client_rate=0.0240),
    _b2(key_id="B2-008", deal_id="800003", category="OPR", category2="IRS_FVH",
        ccy="CHF", direction="L", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", strategy_ias="STRAT_CHF_FVH_002", rate_ref="SARON3M",
        trade_date=date(2025, 4, 10), value_date=date(2025, 4, 14),
        rate_start=date(2026, 1, 14), rate_end=date(2026, 4, 14),
        maturity=date(2032, 4, 14), counterparty="BKCHSIXSWX",
        amount=-30_000_000.0, client_rate=0.0115),

    # === IRS_FVO (4): IRS under fair-value option (no hedge designation) ===
    _b2(key_id="B2-009", deal_id="900001", category="OPR", category2="IRS_FVO",
        ccy="CHF", direction="D", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", rate_ref="SARON3M",
        trade_date=date(2025, 7, 1), value_date=date(2025, 7, 3),
        rate_start=date(2026, 1, 3), rate_end=date(2026, 4, 3),
        maturity=date(2030, 7, 3), counterparty="BKCHSIXSWX",
        amount=50_000_000.0, client_rate=0.0130),
    _b2(key_id="B2-010", deal_id="900002", category="OPR", category2="IRS_FVO",
        ccy="EUR", direction="D", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", rate_ref="ESTR6M",
        trade_date=date(2025, 2, 10), value_date=date(2025, 2, 12),
        rate_start=date(2025, 10, 12), rate_end=date(2026, 4, 12),
        maturity=date(2030, 2, 12), counterparty="BKEURLCHGB",
        amount=100_000_000.0, client_rate=0.0225),
    _b2(key_id="B2-011", deal_id="900003", category="OPR", category2="IRS_FVO",
        ccy="USD", direction="L", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", rate_ref="SOFR",
        trade_date=date(2025, 10, 1), value_date=date(2025, 10, 3),
        rate_start=date(2026, 4, 3), rate_end=date(2026, 5, 3),
        maturity=date(2028, 10, 3), counterparty="BKUSDOUSNY",
        amount=-40_000_000.0, client_rate=0.0420),
    _b2(key_id="B2-012", deal_id="900004", category="OPR", category2="IRS_FVO",
        ccy="CHF", direction="L", product="IRS", sub_product="VANILLA_IRS",
        indexation="FLOAT", rate_ref="SARON3M",
        trade_date=date(2024, 5, 20), value_date=date(2024, 5, 22),
        rate_start=date(2026, 2, 22), rate_end=date(2026, 5, 22),
        maturity=date(2029, 5, 22), counterparty="BKCHSIXSWX",
        amount=-20_000_000.0, client_rate=0.0125),
]

# ---------------------------------------------------------------------------
# WIRP — market-implied policy rate expectations (4 central banks × 3 meetings)
# ---------------------------------------------------------------------------

WIRP_ROWS = [
    {"Indice": "SARON", "Meeting Date": date(2026, 6, 18), "Rate": 0.0100, "Hike / Cut": -0.0025},
    {"Indice": "SARON", "Meeting Date": date(2026, 9, 24), "Rate": 0.0075, "Hike / Cut": -0.0025},
    {"Indice": "SARON", "Meeting Date": date(2026, 12, 17), "Rate": 0.0075, "Hike / Cut": 0.0000},
    {"Indice": "ESTR",  "Meeting Date": date(2026, 6,  4), "Rate": 0.0225, "Hike / Cut": -0.0010},
    {"Indice": "ESTR",  "Meeting Date": date(2026, 9, 10), "Rate": 0.0200, "Hike / Cut": -0.0025},
    {"Indice": "ESTR",  "Meeting Date": date(2026, 12, 17), "Rate": 0.0200, "Hike / Cut": 0.0000},
    {"Indice": "SOFR",  "Meeting Date": date(2026, 6, 17), "Rate": 0.0400, "Hike / Cut": -0.0025},
    {"Indice": "SOFR",  "Meeting Date": date(2026, 9, 16), "Rate": 0.0375, "Hike / Cut": -0.0025},
    {"Indice": "SOFR",  "Meeting Date": date(2026, 12, 16), "Rate": 0.0350, "Hike / Cut": -0.0025},
    {"Indice": "SONIA", "Meeting Date": date(2026, 6, 18), "Rate": 0.0385, "Hike / Cut": -0.0025},
    {"Indice": "SONIA", "Meeting Date": date(2026, 9, 17), "Rate": 0.0360, "Hike / Cut": -0.0025},
    {"Indice": "SONIA", "Meeting Date": date(2026, 12, 17), "Rate": 0.0360, "Hike / Cut": 0.0000},
]

# ---------------------------------------------------------------------------
# rate_schedule — wide monthly nominal per deal (all 30 deals)
# ---------------------------------------------------------------------------

def _rs_row(*, deal_id: str, ccy: str, direction: str, amount: float, rate: float,
            maturity: date, product: str, rate_type: str, rate_idx: str = "",
            sub_perimeter: str = "CC", folder: str | None = None) -> dict:
    """Build one rate_schedule row; monthly columns filled with nominal up to maturity."""
    asset_liab = "Asset" if direction in {"L", "B"} else "Liability"
    row = {
        "Situation_Date": POSITION_DATE,
        "Legal entity name": "BankCo AG",
        "Balancesheet / Off balancesheet": "Balancesheet",
        "Business - level 1": "Treasury",
        "Asset / Liability": asset_liab,
        "Chart of account - level 2": "Money Market" if product == "MM" else product,
        "Chart of account - level 3": "Interbank",
        "Chart of account - level 4": "",
        "Chart of account - level 5": "",
        "Sub Perimeter Name": sub_perimeter,
        "Trade Date": POSITION_DATE,
        "Value Date": POSITION_DATE,
        "Maturity Date": maturity,
        "Deal Currency": ccy,
        "Amount": amount,
        "Rate": rate,
        "Portfolio": "CC-TREAS",
        "Branch": "GVA",
        "Folder": folder or f"{ccy}-{product}",
        "Deal Number KND": deal_id,
        "Rate Type": rate_type,
        "Rate index - level 1": rate_idx,
        "Rate index - level Code": rate_idx,
        "Post-counted interest flag": "N",
    }
    for col in _month_cols:
        year, month = map(int, col.split("/"))
        bucket_end = date(year + (month == 12), month % 12 + 1, 1)
        row[col] = amount if bucket_end <= maturity else 0.0
    return row


def _rs_rows_from_books() -> list[dict]:
    """Derive rate_schedule rows from the Book1 + Book2 deal definitions."""
    rows = []
    for row in BOOK1_ROWS + BOOK2_ROWS:
        rate_type = "FLOAT" if row["@indexation"] == "FLOAT" else "FIXED"
        rows.append(_rs_row(
            deal_id=row["Deal ID"], ccy=row["Deal Currency"],
            direction=row["@Direction"],
            amount=row["Calculated initial Amount (Measure)"],
            rate=row["Nominal Interest Rate"],
            maturity=row["Maturity Date"],
            product=row["Source Product Code"].split("/")[0],
            rate_type=rate_type,
            rate_idx=row["Rate Reference"] or "",
        ))
    return rows


RATE_SCHEDULE_ROWS = _rs_rows_from_books()

# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_fixture(out_root: Path) -> None:
    day_dir = out_root / YEAR_PERIOD / DAY_VARIANT
    day_dir.mkdir(parents=True, exist_ok=True)

    pnl_path = day_dir / f"K+EUR Daily Rate PnL GVA_{DATE_STR}.xlsx"
    with pd.ExcelWriter(pnl_path, engine="openpyxl") as writer:
        pd.DataFrame(BOOK1_ROWS, columns=BOOK1_COLUMNS).to_excel(
            writer, sheet_name="Book1_Daily_PnL", index=False)
        pd.DataFrame(BOOK2_ROWS, columns=BOOK2_COLUMNS).to_excel(
            writer, sheet_name="Book2_Daily_PnL", index=False)

    wirp_path = day_dir / f"{DATE_STR}_WIRP.xlsx"
    with pd.ExcelWriter(wirp_path, engine="openpyxl") as writer:
        pd.DataFrame(WIRP_ROWS).to_excel(writer, sheet_name="WIRP", index=False)

    rs_path = day_dir / f"{DATE_STR}_rate_schedule.xlsx"
    rs_cols = RATE_SCHEDULE_META_COLUMNS + _month_cols
    with pd.ExcelWriter(rs_path, engine="openpyxl") as writer:
        pd.DataFrame(RATE_SCHEDULE_ROWS, columns=rs_cols).to_excel(
            writer, sheet_name="Operation_Propres EoM", index=False)

    print(f"Wrote fixture to {day_dir}:")
    for p in sorted(day_dir.iterdir()):
        print(f"  - {p.name}")
    print(f"  Book1 deals: {len(BOOK1_ROWS)}  Book2 deals: {len(BOOK2_ROWS)}  "
          f"rate_schedule rows: {len(RATE_SCHEDULE_ROWS)}  monthly cols: {len(_month_cols)}")


if __name__ == "__main__":
    out_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "bank_native"
    write_fixture(out_root)
