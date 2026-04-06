"""P&L engine constants — standalone, no cockpit dependency.

These constants define the mapping between currencies, products, and market
conventions used by the vectorized P&L computation engine.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Currency → OIS index mapping (WASP naming convention)
# ---------------------------------------------------------------------------

CURRENCY_TO_OIS: dict[str, str] = {
    "CHF": "CHFSON",
    "EUR": "EUREST",
    "USD": "USSOFR",
    "GBP": "GBPOIS",
}

# ---------------------------------------------------------------------------
# Product → rate column used as RateRef in daily P&L
# ---------------------------------------------------------------------------

PRODUCT_RATE_COLUMN: dict[str, str] = {
    "IAM/LD": "EqOisRate",
    "BND": "YTM",
    "FXS": "EqOisRate",
    "IRS": "Clientrate",
    "IRS-MTM": "Clientrate",
    "HCD": "Clientrate",
}

# ---------------------------------------------------------------------------
# Products that do NOT go through the IAS strategy decomposition path
# ---------------------------------------------------------------------------

NON_STRATEGY_PRODUCTS: set[str] = {"BND", "FXS", "IAM/LD", "IRS", "IRS-MTM"}

# ---------------------------------------------------------------------------
# Supported currencies
# ---------------------------------------------------------------------------

SUPPORTED_CURRENCIES: set[str] = {"CHF", "EUR", "USD", "GBP"}

# ---------------------------------------------------------------------------
# Day count divisor per currency (ISDA 2006 §4.16)
# ---------------------------------------------------------------------------

MM_BY_CURRENCY: dict[str, int] = {
    "CHF": 360,
    "EUR": 360,
    "USD": 360,
    "GBP": 365,
}

# ---------------------------------------------------------------------------
# Echeancier tenor → WASP index mapping
# ---------------------------------------------------------------------------

ECHEANCIER_INDEX_TO_WASP: dict[str, dict[str, str]] = {
    "3M": {"CHF": "CHFSON3M", "EUR": "EUREST3M", "USD": "USSOFR3M", "GBP": "GBPOIS3M"},
    "6M": {"CHF": "CHFSON6M", "EUR": "EUREST6M", "USD": "USSOFR6M", "GBP": "GBPOIS6M"},
    "1M": {"CHF": "CHFSON1M", "EUR": "EUREST1M", "USD": "USSOFR1M", "GBP": "GBPOIS1M"},
}

# ---------------------------------------------------------------------------
# Floating rate short name → WASP OIS index
# ---------------------------------------------------------------------------

FLOAT_NAME_TO_WASP: dict[str, str] = {
    "SARON": "CHFSON",
    "ESTR": "EUREST",
    "SOFR": "USSOFR",
    "SONIA": "GBPOIS",
}

# ---------------------------------------------------------------------------
# Shock labels
# ---------------------------------------------------------------------------

SHOCKS: list[str] = ["0", "50", "wirp"]

# Extended shocks for full sensitivity grid (activate via --shocks CLI flag)
EXTENDED_SHOCKS: list[str] = ["-200", "-100", "-50", "0", "50", "100", "200", "wirp"]

# ---------------------------------------------------------------------------
# Cost of Carry / Funding
# ---------------------------------------------------------------------------

FUNDING_SOURCE: str = "ois"  # "ois" (default) or "coc"

# WASP carry-compounded curve indices (differ from OIS forward indices for EUR/CHF)
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

# ---------------------------------------------------------------------------
# Pfandbriefbank funding spread by product (bps below OIS)
# ---------------------------------------------------------------------------

FUNDING_SPREAD_BY_PRODUCT: dict[str, float] = {
    "IAM/LD": -0.0015,  # Mortgage: Pfandbrief rate = OIS - 15bp
}

# ---------------------------------------------------------------------------
# SNB reserve parameters
# ---------------------------------------------------------------------------

SNB_RESERVE_RATIO: float = 0.025       # 2.5% on sight liabilities
HQLA_DEDUCTION: float = 0.20           # 20% of HQLA offsets requirement
