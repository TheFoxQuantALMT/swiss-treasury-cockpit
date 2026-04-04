"""CLI entry points for Swiss Treasury Cockpit.

Commands:
    cockpit fetch     — Fetch macro data (FRED, ECB, SNB, yfinance)
    cockpit compute   — Run P&L engine + scoring + alerts + portfolio snapshot
    cockpit analyze   — Generate LLM daily brief (requires Ollama)
    cockpit render    — Render HTML cockpit from available data
    cockpit run-all   — Execute all steps in sequence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_json(data: dict, path: Path) -> None:
    """Write a dict as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def cmd_fetch(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Fetch macro data from FRED, ECB, SNB, yfinance."""
    from cockpit.data.manager import DataManager

    print(f"[fetch] Fetching macro data for {date}...")
    dm = DataManager()
    results = asyncio.run(dm.refresh_all_data())

    if not dry_run:
        output_path = data_dir / f"{date}_macro_snapshot.json"
        _save_json(results, output_path)
        print(f"[fetch] Saved to {output_path}")

        stale = results.get("stale", [])
        if stale:
            print(f"[fetch] Warning: stale sources: {', '.join(stale)}")
    else:
        print("[fetch] Dry run — data not saved.")


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
                pnl_result["by_currency"][ccy][f"shock_{shock}"] = shock_data.groupby("Month")["PnL"].sum().tolist()

    # --- Portfolio Snapshot ---
    print("[compute] Building portfolio snapshot...")
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
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
            _save_json(pnl_result, data_dir / f"{date}_pnl.json")
            print(f"[compute] Saved P&L to {data_dir / f'{date}_pnl.json'}")
        if portfolio_result:
            _save_json(portfolio_result, data_dir / f"{date}_portfolio.json")
            print(f"[compute] Saved portfolio to {data_dir / f'{date}_portfolio.json'}")
        if scores_result:
            _save_json(scores_result, data_dir / f"{date}_scores.json")
            print(f"[compute] Saved scores to {data_dir / f'{date}_scores.json'}")
    else:
        print("[compute] Dry run — data not saved.")


def cmd_analyze(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Generate LLM daily brief using Ollama agents."""
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
    if macro_data is None:
        print(f"[analyze] Error: {macro_path} not found. Run 'cockpit fetch' first.")
        sys.exit(1)

    scores_path = data_dir / f"{date}_scores.json"
    scores_data = _load_json(scores_path) or {}

    from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief
    from cockpit.engine.alerts.alerts import check_alerts
    from cockpit.agents.analyst import _build_template, create_analyst_agent
    from cockpit.agents.reviewer import programmatic_check, create_reviewer_agent
    from cockpit.agents.reporter import generate_html_brief
    from cockpit.config import MAX_REVIEW_RETRIES

    deltas = scores_data.get("_deltas", compute_deltas(macro_data))
    alerts = scores_data.get("_alerts", check_alerts(macro_data, deltas))
    delta_table = format_deltas_for_brief(deltas)

    print(f"[analyze] Building analyst template for {date}...")
    template = _build_template(macro_data, deltas, delta_table, alerts)

    print("[analyze] Running analyst agent...")
    analyst = create_analyst_agent()
    brief_text = asyncio.run(analyst.run(template))

    print("[analyze] Running reviewer agent...")
    reviewer = create_reviewer_agent()
    reviewed = False
    for attempt in range(MAX_REVIEW_RETRIES):
        errors = programmatic_check(brief_text, macro_data)
        if not errors:
            reviewed = True
            break
        print(f"[analyze] Review attempt {attempt + 1}: {len(errors)} issues found, retrying...")
        brief_text = asyncio.run(analyst.run(template))

    brief_html = generate_html_brief(brief_text, macro_data, deltas)

    result = {
        "date": date,
        "reviewed": reviewed,
        "html": brief_html,
        "text": brief_text,
    }

    if not dry_run:
        output_path = data_dir / f"{date}_brief.json"
        _save_json(result, output_path)
        print(f"[analyze] Saved brief to {output_path}")
    else:
        print("[analyze] Dry run — brief not saved.")


def cmd_render(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Render HTML cockpit from available JSON intermediates."""
    from cockpit.render.renderer import render_cockpit

    macro_data = _load_json(data_dir / f"{date}_macro_snapshot.json")
    pnl_data = _load_json(data_dir / f"{date}_pnl.json")
    portfolio_data = _load_json(data_dir / f"{date}_portfolio.json")
    scores_data = _load_json(data_dir / f"{date}_scores.json")
    brief_data = _load_json(data_dir / f"{date}_brief.json")

    output_path = output_dir / f"{date}_cockpit.html"

    print(f"[render] Rendering cockpit for {date}...")
    available = []
    if macro_data:
        available.append("macro")
    if pnl_data:
        available.append("pnl")
    if portfolio_data:
        available.append("portfolio")
    if scores_data:
        available.append("scores")
    if brief_data:
        available.append("brief")
    print(f"[render] Available data: {', '.join(available) or 'none'}")

    render_cockpit(
        macro_data=macro_data,
        pnl_data=pnl_data,
        portfolio_data=portfolio_data,
        scores_data=scores_data,
        brief_data=brief_data,
        date=date,
        output_path=output_path,
    )
    print(f"[render] Output: {output_path}")


def cmd_run_all(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    funding_source: str = "ois",
) -> None:
    """Execute all pipeline steps in sequence."""
    cmd_fetch(date=date, data_dir=data_dir, dry_run=dry_run)
    cmd_compute(date=date, input_dir=input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=dry_run, funding_source=funding_source)
    try:
        cmd_analyze(date=date, data_dir=data_dir, dry_run=dry_run)
    except Exception as e:
        print(f"[run-all] Analyze step failed (Ollama may be unavailable): {e}")
        print("[run-all] Continuing without daily brief...")
    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cockpit",
        description="Swiss Treasury Cockpit — unified dashboard pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch macro data")
    p_fetch.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_fetch.add_argument("--dry-run", action="store_true")

    # compute
    p_compute = sub.add_parser("compute", help="Run P&L + scoring + alerts + portfolio")
    p_compute.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_compute.add_argument("--input-dir", help="Path to Excel input files")
    p_compute.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                           help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_compute.add_argument("--dry-run", action="store_true")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Generate LLM daily brief")
    p_analyze.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_analyze.add_argument("--dry-run", action="store_true")

    # render
    p_render = sub.add_parser("render", help="Render HTML cockpit")
    p_render.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")

    # run-all
    p_all = sub.add_parser("run-all", help="Execute all steps")
    p_all.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_all.add_argument("--input-dir", help="Path to Excel input files")
    p_all.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                       help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_all.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    data_dir = DATA_DIR
    output_dir = OUTPUT_DIR

    if args.command == "fetch":
        cmd_fetch(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "compute":
        cmd_compute(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
    elif args.command == "analyze":
        cmd_analyze(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "render":
        cmd_render(date=args.date, data_dir=data_dir, output_dir=output_dir)
    elif args.command == "run-all":
        cmd_run_all(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
