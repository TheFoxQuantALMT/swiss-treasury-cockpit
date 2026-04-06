"""CLI command: backfill date range."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cockpit.config import OUTPUT_DIR


def cmd_backfill(
    *,
    from_date: str,
    to_date: str,
    input_dir: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    funding_source: str = "ois",
) -> None:
    """Run render-pnl for a date range to populate KPI history and trends."""
    from datetime import timedelta
    from cockpit.calendar import is_business_day
    from cockpit.commands.render import cmd_render_pnl

    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")
    current = start
    n_ok = 0
    n_fail = 0

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        if not is_business_day(current):
            print(f"[backfill] Skipping {date_str} (not a business day)")
            current += timedelta(days=1)
            continue
        print(f"\n[backfill] === {date_str} ===")
        try:
            cmd_render_pnl(
                date=date_str,
                input_dir=input_dir,
                output_dir=output_dir,
                funding_source=funding_source,
            )
            n_ok += 1
        except Exception as e:
            print(f"[backfill] FAILED {date_str}: {e}")
            n_fail += 1
        current += timedelta(days=1)

    print(f"\n[backfill] Done: {n_ok} succeeded, {n_fail} failed")
