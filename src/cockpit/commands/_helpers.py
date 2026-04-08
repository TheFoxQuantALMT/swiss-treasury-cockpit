"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path


def load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist or is corrupt."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        import logging
        logging.getLogger(__name__).warning("Corrupt JSON file %s: %s", path, e)
        return None


def save_json(data: dict, path: Path) -> None:
    """Write a dict as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")
