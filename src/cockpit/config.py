"""Unified configuration for Swiss Treasury Cockpit.

Merges constants from pnl_engine (P&L engine) and macro-cbwatch (CB monitoring).
P&L-specific constants are re-exported from the standalone pnl_engine package.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Re-export P&L engine constants from standalone package
# ---------------------------------------------------------------------------

from pnl_engine.config import (  # noqa: F401
    CURRENCY_TO_CARRY_INDEX,
    CURRENCY_TO_OIS,
    ECHEANCIER_INDEX_TO_WASP,
    FLOAT_NAME_TO_WASP,
    FUNDING_SOURCE,
    LOOKBACK_DAYS,
    MM_BY_CURRENCY,
    NON_STRATEGY_PRODUCTS,
    PRODUCT_RATE_COLUMN,
    SHOCKS,
    SUPPORTED_CURRENCIES,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

# ---------------------------------------------------------------------------
# Exposure module constants (from economic-pnl config.py)
# ---------------------------------------------------------------------------

LIQUIDITY_BUCKETS: list[tuple[str, int | None, int | None]] = [
    ("O/N", 0, 0),
    ("D+1", 1, 1),
    ("D+2", 2, 2),
    ("D+3", 3, 3),
    ("D+4", 4, 4),
    ("D+5", 5, 5),
    ("D+6", 6, 6),
    ("D+7", 7, 7),
    ("D+8", 8, 8),
    ("D+9", 9, 9),
    ("D+10", 10, 10),
    ("D+11", 11, 11),
    ("D+12", 12, 12),
    ("D+13", 13, 13),
    ("D+14", 14, 14),
    ("D+15", 15, 15),
    ("16-30d", 16, 30),
    ("1-3M", 31, 90),
    ("3-6M", 91, 180),
    ("6-12M", 181, 365),
    ("1-2Y", 366, 730),
    ("2-5Y", 731, 1825),
    ("5Y+", 1826, None),
    ("Undefined", None, None),
]

RATING_BUCKETS: dict[str, list[str]] = {
    "AAA-AA": ["AAA", "AA+", "AA", "AA-"],
    "A": ["A+", "A", "A-"],
    "BBB": ["BBB+", "BBB", "BBB-"],
    "Sub-IG": ["BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C", "D"],
    "NR": ["NR"],
}

HQLA_LEVELS: list[str] = ["L1", "L2A", "L2B", "Non-HQLA"]

CURRENCY_CLASSES: list[str] = ["Total", "CHF", "USD", "EUR", "GBP", "Others"]

CDS_ALERT_THRESHOLD_BPS: int = 200

# ---------------------------------------------------------------------------
# Counterparty perimeters (from economic-pnl config.py)
# ---------------------------------------------------------------------------

_WM_COUNTERPARTIES: set[str] = {
    "THCCBFIGE", "BKCCBFIGE", "THCCBZIWE", "WCCCBFIGE", "THCCHFIGE",
}

_CIB_COUNTERPARTIES: set[str] = {
    "CLI-MT-CIB", "CPFNCLI", "CLI-FI-CIB",
}

# ---------------------------------------------------------------------------
# Macro monitoring constants (from cbwatch config.yaml)
# ---------------------------------------------------------------------------

FX_ALERT_BANDS: dict[str, dict[str, float]] = {
    "EUR_CHF": {"low": 0.90, "high": 0.96},
    "USD_CHF": {"low": 0.78, "high": 0.85},
    "GBP_CHF": {"low": 1.08, "high": 1.16},
}

ENERGY_THRESHOLDS: dict[str, float] = {
    "brent_high": 120.0,
    "brent_low": 65.0,
    "eu_gas_high": 80.0,
}

DEPOSIT_THRESHOLDS: dict[str, float] = {
    "weekly_change_threshold_bln": 2.0,
}

DAILY_MOVE_THRESHOLDS: dict[str, float] = {
    "brent_pct": 5.0,
    "eu_gas_pct": 5.0,
    "fx_pct": 1.0,
    "vix_pct": 10.0,
}

SCORING_LABELS: dict[str, int] = {
    "calm_max": 45,
    "watch_max": 70,
}

SCENARIOS: dict[str, dict] = {
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
}

# ---------------------------------------------------------------------------
# LLM models (from cbwatch config.yaml)
# ---------------------------------------------------------------------------

ANALYST_MODEL: str = "deepseek-r1:14b"
REVIEWER_MODEL: str = "qwen3.5:9b"
OLLAMA_HOST: str = "http://localhost:11434"
MAX_REVIEW_RETRIES: int = 3
