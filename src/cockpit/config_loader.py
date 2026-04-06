"""Load runtime configuration from YAML, falling back to built-in defaults.

Usage::

    from cockpit.config_loader import load_config
    cfg = load_config()          # auto-discovers config/cockpit.config.yaml
    cfg["fx_alert_bands"]["EUR_CHF"]["low"]  # → 0.90
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "config" / "cockpit.config.yaml"

# Built-in defaults (same values as hardcoded in config.py).
# Every key that can appear in the YAML must have a default here.
DEFAULTS: dict[str, Any] = {
    "fx_alert_bands": {
        "EUR_CHF": {"low": 0.90, "high": 0.96},
        "USD_CHF": {"low": 0.78, "high": 0.85},
        "GBP_CHF": {"low": 1.08, "high": 1.16},
    },
    "energy_thresholds": {
        "brent_high": 120.0,
        "brent_low": 65.0,
        "eu_gas_high": 80.0,
    },
    "deposit_thresholds": {
        "weekly_change_threshold_bln": 2.0,
    },
    "daily_move_thresholds": {
        "brent_pct": 5.0,
        "eu_gas_pct": 5.0,
        "fx_pct": 1.0,
        "vix_pct": 10.0,
    },
    "scoring_labels": {
        "calm_max": 45,
        "watch_max": 70,
    },
    "cds_alert_threshold_bps": 200,
    "scenarios": {
        "ceasefire_rapid": {
            "probability": 0.30,
            "brent_target": 65,
            "usd_chf_range": [0.82, 0.84],
            "eur_chf_range": [0.92, 0.94],
        },
        "conflict_contained": {
            "probability": 0.45,
            "brent_target": [100, 120],
            "usd_chf_range": [0.79, 0.82],
            "eur_chf_range": [0.90, 0.93],
        },
        "escalation_major": {
            "probability": 0.25,
            "brent_target": [130, 150],
            "usd_chf_range": [0.75, 0.78],
            "eur_chf_range": [0.88, 0.91],
        },
    },
    "analyst_model": "deepseek-r1:14b",
    "reviewer_model": "qwen3.5:9b",
    "ollama_host": "http://localhost:11434",
    "max_review_retries": 3,
    "shocks": ["0", "50", "wirp"],
}

_cached_config: dict[str, Any] | None = None


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (non-destructive)."""
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | str | None = None, *, use_cache: bool = True) -> dict[str, Any]:
    """Load configuration from YAML, merged over built-in defaults.

    Parameters
    ----------
    path : Path or str, optional
        Path to the YAML config file. Defaults to ``config/cockpit.config.yaml``
        relative to the project root. If the file does not exist, returns defaults.
    use_cache : bool
        If *True* (default), re-use a previously loaded config for the same
        default path. Pass *False* to force a re-read (useful in tests).
    """
    global _cached_config

    if path is None:
        resolved = DEFAULT_CONFIG_PATH
    else:
        resolved = Path(path)

    if use_cache and _cached_config is not None and path is None:
        return _cached_config

    if resolved.exists():
        try:
            with open(resolved, encoding="utf-8") as fh:
                user_cfg = yaml.safe_load(fh) or {}
        except yaml.YAMLError as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Malformed config YAML at %s, falling back to defaults: %s", resolved, exc,
            )
            user_cfg = {}
    else:
        user_cfg = {}

    merged = _deep_merge(DEFAULTS, user_cfg)

    if path is None:
        _cached_config = merged

    return merged


def reset_cache() -> None:
    """Clear the cached config (for testing)."""
    global _cached_config
    _cached_config = None
