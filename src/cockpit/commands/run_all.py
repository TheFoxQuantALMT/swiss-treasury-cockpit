"""CLI command: run all pipeline steps."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR


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
    from cockpit.calendar import is_business_day
    from cockpit.commands.fetch import cmd_fetch
    from cockpit.commands.compute import cmd_compute
    from cockpit.commands.analyze import cmd_analyze
    from cockpit.commands.render import cmd_render, cmd_render_pnl

    run_date = datetime.strptime(date, "%Y-%m-%d")
    if not is_business_day(run_date):
        print(f"[run-all] WARNING: {date} is not a Swiss business day (weekend or holiday).")

    cmd_fetch(date=date, data_dir=data_dir, dry_run=dry_run)
    cmd_compute(date=date, input_dir=input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=dry_run, funding_source=funding_source)

    analyze_ok = False
    try:
        cmd_analyze(date=date, data_dir=data_dir, dry_run=dry_run)
        analyze_ok = True
    except SystemExit:
        print("[run-all] WARNING: Analyze step exited (macro snapshot may be missing).")
        print("[run-all] Continuing without daily brief...")
    except Exception as e:
        print(f"[run-all] WARNING: Analyze step failed (Ollama may be unavailable): {e}")
        print("[run-all] Continuing without daily brief...")

    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    # Also render dedicated P&L dashboard if input_dir provided
    if input_dir:
        try:
            cmd_render_pnl(date=date, input_dir=input_dir, output_dir=output_dir, funding_source=funding_source)
        except Exception as e:
            print(f"[run-all] WARNING: P&L dashboard render failed: {e}")

    if not analyze_ok:
        print("[run-all] Completed with warnings (analyze step failed).")
