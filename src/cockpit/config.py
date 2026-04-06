"""Unified configuration for Swiss Treasury Cockpit.

Merges constants from pnl_engine (P&L engine) and macro-cbwatch (CB monitoring).
P&L-specific constants are re-exported from the standalone pnl_engine package.
Runtime-tunable values are loaded from ``config/cockpit.config.yaml`` via
:func:`cockpit.config_loader.load_config`.
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

from cockpit.config_loader import load_config

_CFG = load_config()

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
# Macro monitoring constants — loaded from config/cockpit.config.yaml
# ---------------------------------------------------------------------------

FX_ALERT_BANDS: dict[str, dict[str, float]] = _CFG["fx_alert_bands"]
ENERGY_THRESHOLDS: dict[str, float] = _CFG["energy_thresholds"]
DEPOSIT_THRESHOLDS: dict[str, float] = _CFG["deposit_thresholds"]
DAILY_MOVE_THRESHOLDS: dict[str, float] = _CFG["daily_move_thresholds"]
SCORING_LABELS: dict[str, int] = _CFG["scoring_labels"]
CDS_ALERT_THRESHOLD_BPS: int = _CFG["cds_alert_threshold_bps"]
SCENARIOS: dict[str, dict] = _CFG["scenarios"]

# ---------------------------------------------------------------------------
# LLM models — loaded from config/cockpit.config.yaml
# ---------------------------------------------------------------------------

ANALYST_MODEL: str = _CFG["analyst_model"]
REVIEWER_MODEL: str = _CFG["reviewer_model"]
OLLAMA_HOST: str = _CFG["ollama_host"]
MAX_REVIEW_RETRIES: int = _CFG["max_review_retries"]
