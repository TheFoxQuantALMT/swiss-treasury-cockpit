"""Build a mock _pnl_report.xlsx to demonstrate the attribution + new-deals sections.

Useful when WASP is unavailable locally — we can't run the real pipeline with a
previous date, so this script fabricates a realistic ``dashboard_data`` and calls
``export_pnl_report`` so you can open the output and see the full P&L Explain.

Usage:
    uv run python scripts/demo_pnl_report.py [--out PATH]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from cockpit.export.pnl_report import export_pnl_report


def build_mock_dashboard_data(date_run: str, prev_date: str) -> dict:
    """Synthetic dashboard_data with a populated Attribution Waterfall + MTD sheets.

    ``prev_date`` powers the Day-over-Day Attribution Waterfall. The
    Month-over-Month sheet is anchored at 2026-03-31 (hardcoded in the mock).
    """
    # --- Attribution / P&L Explain (the focus of this demo) --------------------
    attribution = {
        "has_data": True,
        "waterfall": [
            {"label": f"Prev NII ({prev_date})", "value": 12_800_000, "type": "base"},
            {"label": "New Deals (+4)", "value": 320_000, "type": "effect"},
            {"label": "Maturing Deals (-3)", "value": -180_000, "type": "effect"},
            {"label": "Rate Effect (\u0394OIS)", "value": 210_000, "type": "effect"},
            {"label": "Spread Effect (\u0394ClientRate)", "value": -45_000, "type": "effect"},
            {"label": "Residual (time / mix / amort.)", "value": -25_000, "type": "effect"},
            {"label": f"Current NII ({date_run})", "value": 13_080_000, "type": "total"},
        ],
        "by_currency": {
            "CHF": {
                "ois_prev": 48.0, "ois_curr": 56.0, "spread_prev": 12.0, "spread_curr": 10.0,
                "existing_prev_pnl": 7_400_000, "existing_curr_pnl": 7_540_000,
                "rate_effect": 140_000, "spread_effect": -30_000, "residual": 30_000,
                "prev_nii": 7_400_000, "curr_nii": 7_540_000, "delta": 140_000,
            },
            "EUR": {
                "ois_prev": 238.0, "ois_curr": 232.0, "spread_prev": 18.0, "spread_curr": 20.0,
                "existing_prev_pnl": 3_900_000, "existing_curr_pnl": 3_950_000,
                "rate_effect": 55_000, "spread_effect": -15_000, "residual": 10_000,
                "prev_nii": 3_900_000, "curr_nii": 3_950_000, "delta": 50_000,
            },
            "USD": {
                "ois_prev": 525.0, "ois_curr": 520.0, "spread_prev": 22.0, "spread_curr": 24.0,
                "existing_prev_pnl": 1_500_000, "existing_curr_pnl": 1_590_000,
                "rate_effect": 15_000, "spread_effect": 0, "residual": 75_000,
                "prev_nii": 1_500_000, "curr_nii": 1_590_000, "delta": 90_000,
            },
        },
        "new_deals": [
            {"deal_id": "304123", "counterparty": "UBS", "currency": "CHF",
             "product": "IAM/LD", "pnl": 185_000, "nominal": 50_000_000},
            {"deal_id": "304155", "counterparty": "Zurich Cantonal",
             "currency": "CHF", "product": "BND", "pnl": 95_000, "nominal": 25_000_000},
            {"deal_id": "304167", "counterparty": "BNP Paribas", "currency": "EUR",
             "product": "IAM/LD", "pnl": 45_000, "nominal": 20_000_000},
            {"deal_id": "304189", "counterparty": "Deutsche Bank", "currency": "USD",
             "product": "BND", "pnl": -5_000, "nominal": 10_000_000},
        ],
        "matured_deals": [
            {"deal_id": "201055", "counterparty": "Credit Suisse", "currency": "CHF",
             "product": "IAM/LD", "pnl_lost": 110_000, "nominal": 30_000_000},
            {"deal_id": "201078", "counterparty": "Raiffeisen", "currency": "CHF",
             "product": "BND", "pnl_lost": 45_000, "nominal": 15_000_000},
            {"deal_id": "201102", "counterparty": "Santander", "currency": "EUR",
             "product": "IAM/LD", "pnl_lost": 25_000, "nominal": 10_000_000},
        ],
        "summary": {
            "prev_nii": 12_800_000, "curr_nii": 13_080_000, "delta": 280_000,
            "new_deal_effect": 320_000, "matured_deal_effect": -180_000,
            "rate_effect": 210_000, "spread_effect": -45_000,
            "residual_effect": -25_000, "time_effect": -25_000,
            "n_new": 4, "n_matured": 3, "n_existing": 287,
            "prev_date": prev_date, "curr_date": date_run,
        },
    }

    # --- Month-over-Month P&L Explain (anchored at last month-end) ------------
    mom_prev_date = "2026-03-31"
    attribution_mom = {
        "has_data": True,
        "waterfall": [
            {"label": f"Prev NII ({mom_prev_date})", "value": 10_200_000, "type": "base"},
            {"label": "New Deals (+27)", "value": 2_150_000, "type": "effect"},
            {"label": "Maturing Deals (-14)", "value": -880_000, "type": "effect"},
            {"label": "Rate Effect (\u0394OIS)", "value": 1_420_000, "type": "effect"},
            {"label": "Spread Effect (\u0394ClientRate)", "value": -310_000, "type": "effect"},
            {"label": "Residual (time / mix / amort.)", "value": 500_000, "type": "effect"},
            {"label": f"Current NII ({date_run})", "value": 13_080_000, "type": "total"},
        ],
        "by_currency": {
            "CHF": {
                "ois_prev": 42.0, "ois_curr": 56.0, "spread_prev": 14.0, "spread_curr": 10.0,
                "existing_prev_pnl": 5_900_000, "existing_curr_pnl": 7_540_000,
                "rate_effect": 950_000, "spread_effect": -210_000, "residual": 900_000,
                "prev_nii": 5_900_000, "curr_nii": 7_540_000, "delta": 1_640_000,
            },
            "EUR": {
                "ois_prev": 245.0, "ois_curr": 232.0, "spread_prev": 16.0, "spread_curr": 20.0,
                "existing_prev_pnl": 3_150_000, "existing_curr_pnl": 3_950_000,
                "rate_effect": 380_000, "spread_effect": -85_000, "residual": 505_000,
                "prev_nii": 3_150_000, "curr_nii": 3_950_000, "delta": 800_000,
            },
            "USD": {
                "ois_prev": 540.0, "ois_curr": 520.0, "spread_prev": 25.0, "spread_curr": 24.0,
                "existing_prev_pnl": 1_150_000, "existing_curr_pnl": 1_590_000,
                "rate_effect": 90_000, "spread_effect": -15_000, "residual": 365_000,
                "prev_nii": 1_150_000, "curr_nii": 1_590_000, "delta": 440_000,
            },
        },
        "new_deals": [
            {"deal_id": "303001", "counterparty": "UBS", "currency": "CHF",
             "product": "IAM/LD", "pnl": 420_000, "nominal": 120_000_000},
            {"deal_id": "303018", "counterparty": "Zurich Cantonal", "currency": "CHF",
             "product": "BND", "pnl": 285_000, "nominal": 75_000_000},
            {"deal_id": "303027", "counterparty": "BNP Paribas", "currency": "EUR",
             "product": "IAM/LD", "pnl": 240_000, "nominal": 80_000_000},
            {"deal_id": "303044", "counterparty": "Raiffeisen", "currency": "CHF",
             "product": "IAM/LD", "pnl": 190_000, "nominal": 60_000_000},
            {"deal_id": "303063", "counterparty": "Santander", "currency": "EUR",
             "product": "BND", "pnl": 165_000, "nominal": 50_000_000},
            {"deal_id": "303091", "counterparty": "JP Morgan", "currency": "USD",
             "product": "IAM/LD", "pnl": 140_000, "nominal": 40_000_000},
            {"deal_id": "303112", "counterparty": "Deutsche Bank", "currency": "EUR",
             "product": "IAM/LD", "pnl": 110_000, "nominal": 35_000_000},
            {"deal_id": "303133", "counterparty": "HSBC", "currency": "USD",
             "product": "BND", "pnl": 95_000, "nominal": 30_000_000},
            {"deal_id": "303155", "counterparty": "PostFinance", "currency": "CHF",
             "product": "BND", "pnl": 80_000, "nominal": 25_000_000},
            {"deal_id": "303178", "counterparty": "Vontobel", "currency": "CHF",
             "product": "IAM/LD", "pnl": 65_000, "nominal": 20_000_000},
        ],
        "matured_deals": [
            {"deal_id": "198042", "counterparty": "Credit Suisse", "currency": "CHF",
             "product": "IAM/LD", "pnl_lost": 220_000, "nominal": 80_000_000},
            {"deal_id": "198065", "counterparty": "Raiffeisen", "currency": "CHF",
             "product": "BND", "pnl_lost": 155_000, "nominal": 50_000_000},
            {"deal_id": "198089", "counterparty": "BNP Paribas", "currency": "EUR",
             "product": "IAM/LD", "pnl_lost": 120_000, "nominal": 45_000_000},
            {"deal_id": "198114", "counterparty": "Deutsche Bank", "currency": "USD",
             "product": "BND", "pnl_lost": 95_000, "nominal": 30_000_000},
            {"deal_id": "198138", "counterparty": "Santander", "currency": "EUR",
             "product": "IAM/LD", "pnl_lost": 80_000, "nominal": 25_000_000},
            {"deal_id": "198160", "counterparty": "HSBC", "currency": "USD",
             "product": "BND", "pnl_lost": 55_000, "nominal": 18_000_000},
            {"deal_id": "198182", "counterparty": "Zurich Cantonal", "currency": "CHF",
             "product": "IAM/LD", "pnl_lost": 40_000, "nominal": 15_000_000},
        ],
        "summary": {
            "prev_nii": 10_200_000, "curr_nii": 13_080_000, "delta": 2_880_000,
            "new_deal_effect": 2_150_000, "matured_deal_effect": -880_000,
            "rate_effect": 1_420_000, "spread_effect": -310_000,
            "residual_effect": 500_000, "time_effect": 500_000,
            "n_new": 27, "n_matured": 14, "n_existing": 260,
            "prev_date": mom_prev_date, "curr_date": date_run,
        },
    }

    # --- Supporting data to keep other sheets informative ---------------------
    dates = pd.date_range(date_run, "2026-04-30", freq="D")
    daily_central = pd.DataFrame([
        {"Date": d, "Currency": c, "PnL_Daily": 42_000 if c == "CHF" else 18_000}
        for d in dates for c in ("CHF", "EUR", "USD")
    ])
    daily_wirp = pd.DataFrame([
        {"Date": d, "Currency": c, "PnL_Daily": 44_500 if c == "CHF" else 19_200}
        for d in dates for c in ("CHF", "EUR", "USD")
    ])

    summary = {
        "kpis": {"shock_0": {"total": 13_080_000, "CHF": 7_540_000, "EUR": 3_950_000, "USD": 1_590_000}},
        "dod_bridge": [
            {"currency": "CHF", "previous": 7_400_000, "current": 7_540_000, "delta": 140_000},
            {"currency": "EUR", "previous": 3_900_000, "current": 3_950_000, "delta": 50_000},
            {"currency": "USD", "previous": 1_500_000, "current": 1_590_000, "delta": 90_000},
            {"currency": "Total", "previous": 12_800_000, "current": 13_080_000, "delta": 280_000},
        ],
    }

    return {
        "summary": summary,
        "attribution": attribution,
        "attribution_mom": attribution_mom,
        "daily_projection": {
            "has_data": True, "central": daily_central, "wirp": daily_wirp,
            "start_date": date_run, "end_date": "2026-04-30",
        },
        "realized_daily_pnl": {
            "has_data": True, "date_run": date_run,
            "rows": [],
            "pivot": pd.DataFrame([
                {"currency": "CHF", "BOOK1 Accrual (PnL_Acc_Adj)": 42_000.0,
                 "BOOK1 Realized (PnL_IAS)": 8_000.0, "BOOK2 Realized (PnL_MTM)": -1_500.0},
                {"currency": "EUR", "BOOK1 Accrual (PnL_Acc_Adj)": 18_000.0,
                 "BOOK1 Realized (PnL_IAS)": 3_000.0, "BOOK2 Realized (PnL_MTM)": 800.0},
                {"currency": "USD", "BOOK1 Accrual (PnL_Acc_Adj)": 6_500.0,
                 "BOOK1 Realized (PnL_IAS)": 1_200.0, "BOOK2 Realized (PnL_MTM)": 0.0},
            ]),
        },
        "book1_realized_mtd": {
            "has_data": True, "month_start": "2026-04-01", "date_run": date_run,
            "days_counted": 13,
            "rows": [
                {"currency": "CHF", "book1_accrual": 546_000, "book1_ias": 104_000,
                 "book2_mtm": -19_500, "book1_total": 650_000},
                {"currency": "EUR", "book1_accrual": 234_000, "book1_ias": 39_000,
                 "book2_mtm": 10_400, "book1_total": 273_000},
                {"currency": "USD", "book1_accrual": 84_500, "book1_ias": 15_600,
                 "book2_mtm": 0, "book1_total": 100_100},
            ],
            "totals": {"book1_accrual": 864_500, "book1_ias": 158_600,
                       "book2_mtm": -9_100, "book1_total": 1_023_100},
        },
        "book2_delta_dod": {
            "has_data": True, "prev_date": prev_date,
            "rows": [
                {"currency": "CHF", "n_deals": 18, "mtm_today": 1_250_000,
                 "mtm_prev": 1_230_000, "delta": 20_000},
                {"currency": "EUR", "n_deals": 12, "mtm_today": -380_000,
                 "mtm_prev": -365_000, "delta": -15_000},
            ],
            "totals": {"mtm_today": 870_000, "mtm_prev": 865_000, "delta": 5_000},
        },
        "book2_delta_mtd": {
            "has_data": True, "prev_date": "2026-03-31",
            "rows": [
                {"currency": "CHF", "n_deals": 18, "mtm_today": 1_250_000,
                 "mtm_prev": 1_100_000, "delta": 150_000},
                {"currency": "EUR", "n_deals": 12, "mtm_today": -380_000,
                 "mtm_prev": -425_000, "delta": 45_000},
            ],
            "totals": {"mtm_today": 870_000, "mtm_prev": 675_000, "delta": 195_000},
        },
        "strategy_consolidated": {
            "has_data": True,
            "summary": {"n_total": 3, "n_ok": 2, "n_under": 1, "n_over": 0, "n_na": 0, "n_multi_ccy": 0},
            "rows": [
                {"strategy_ias": "S_CHF_FVH1", "hedge_type": "FVH", "currencies": "CHF",
                 "multi_currency": False, "n_hedged": 1, "n_hedging": 1, "n_hedging_book2": 1,
                 "hedged_clean_fv_today": 25_000_000, "hedged_clean_dFV": -180_000,
                 "hedging_irs_mtm_today": 620_000, "hedging_irs_dMtM": 175_000,
                 "effectiveness_ratio": 0.972, "corridor_flag": "ok"},
                {"strategy_ias": "S_EUR_FVH1", "hedge_type": "FVH", "currencies": "EUR",
                 "multi_currency": False, "n_hedged": 1, "n_hedging": 1, "n_hedging_book2": 1,
                 "hedged_clean_fv_today": 15_000_000, "hedged_clean_dFV": -95_000,
                 "hedging_irs_mtm_today": 280_000, "hedging_irs_dMtM": 88_000,
                 "effectiveness_ratio": 0.926, "corridor_flag": "ok"},
                {"strategy_ias": "S_USD_FVH1", "hedge_type": "FVH", "currencies": "USD",
                 "multi_currency": False, "n_hedged": 1, "n_hedging": 1, "n_hedging_book2": 1,
                 "hedged_clean_fv_today": 10_000_000, "hedged_clean_dFV": -200_000,
                 "hedging_irs_mtm_today": 150_000, "hedging_irs_dMtM": 110_000,
                 "effectiveness_ratio": 0.550, "corridor_flag": "under"},
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="tmp/mock_pnl_report.xlsx", help="Output xlsx path")
    parser.add_argument("--date", default="2026-04-18", help="Mock date_run (YYYY-MM-DD)")
    parser.add_argument("--prev-date", default="2026-04-17",
                        help="Mock previous run date (powers P&L Explain)")
    args = parser.parse_args()

    data = build_mock_dashboard_data(args.date, args.prev_date)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    result = export_pnl_report(data, out_path, args.date)
    if result:
        print(f"Wrote {result.resolve()}")
    else:
        raise SystemExit("export_pnl_report returned no path")


if __name__ == "__main__":
    main()
