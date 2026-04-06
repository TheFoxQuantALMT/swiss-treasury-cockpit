"""Decision audit trail — record, load, and query ALCO decisions.

Stores decisions as JSON lines in a date-organized file.
Each decision has: timestamp, topic, description, priority, status, owner.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional


class DecisionStore:
    """Append-only store for ALCO decisions."""

    def __init__(self, store_dir: Path | str):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _file_for_date(self, dt: datetime) -> Path:
        return self.store_dir / f"{dt.strftime('%Y-%m')}_decisions.jsonl"

    def record(
        self,
        topic: str,
        description: str,
        priority: str = "medium",
        owner: str = "",
        status: str = "open",
        date: Optional[datetime] = None,
    ) -> dict:
        """Record a new decision."""
        dt = date or datetime.now()
        entry = {
            "timestamp": dt.isoformat(),
            "date": dt.strftime("%Y-%m-%d"),
            "topic": topic,
            "description": description,
            "priority": priority,
            "owner": owner,
            "status": status,
        }
        path = self._file_for_date(dt)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def load(self, year_month: str | None = None) -> list[dict]:
        """Load decisions, optionally filtered by YYYY-MM."""
        decisions = []
        pattern = f"{year_month}_decisions.jsonl" if year_month else "*_decisions.jsonl"
        for path in sorted(self.store_dir.glob(pattern)):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        decisions.append(json.loads(line))
        return decisions

    def load_recent(self, n: int = 20) -> list[dict]:
        """Load the N most recent decisions across all months."""
        all_decisions = self.load()
        return sorted(all_decisions, key=lambda d: d.get("timestamp", ""), reverse=True)[:n]

    def update_status(self, date: str, topic: str, new_status: str) -> bool:
        """Update the status of a decision (by date + topic match).

        Rewrites the file with the updated entry. Returns True if found and updated.
        """
        for path in self.store_dir.glob("*_decisions.jsonl"):
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            updated = False
            new_lines = []
            for line in lines:
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("date") == date and entry.get("topic") == topic:
                    entry["status"] = new_status
                    updated = True
                new_lines.append(json.dumps(entry))
            if updated:
                path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return True
        return False

    def summary(self) -> dict:
        """Return summary counts by status and priority."""
        decisions = self.load()
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}
        for d in decisions:
            s = d.get("status", "unknown")
            p = d.get("priority", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            by_priority[p] = by_priority.get(p, 0) + 1
        return {
            "total": len(decisions),
            "by_status": by_status,
            "by_priority": by_priority,
        }
