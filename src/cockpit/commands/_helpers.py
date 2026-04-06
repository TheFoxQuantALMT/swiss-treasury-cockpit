"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_json(data: dict, path: Path) -> None:
    """Write a dict as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
