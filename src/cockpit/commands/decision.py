"""CLI command: ALCO decision management."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from cockpit.config import DATA_DIR


def cmd_decision(
    *,
    action: str,
    topic: str = "",
    description: str = "",
    priority: str = "medium",
    owner: str = "",
    status: str = "",
    date: str = "",
    month: str = "",
    n: int = 20,
) -> None:
    """Record, list, or update ALCO decisions."""
    from cockpit.decisions import DecisionStore

    store = DecisionStore(DATA_DIR / "decisions")

    if action == "record":
        if not topic:
            print("[decision] Error: --topic is required for recording")
            sys.exit(1)
        try:
            dt = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
        except ValueError:
            print(f"[decision] Error: invalid date format '{date}', expected YYYY-MM-DD")
            sys.exit(1)
        entry = store.record(
            topic=topic,
            description=description,
            priority=priority,
            owner=owner,
            date=dt,
        )
        print(f"[decision] Recorded: {entry['topic']} ({entry['priority']}) on {entry['date']}")

    elif action == "list":
        if month:
            decisions = store.load(year_month=month)
        else:
            decisions = store.load_recent(n=n)
        if not decisions:
            print("[decision] No decisions found.")
            return
        for d in decisions:
            status_str = f"[{d.get('status', '?')}]"
            print(f"  {d['date']}  {status_str:<10}  {d.get('priority', '?'):<8}  {d['topic']}: {d.get('description', '')[:60]}")
        print(f"\n[decision] {len(decisions)} decision(s)")

    elif action == "update":
        if not topic or not date or not status:
            print("[decision] Error: --topic, --date, and --status required for update")
            sys.exit(1)
        ok = store.update_status(date, topic, status)
        if ok:
            print(f"[decision] Updated: {topic} on {date} -> {status}")
        else:
            print(f"[decision] Not found: {topic} on {date}")

    elif action == "summary":
        s = store.summary()
        print(f"[decision] Total: {s['total']}")
        for k, v in s.get("by_status", {}).items():
            print(f"  {k}: {v}")

    else:
        print(f"[decision] Unknown action: {action}. Use record, list, update, or summary.")
