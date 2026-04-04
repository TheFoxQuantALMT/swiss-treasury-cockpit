"""Unified configuration for Swiss Treasury Cockpit.

Merges constants from economic-pnl (P&L engine) and macro-cbwatch (CB monitoring).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

# ---------------------------------------------------------------------------
# P&L Engine constants (from economic-pnl config.py)
# ---------------------------------------------------------------------------

CURRENCY_TO_OIS: dict[str, str] = {
    "CHF": "CHFSON",
    "EUR": "EUREST",
    "USD": "USSOFR",
    "GBP": "GBPOIS",
}

PRODUCT_RATE_COLUMN: dict[str, str] = {
    "IAM/LD": "EqOisRate",
    "BND": "YTM",
    "FXS": "EqOisRate",
    "IRS": "Clientrate",
    "IRS-MTM": "Clientrate",
    "HCD": "Clientrate",
}

NON_STRATEGY_PRODUCTS: set[str] = {"BND", "FXS", "IAM/LD", "IRS", "IRS-MTM"}

SUPPORTED_CURRENCIES: set[str] = {"CHF", "EUR", "USD", "GBP"}

MM_BY_CURRENCY: dict[str, int] = {
    "CHF": 360,
    "EUR": 360,
    "USD": 360,
    "GBP": 365,
}

ECHEANCIER_INDEX_TO_WASP: dict[str, dict[str, str]] = {
    "3M": {"CHF": "CHFSON3M", "EUR": "EUREST3M", "USD": "USSOFR3M", "GBP": "GBPOIS3M"},
    "6M": {"CHF": "CHFSON6M", "EUR": "EUREST6M", "USD": "USSOFR6M", "GBP": "GBPOIS6M"},
    "1M": {"CHF": "CHFSON1M", "EUR": "EUREST1M", "USD": "USSOFR1M", "GBP": "GBPOIS1M"},
}

FLOAT_NAME_TO_WASP: dict[str, str] = {
    "SARON": "CHFSON",
    "ESTR": "EUREST",
    "SOFR": "USSOFR",
    "SONIA": "GBPOIS",
}

SHOCKS: list[str] = ["0", "50", "wirp"]

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

# ---------------------------------------------------------------------------
# Cost of Carry / P&L decomposition
# ---------------------------------------------------------------------------

FUNDING_SOURCE: str = "ois"  # "ois" (default) or "coc"

# WASP carry-compounded curve indices (from wasptools.py)
# These differ from OIS forward indices for EUR and CHF
CURRENCY_TO_CARRY_INDEX: dict[str, str] = {
    "CHF": "CSCML5",
    "EUR": "ESAVB1",
    "USD": "USSOFR",
    "GBP": "GBPOIS",
}

# RFR lookback in business days (SNB WG: SARON=2, BoE WG: SONIA=5)
LOOKBACK_DAYS: dict[str, int] = {
    "CHF": 2,
    "GBP": 5,
}
