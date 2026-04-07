"""CLI command: compute P&L, scoring, alerts, portfolio snapshot."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR
from cockpit.commands._helpers import load_json, save_json


def cmd_compute(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    funding_source: str = "ois",
) -> None:
    """Run P&L engine, scoring, alerts, and portfolio snapshot."""
    from cockpit.engine.pnl.forecast import ForecastRatePnL
    from cockpit.engine.snapshot import build_portfolio_snapshot
    from cockpit.data.parsers import parse_mtd, parse_echeancier, parse_reference_table

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    # --- P&L ---
    print(f"[compute] Running P&L engine for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt,
        dateRates=date_dt,
        export=False,
        input_dir=input_dir,
        output_dir=str(output_dir),
        funding_source=funding_source,
    )
    pnl.run()
    print("[compute] P&L engine complete.")

    # Save NII forecast snapshot for forecast tracking
    if pnl.pnlAllS is not None and not dry_run:
        try:
            from cockpit.engine.pnl.forecast_tracking import save_nii_forecast
            snapshot_path = save_nii_forecast(pnl.pnlAllS, date, data_dir)
            if snapshot_path:
                print(f"[compute] Saved NII forecast snapshot to {snapshot_path}")
        except Exception as e:
            print(f"[compute] Warning: could not save NII forecast snapshot: {e}")

    # Serialize P&L results to JSON
    pnl_result = {}
    if pnl.pnlAllS is not None:
        months = sorted(pnl.pnlAllS.index.get_level_values("Month").unique().tolist())
        pnl_result["months"] = [str(m) for m in months]
        pnl_result["by_currency"] = {}
        for ccy in pnl.pnlAllS.index.get_level_values("Deal currency").unique():
            ccy_data = pnl.pnlAllS.xs(ccy, level="Deal currency")
            pnl_result["by_currency"][ccy] = {}
            for shock in ccy_data.index.get_level_values("Shock").unique():
                shock_data = ccy_data.xs(shock, level="Shock")
                shock_key = f"shock_{shock}"
                if "PnL_Type" in shock_data.index.names:
                    pnl_result["by_currency"][ccy][shock_key] = {}
                    for pnl_type in shock_data.index.get_level_values("PnL_Type").unique():
                        type_data = shock_data.xs(pnl_type, level="PnL_Type")
                        pnl_result["by_currency"][ccy][shock_key][pnl_type] = (
                            type_data.groupby("Month")["PnL"].sum().tolist()
                        )
                else:
                    pnl_result["by_currency"][ccy][shock_key] = shock_data.groupby("Month")["PnL"].sum().tolist()

    # --- Portfolio Snapshot ---
    print("[compute] Building portfolio snapshot...")
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = load_json(macro_path)
    fx_rates = {}
    if macro_data:
        for pair, key in [("USD", "usd_chf_latest"), ("EUR", "eur_chf_latest"), ("GBP", "gbp_chf_latest")]:
            latest = macro_data.get(key, {})
            if isinstance(latest, dict) and "value" in latest:
                fx_rates[pair] = latest["value"]

    ref_table_path = Path(input_dir) / "reference_table.xlsx" if input_dir else None
    portfolio_result = {}
    if pnl.pnlData is not None and pnl.scheduleData is not None:
        import pandas as pd
        ref_table = parse_reference_table(ref_table_path) if ref_table_path and ref_table_path.exists() else pd.DataFrame(columns=["counterparty", "rating", "hqla_level", "country"])
        portfolio_result = build_portfolio_snapshot(
            echeancier=pnl.scheduleData,
            deals=pnl.pnlData,
            ref_table=ref_table,
            fx_rates=fx_rates,
            ref_date=date_dt.date(),
        )

    # --- Scoring & Alerts ---
    scores_result = {}
    if macro_data:
        print("[compute] Computing scores and alerts...")
        from cockpit.engine.scoring.scoring import compute_scores
        from cockpit.engine.alerts.alerts import check_alerts
        from cockpit.engine.comparison import compute_deltas

        scores = compute_scores(macro_data)
        scores_result = {
            ccy: {
                "composite": s.composite,
                "label": s.label,
                "driver": s.driver,
                "families": {
                    fname: {"score": f.score, "label": f.label, "confidence": f.confidence}
                    for fname, f in s.families.items()
                },
            }
            for ccy, s in scores.items()
        }

        deltas = compute_deltas(macro_data)
        alerts = check_alerts(macro_data, deltas)
        scores_result["_alerts"] = alerts
        scores_result["_deltas"] = deltas

    if not dry_run:
        if pnl_result:
            save_json(pnl_result, data_dir / f"{date}_pnl.json")
            print(f"[compute] Saved P&L to {data_dir / f'{date}_pnl.json'}")
        if portfolio_result:
            save_json(portfolio_result, data_dir / f"{date}_portfolio.json")
            print(f"[compute] Saved portfolio to {data_dir / f'{date}_portfolio.json'}")
        if scores_result:
            save_json(scores_result, data_dir / f"{date}_scores.json")
            print(f"[compute] Saved scores to {data_dir / f'{date}_scores.json'}")
    else:
        print("[compute] Dry run — data not saved.")
