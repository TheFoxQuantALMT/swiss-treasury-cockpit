"""Generate ideal-format mock input Excel files for testing.

Creates 4 files in the specified output directory:
  - deals.xlsx    (unified BOOK1 + BOOK2)
  - rate_schedule.xlsx (monthly nominal balances)
  - wirp.xlsx     (rate expectations)
  - reference_table.xlsx (counterparty metadata)

Usage:
    python -m tests.fixtures.generate_mock_inputs [output_dir]
    # Default output: tests/fixtures/ideal_input/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# deals.xlsx — unified BOOK1 + BOOK2
# ---------------------------------------------------------------------------

DEALS_DATA = [
    # BOOK1: IAM/LD deposits (CHF, EUR)
    {
        "deal_id": 100001, "product": "IAM/LD", "currency": "CHF", "direction": "D",
        "book": "BOOK1", "amount": 50_000_000, "client_rate": 0.0125,
        "eq_ois_rate": 0.0110, "ytm": 0.0, "coc_rate": 0.0080, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-01-15", "value_date": "2025-01-17",
        "maturity_date": "2026-07-17", "strategy_ias": "STRAT_CHF_001", "perimeter": "CC",
        "counterparty": "THCCBFIGE", "hedge_type": "cash_flow", "ias_standard": "IFRS9", "designation_date": "2025-06-15",
        "pay_receive": None, "notional": None, "last_fixing_date": None, "next_fixing_date": None,
    },
    {
        "deal_id": 100002, "product": "IAM/LD", "currency": "EUR", "direction": "D",
        "book": "BOOK1", "amount": 30_000_000, "client_rate": 0.0250,
        "eq_ois_rate": 0.0235, "ytm": 0.0, "coc_rate": 0.0070, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-03-01", "value_date": "2025-03-03",
        "maturity_date": "2027-03-03", "strategy_ias": None, "perimeter": "CC",
        "counterparty": "BKCCBFIGE", "pay_receive": None, "notional": None, "last_fixing_date": None, "next_fixing_date": None,
    },
    # BOOK1: IAM/LD loan (CHF)
    {
        "deal_id": 100003, "product": "IAM/LD", "currency": "CHF", "direction": "L",
        "book": "BOOK1", "amount": -80_000_000, "client_rate": 0.0095,
        "eq_ois_rate": 0.0110, "ytm": 0.0, "coc_rate": 0.0080, "spread": 0.0,
        "floating_index": "", "trade_date": "2024-06-10", "value_date": "2024-06-12",
        "maturity_date": "2027-06-12", "strategy_ias": "STRAT_CHF_002", "perimeter": "CC",
        "counterparty": "THCCBFIGE", "hedge_type": "fair_value", "ias_standard": "IAS39", "designation_date": "2025-01-20",
    },
    # BOOK1: IAM/LD floating (SARON)
    {
        "deal_id": 100004, "product": "IAM/LD", "currency": "CHF", "direction": "L",
        "book": "BOOK1", "amount": -25_000_000, "client_rate": 0.0,
        "eq_ois_rate": 0.0110, "ytm": 0.0, "coc_rate": 0.0080, "spread": 0.0015,
        "floating_index": "SARON", "trade_date": "2025-09-01", "value_date": "2025-09-03",
        "maturity_date": "2028-09-03", "strategy_ias": None, "perimeter": "CC",
    },
    # BOOK1: BND (CHF bond, bought)
    {
        "deal_id": 200001, "product": "BND", "currency": "CHF", "direction": "B",
        "book": "BOOK1", "amount": 20_000_000, "client_rate": 0.0150,
        "eq_ois_rate": 0.0110, "ytm": 0.0175, "coc_rate": 0.0080, "spread": 0.0,
        "floating_index": "", "trade_date": "2024-01-20", "value_date": "2024-01-22",
        "maturity_date": "2029-01-22", "strategy_ias": None, "perimeter": "CC",
    },
    # BOOK1: BND (EUR bond, sold)
    {
        "deal_id": 200002, "product": "BND", "currency": "EUR", "direction": "S",
        "book": "BOOK1", "amount": -15_000_000, "client_rate": 0.0275,
        "eq_ois_rate": 0.0235, "ytm": 0.0310, "coc_rate": 0.0070, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-06-15", "value_date": "2025-06-17",
        "maturity_date": "2030-06-17", "strategy_ias": "STRAT_EUR_001", "perimeter": "CC",
        "counterparty": "BKCCBFIGE", "hedge_type": "cash_flow", "ias_standard": "IFRS9", "designation_date": "2025-09-01",
    },
    # BOOK1: FXS (USD swap)
    {
        "deal_id": 300001, "product": "FXS", "currency": "USD", "direction": "D",
        "book": "BOOK1", "amount": 40_000_000, "client_rate": 0.0430,
        "eq_ois_rate": 0.0450, "ytm": 0.0, "coc_rate": 0.0090, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-11-01", "value_date": "2025-11-03",
        "maturity_date": "2026-11-03", "strategy_ias": None, "perimeter": "CC",
    },
    # BOOK1: GBP deposit
    {
        "deal_id": 100005, "product": "IAM/LD", "currency": "GBP", "direction": "D",
        "book": "BOOK1", "amount": 10_000_000, "client_rate": 0.0440,
        "eq_ois_rate": 0.0460, "ytm": 0.0, "coc_rate": 0.0085, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-12-01", "value_date": "2025-12-03",
        "maturity_date": "2026-12-03", "strategy_ias": None, "perimeter": "CC",
    },
    # BOOK1: Strategy IAS deal (IAM/LD with hedge designation)
    {
        "deal_id": 100006, "product": "IAM/LD", "currency": "CHF", "direction": "D",
        "book": "BOOK1", "amount": 60_000_000, "client_rate": 0.0100,
        "eq_ois_rate": 0.0110, "ytm": 0.0, "coc_rate": 0.0080, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-02-01", "value_date": "2025-02-03",
        "maturity_date": "2028-02-03", "strategy_ias": None, "perimeter": "CC",
        "counterparty": "THCCBFIGE", "pay_receive": None, "notional": None, "last_fixing_date": None, "next_fixing_date": None,
    },
    # BOOK1: WM perimeter deal
    {
        "deal_id": 100007, "product": "IAM/LD", "currency": "CHF", "direction": "D",
        "book": "BOOK1", "amount": 15_000_000, "client_rate": 0.0050,
        "eq_ois_rate": 0.0110, "ytm": 0.0, "coc_rate": 0.0080, "spread": 0.0,
        "floating_index": "", "trade_date": "2025-04-01", "value_date": "2025-04-03",
        "maturity_date": "2026-10-03", "strategy_ias": None, "perimeter": "WM",
        "counterparty": "THCCBFIGE", "pay_receive": None, "notional": None, "last_fixing_date": None, "next_fixing_date": None,
    },
    # BOOK2: IRS (pay fixed, receive SARON)
    {
        "deal_id": 400001, "product": "IRS", "currency": "CHF", "direction": "D",
        "book": "BOOK2", "amount": 0, "client_rate": 0.0120,
        "eq_ois_rate": 0.0, "ytm": 0.0, "coc_rate": 0.0, "spread": 0.0,
        "floating_index": "SARON", "trade_date": "2025-03-15", "value_date": "2025-03-17",
        "maturity_date": "2030-03-17", "strategy_ias": "STRAT_CHF_001", "perimeter": "CC",
        "counterparty": "THCCBFIGE", "hedge_type": "cash_flow", "ias_standard": "IFRS9", "designation_date": "2025-06-15",
        "last_fixing_date": "2026-03-17", "next_fixing_date": "2026-06-17",
    },
    # BOOK2: IRS (receive fixed, pay SARON)
    {
        "deal_id": 400002, "product": "IRS", "currency": "CHF", "direction": "D",
        "book": "BOOK2", "amount": 0, "client_rate": 0.0095,
        "eq_ois_rate": 0.0, "ytm": 0.0, "coc_rate": 0.0, "spread": 0.0,
        "floating_index": "SARON", "trade_date": "2024-11-01", "value_date": "2024-11-03",
        "maturity_date": "2029-11-03", "strategy_ias": "STRAT_CHF_002", "perimeter": "CC",
        "counterparty": "BKCCBFIGE", "hedge_type": "fair_value", "ias_standard": "IAS39", "designation_date": "2025-01-20",
        "last_fixing_date": "2026-02-03", "next_fixing_date": "2026-05-03",
    },
    # BOOK2: IRS EUR
    {
        "deal_id": 400003, "product": "IRS", "currency": "EUR", "direction": "D",
        "book": "BOOK2", "amount": 0, "client_rate": 0.0230,
        "eq_ois_rate": 0.0, "ytm": 0.0, "coc_rate": 0.0, "spread": 0.0,
        "floating_index": "ESTR", "trade_date": "2025-06-01", "value_date": "2025-06-03",
        "maturity_date": "2028-06-03", "strategy_ias": "STRAT_EUR_001", "perimeter": "CC",
        "counterparty": "CLI-MT-CIB", "hedge_type": "cash_flow", "ias_standard": "IFRS9", "designation_date": "2025-09-01",
        "last_fixing_date": "2026-03-03", "next_fixing_date": "2026-06-03",
    },
]

# ---------------------------------------------------------------------------
# rate_schedule.xlsx — monthly nominal balances
# ---------------------------------------------------------------------------

# Generate 60 months of YYYY/MM columns starting 2026/04
_MONTHS = [f"{2026 + (3 + i) // 12}/{((3 + i) % 12) + 1:02d}" for i in range(60)]


def _schedule_row(deal_id, direction, currency, rate_type, amount, mat_month_idx):
    """Build a schedule row: flat nominal until maturity, then zero."""
    row = {
        "deal_id": deal_id,
        "direction": direction,
        "currency": currency,
        "rate_type": rate_type,
    }
    for i, m in enumerate(_MONTHS):
        row[m] = amount if i < mat_month_idx else 0.0
    return row


SCHEDULE_DATA = [
    _schedule_row(100001, "D", "CHF", "F", 50_000_000, 16),    # matures 2027/07
    _schedule_row(100002, "D", "EUR", "F", 30_000_000, 12),    # matures 2027/03
    _schedule_row(100003, "L", "CHF", "F", -80_000_000, 27),   # matures 2028/06
    _schedule_row(100004, "L", "CHF", "V", -25_000_000, 30),   # floating, matures 2028/09
    _schedule_row(200001, "B", "CHF", "F", 20_000_000, 34),    # bond, matures 2029/01
    _schedule_row(200002, "S", "EUR", "F", -15_000_000, 51),   # sold bond, matures 2030/06
    _schedule_row(300001, "D", "USD", "F", 40_000_000, 8),     # FX swap, matures 2026/11
    _schedule_row(100005, "D", "GBP", "F", 10_000_000, 9),     # GBP deposit, matures 2026/12
    _schedule_row(100006, "D", "CHF", "F", 60_000_000, 23),    # strategy deal, matures 2028/02
    _schedule_row(100007, "D", "CHF", "F", 15_000_000, 7),     # WM deal, matures 2026/10
]

# ---------------------------------------------------------------------------
# wirp.xlsx — rate expectations (central bank meeting dates)
# ---------------------------------------------------------------------------

WIRP_DATA = [
    # CHF (CHFSON) — SNB meetings
    {"index": "CHFSON", "meeting_date": "2026-06-18", "rate": 0.0050, "change_bps": -25},
    {"index": "CHFSON", "meeting_date": "2026-09-24", "rate": 0.0050, "change_bps": 0},
    {"index": "CHFSON", "meeting_date": "2026-12-17", "rate": 0.0025, "change_bps": -25},
    {"index": "CHFSON", "meeting_date": "2027-03-25", "rate": 0.0025, "change_bps": 0},
    {"index": "CHFSON", "meeting_date": "2027-06-17", "rate": 0.0025, "change_bps": 0},
    # EUR (EUREST) — ECB meetings
    {"index": "EUREST", "meeting_date": "2026-06-04", "rate": 0.0200, "change_bps": -25},
    {"index": "EUREST", "meeting_date": "2026-07-16", "rate": 0.0200, "change_bps": 0},
    {"index": "EUREST", "meeting_date": "2026-09-10", "rate": 0.0175, "change_bps": -25},
    {"index": "EUREST", "meeting_date": "2026-10-29", "rate": 0.0175, "change_bps": 0},
    {"index": "EUREST", "meeting_date": "2026-12-17", "rate": 0.0150, "change_bps": -25},
    # USD (USSOFR) — Fed meetings
    {"index": "USSOFR", "meeting_date": "2026-06-17", "rate": 0.0400, "change_bps": -25},
    {"index": "USSOFR", "meeting_date": "2026-07-29", "rate": 0.0400, "change_bps": 0},
    {"index": "USSOFR", "meeting_date": "2026-09-16", "rate": 0.0375, "change_bps": -25},
    {"index": "USSOFR", "meeting_date": "2026-11-04", "rate": 0.0375, "change_bps": 0},
    {"index": "USSOFR", "meeting_date": "2026-12-16", "rate": 0.0350, "change_bps": -25},
    # GBP (GBPOIS) — BoE meetings
    {"index": "GBPOIS", "meeting_date": "2026-06-18", "rate": 0.0400, "change_bps": -25},
    {"index": "GBPOIS", "meeting_date": "2026-08-06", "rate": 0.0400, "change_bps": 0},
    {"index": "GBPOIS", "meeting_date": "2026-09-17", "rate": 0.0375, "change_bps": -25},
    {"index": "GBPOIS", "meeting_date": "2026-11-05", "rate": 0.0375, "change_bps": 0},
]

# ---------------------------------------------------------------------------
# reference_table.xlsx — counterparty metadata
# ---------------------------------------------------------------------------

REFERENCE_DATA = [
    {"counterparty": "THCCBFIGE", "rating": "AA+", "hqla_level": "L1", "country": "CH"},
    {"counterparty": "BKCCBFIGE", "rating": "AA", "hqla_level": "L1", "country": "CH"},
    {"counterparty": "THCCBZIWE", "rating": "AA+", "hqla_level": "L1", "country": "CH"},
    {"counterparty": "WCCCBFIGE", "rating": "A+", "hqla_level": "L2A", "country": "CH"},
    {"counterparty": "THCCHFIGE", "rating": "AA-", "hqla_level": "L1", "country": "CH"},
    {"counterparty": "CLI-MT-CIB", "rating": "A", "hqla_level": "L2A", "country": "FR"},
    {"counterparty": "CPFNCLI", "rating": "BBB+", "hqla_level": "L2B", "country": "FR"},
    {"counterparty": "CLI-FI-CIB", "rating": "A-", "hqla_level": "L2A", "country": "DE"},
]


# ---------------------------------------------------------------------------
# budget.xlsx — monthly NII budget per currency
# ---------------------------------------------------------------------------

def _generate_budget_data():
    """12 months × 4 currencies with slight growth trend."""
    rows = []
    base = {"CHF": 125000, "EUR": 85000, "USD": 60000, "GBP": 15000}
    months = [f"2026-{m:02d}" for m in range(4, 16)]  # 2026-04 to 2027-03
    months = [m if int(m.split("-")[1]) <= 12 else f"{int(m.split('-')[0])+1}-{int(m.split('-')[1])-12:02d}" for m in months]
    for i, m in enumerate(months):
        for ccy, base_nii in base.items():
            rows.append({
                "currency": ccy,
                "month": m,
                "budget_nii": round(base_nii * (1 + 0.005 * i), 2),
                "perimeter": "CC",
            })
    return rows


BUDGET_DATA = _generate_budget_data()


# ---------------------------------------------------------------------------
# scenarios.xlsx — BCBS 368 rate shock definitions
# ---------------------------------------------------------------------------

def _generate_scenarios_data():
    """Use default BCBS 368 scenarios."""
    from cockpit.data.parsers.scenarios import get_default_scenarios
    return get_default_scenarios().to_dict("records")


# ---------------------------------------------------------------------------
# alert_thresholds.xlsx — per-currency alert threshold overrides
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# nmd_profiles.xlsx — Non-Maturing Deposit behavioral profiles
# ---------------------------------------------------------------------------

NMD_PROFILES_DATA = [
    # Core deposits: stable, long behavioral maturity, low beta
    {"product": "IAM/LD", "currency": "CHF", "direction": "D", "tier": "core",
     "behavioral_maturity_years": 5.0, "decay_rate": 0.15, "deposit_beta": 0.40, "floor_rate": 0.0},
    {"product": "IAM/LD", "currency": "EUR", "direction": "D", "tier": "core",
     "behavioral_maturity_years": 4.0, "decay_rate": 0.20, "deposit_beta": 0.45, "floor_rate": 0.0},
    {"product": "IAM/LD", "currency": "USD", "direction": "D", "tier": "core",
     "behavioral_maturity_years": 3.0, "decay_rate": 0.25, "deposit_beta": 0.50, "floor_rate": 0.0},
    {"product": "IAM/LD", "currency": "GBP", "direction": "D", "tier": "core",
     "behavioral_maturity_years": 3.0, "decay_rate": 0.25, "deposit_beta": 0.55, "floor_rate": 0.0},
    # Volatile deposits: rate-sensitive, short maturity, high beta
    {"product": "IAM/LD", "currency": "CHF", "direction": "D", "tier": "volatile",
     "behavioral_maturity_years": 1.5, "decay_rate": 0.50, "deposit_beta": 0.80, "floor_rate": 0.0},
    {"product": "IAM/LD", "currency": "EUR", "direction": "D", "tier": "volatile",
     "behavioral_maturity_years": 1.0, "decay_rate": 0.60, "deposit_beta": 0.85, "floor_rate": 0.0},
    # Loans: no NMD treatment (contractual maturity, beta=1.0)
    {"product": "IAM/LD", "currency": "CHF", "direction": "L", "tier": "term",
     "behavioral_maturity_years": 0.0, "decay_rate": 0.0, "deposit_beta": 1.0, "floor_rate": 0.0},
]


# ---------------------------------------------------------------------------
# limits.xlsx — Board-approved NII/EVE limits
# ---------------------------------------------------------------------------

LIMITS_DATA = [
    {"metric": "nii_sensitivity_50bp", "currency": "ALL", "limit_value": 500000, "warning_pct": 80.0, "limit_type": "absolute"},
    {"metric": "nii_at_risk_worst", "currency": "ALL", "limit_value": 1000000, "warning_pct": 75.0, "limit_type": "absolute"},
    {"metric": "eve_change_200bp", "currency": "ALL", "limit_value": 2000000, "warning_pct": 80.0, "limit_type": "absolute"},
    {"metric": "eve_change_worst", "currency": "ALL", "limit_value": 3000000, "warning_pct": 80.0, "limit_type": "absolute"},
    {"metric": "nii_sensitivity_50bp", "currency": "CHF", "limit_value": 300000, "warning_pct": 80.0, "limit_type": "absolute"},
]


ALERT_THRESHOLDS_DATA = [
    {"currency": "ALL", "annual_nii_floor": -100000, "mom_delta_pct": 40.0, "ccy_concentration_pct": 75.0, "shock_sensitivity_limit": 500000},
    {"currency": "CHF", "annual_nii_floor": -50000, "mom_delta_pct": 50.0, "ccy_concentration_pct": 80.0, "shock_sensitivity_limit": 300000},
    {"currency": "EUR", "annual_nii_floor": -30000, "mom_delta_pct": 45.0, "ccy_concentration_pct": 70.0, "shock_sensitivity_limit": 200000},
    {"currency": "USD", "annual_nii_floor": -20000, "mom_delta_pct": 50.0, "ccy_concentration_pct": 60.0, "shock_sensitivity_limit": 150000},
    {"currency": "GBP", "annual_nii_floor": -10000, "mom_delta_pct": 60.0, "ccy_concentration_pct": 50.0, "shock_sensitivity_limit": 100000},
]



# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def generate(output_dir: Path) -> None:
    """Write all 10 ideal-format Excel files to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # deals.xlsx
    deals_df = pd.DataFrame(DEALS_DATA)
    with pd.ExcelWriter(output_dir / "deals.xlsx", engine="openpyxl") as w:
        deals_df.to_excel(w, sheet_name="Deals", index=False)
    print(f"  deals.xlsx       ({len(deals_df)} rows: "
          f"{(deals_df['book']=='BOOK1').sum()} BOOK1, {(deals_df['book']=='BOOK2').sum()} BOOK2)")

    # rate_schedule.xlsx
    schedule_df = pd.DataFrame(SCHEDULE_DATA)
    with pd.ExcelWriter(output_dir / "rate_schedule.xlsx", engine="openpyxl") as w:
        schedule_df.to_excel(w, sheet_name="Schedule", index=False)
    print(f"  rate_schedule.xlsx    ({len(schedule_df)} rows, {len(_MONTHS)} month columns)")

    # wirp.xlsx
    wirp_df = pd.DataFrame(WIRP_DATA)
    with pd.ExcelWriter(output_dir / "wirp.xlsx", engine="openpyxl") as w:
        wirp_df.to_excel(w, sheet_name="WIRP", index=False)
    print(f"  wirp.xlsx        ({len(wirp_df)} rows: "
          f"{wirp_df['index'].nunique()} indices)")

    # reference_table.xlsx
    ref_df = pd.DataFrame(REFERENCE_DATA)
    with pd.ExcelWriter(output_dir / "reference_table.xlsx", engine="openpyxl") as w:
        ref_df.to_excel(w, sheet_name="Reference", index=False)
    print(f"  reference_table  ({len(ref_df)} counterparties)")

    # budget.xlsx
    budget_df = pd.DataFrame(BUDGET_DATA)
    with pd.ExcelWriter(output_dir / "budget.xlsx", engine="openpyxl") as w:
        budget_df.to_excel(w, sheet_name="Budget", index=False)
    print(f"  budget.xlsx      ({len(budget_df)} rows: {budget_df['currency'].nunique()} currencies)")

    # scenarios.xlsx
    scenarios_records = _generate_scenarios_data()
    scenarios_df = pd.DataFrame(scenarios_records)
    with pd.ExcelWriter(output_dir / "scenarios.xlsx", engine="openpyxl") as w:
        scenarios_df.to_excel(w, sheet_name="Scenarios", index=False)
    print(f"  scenarios.xlsx   ({len(scenarios_df)} rows: {scenarios_df['scenario'].nunique()} scenarios)")

    # limits.xlsx
    limits_df = pd.DataFrame(LIMITS_DATA)
    with pd.ExcelWriter(output_dir / "limits.xlsx", engine="openpyxl") as w:
        limits_df.to_excel(w, sheet_name="Limits", index=False)
    print(f"  limits.xlsx      ({len(limits_df)} rows: {limits_df['metric'].nunique()} metrics)")

    # nmd_profiles.xlsx
    nmd_df = pd.DataFrame(NMD_PROFILES_DATA)
    with pd.ExcelWriter(output_dir / "nmd_profiles.xlsx", engine="openpyxl") as w:
        nmd_df.to_excel(w, sheet_name="NMD", index=False)
    print(f"  nmd_profiles.xlsx ({len(nmd_df)} rows: {nmd_df['tier'].nunique()} tiers)")

    # alert_thresholds.xlsx
    at_df = pd.DataFrame(ALERT_THRESHOLDS_DATA)
    with pd.ExcelWriter(output_dir / "alert_thresholds.xlsx", engine="openpyxl") as w:
        at_df.to_excel(w, sheet_name="Thresholds", index=False)
    print(f"  alert_thresholds.xlsx ({len(at_df)} rows: {at_df['currency'].nunique()} currencies)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "ideal_input"
    print(f"Generating mock input files in: {out}")
    generate(out)
    print("Done.")
