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

from cockpit.config import DATA_DIR, OUTPUT_DIR

# Backward-compatible re-exports for code that imports command functions from cockpit.cli
from cockpit.commands.fetch import cmd_fetch  # noqa: F401
from cockpit.commands.compute import cmd_compute  # noqa: F401
from cockpit.commands.analyze import cmd_analyze  # noqa: F401
from cockpit.commands.render import cmd_render, cmd_render_pnl  # noqa: F401
from cockpit.commands.run_all import cmd_run_all  # noqa: F401
from cockpit.commands.backfill import cmd_backfill  # noqa: F401
from cockpit.commands.validate import cmd_validate  # noqa: F401
from cockpit.commands.what_if import cmd_what_if  # noqa: F401
from cockpit.commands.decision import cmd_decision  # noqa: F401
from cockpit.commands.export import cmd_export_notion  # noqa: F401
from cockpit.commands._helpers import load_json as _load_json, save_json as _save_json  # noqa: F401


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

    # render-pnl
    p_render_pnl = sub.add_parser("render-pnl", help="Render dedicated P&L dashboard")
    p_render_pnl.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_render_pnl.add_argument("--input-dir", help="Path to Excel input files")
    p_render_pnl.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                              help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_render_pnl.add_argument("--budget", dest="budget_file", help="Path to budget.xlsx")
    p_render_pnl.add_argument("--prev-date", help="Previous date for P&L attribution (YYYY-MM-DD)")
    p_render_pnl.add_argument("--prev-input-dir", help="Directory for previous date's Excel inputs (defaults to --input-dir)")
    p_render_pnl.add_argument("--shocks", help="Comma-separated shock list (e.g. '-200,-100,0,50,100,200,wirp') or 'extended' for full grid")
    p_render_pnl.add_argument("--format", choices=["html", "xlsx", "pdf", "all"], default="html",
                              help="Output format: html (default), xlsx, pdf, or all")
    p_render_pnl.add_argument("--custom-scenarios", dest="custom_scenarios",
                              help="Path to custom_scenarios.xlsx for user-defined stress tests")

    # backfill
    p_backfill = sub.add_parser("backfill", help="Run render-pnl for a date range")
    p_backfill.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    p_backfill.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    p_backfill.add_argument("--input-dir", help="Path to Excel input files")
    p_backfill.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # what-if
    p_whatif = sub.add_parser("what-if", help="Simulate adding a hypothetical deal")
    p_whatif.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_whatif.add_argument("--input-dir", required=True, help="Path to Excel input files")
    p_whatif.add_argument("--product", required=True, help="Product type (IAM/LD, BND, IRS)")
    p_whatif.add_argument("--currency", required=True, help="Currency (CHF, EUR, USD, GBP)")
    p_whatif.add_argument("--amount", required=True, type=float, help="Notional amount")
    p_whatif.add_argument("--rate", required=True, type=float, help="Client rate (decimal, e.g. 0.025)")
    p_whatif.add_argument("--direction", default="L", choices=["L", "B", "D", "S"], help="Direction (L=loan, B=bond, D=deposit, S=sell bond)")
    p_whatif.add_argument("--maturity", dest="maturity_years", type=float, default=5.0, help="Maturity in years")
    p_whatif.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # decision
    p_decision = sub.add_parser("decision", help="Record/list/update ALCO decisions")
    p_decision.add_argument("action", choices=["record", "list", "update", "summary"], help="Action to perform")
    p_decision.add_argument("--topic", default="", help="Decision topic")
    p_decision.add_argument("--description", default="", help="Decision description")
    p_decision.add_argument("--priority", choices=["critical", "high", "medium", "low"], default="medium")
    p_decision.add_argument("--owner", default="", help="Decision owner")
    p_decision.add_argument("--status", default="", help="Status for update (open/closed/deferred)")
    p_decision.add_argument("--date", default="", help="Date (YYYY-MM-DD)")
    p_decision.add_argument("--month", default="", help="Filter by YYYY-MM")
    p_decision.add_argument("-n", type=int, default=20, help="Number of recent decisions to list")

    # export-notion
    p_notion = sub.add_parser("export-notion", help="Export ALCO Decision Pack to Notion")
    p_notion.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_notion.add_argument("--input-dir", help="Path to Excel input files")
    p_notion.add_argument("--parent-page-id", default="", help="Notion parent page/database ID")
    p_notion.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # validate
    p_validate = sub.add_parser("validate", help="Validate input Excel files")
    p_validate.add_argument("--input-dir", required=True, help="Path to Excel input files")

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
        from cockpit.commands.fetch import cmd_fetch
        cmd_fetch(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "compute":
        from cockpit.commands.compute import cmd_compute
        cmd_compute(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
    elif args.command == "analyze":
        from cockpit.commands.analyze import cmd_analyze
        cmd_analyze(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "render":
        from cockpit.commands.render import cmd_render
        cmd_render(date=args.date, data_dir=data_dir, output_dir=output_dir)
    elif args.command == "render-pnl":
        from cockpit.commands.render import cmd_render_pnl
        cmd_render_pnl(date=args.date, input_dir=args.input_dir, output_dir=output_dir, funding_source=args.funding_source, budget_file=args.budget_file, prev_date=args.prev_date, prev_input_dir=getattr(args, 'prev_input_dir', None), shocks=getattr(args, 'shocks', None), format=getattr(args, 'format', 'html'), custom_scenarios=getattr(args, 'custom_scenarios', None))
    elif args.command == "backfill":
        from cockpit.commands.backfill import cmd_backfill
        cmd_backfill(from_date=args.from_date, to_date=args.to_date, input_dir=args.input_dir, output_dir=output_dir, funding_source=args.funding_source)
    elif args.command == "what-if":
        from cockpit.commands.what_if import cmd_what_if
        cmd_what_if(input_dir=args.input_dir, date=args.date, product=args.product, currency=args.currency, amount=args.amount, rate=args.rate, direction=args.direction, maturity_years=args.maturity_years, funding_source=args.funding_source)
    elif args.command == "decision":
        from cockpit.commands.decision import cmd_decision
        cmd_decision(action=args.action, topic=args.topic, description=args.description, priority=args.priority, owner=args.owner, status=args.status, date=args.date, month=args.month, n=args.n)
    elif args.command == "export-notion":
        from cockpit.commands.export import cmd_export_notion
        cmd_export_notion(date=args.date, input_dir=getattr(args, 'input_dir', None), parent_page_id=args.parent_page_id, funding_source=args.funding_source)
    elif args.command == "validate":
        from cockpit.commands.validate import cmd_validate
        cmd_validate(input_dir=args.input_dir)
    elif args.command == "run-all":
        from cockpit.commands.run_all import cmd_run_all
        cmd_run_all(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
