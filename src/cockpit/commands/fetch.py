"""CLI command: fetch macro data."""

from __future__ import annotations

import asyncio
from pathlib import Path

from cockpit.config import DATA_DIR
from cockpit.commands._helpers import save_json


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
        save_json(results, output_path)
        print(f"[fetch] Saved to {output_path}")

        stale = results.get("stale", [])
        if stale:
            print(f"[fetch] Warning: stale sources: {', '.join(stale)}")
    else:
        print("[fetch] Dry run — data not saved.")
