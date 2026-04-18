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
# Bare names map to overnight RFR curves (daily compounding).
# Tenor suffixes (1M/3M/6M) map to term forward curves declared in
# ECHEANCIER_INDEX_TO_WASP — used for term floaters that fix periodically.

FLOAT_NAME_TO_WASP: dict[str, str] = {
    "SARON": "CHFSON",
    "ESTR": "EUREST",
    "SOFR": "USSOFR",
    "SONIA": "GBPOIS",
    "SARON1M": "CHFSON1M", "SARON3M": "CHFSON3M", "SARON6M": "CHFSON6M",
    "ESTR1M":  "EUREST1M", "ESTR3M":  "EUREST3M", "ESTR6M":  "EUREST6M",
    "SOFR1M":  "USSOFR1M", "SOFR3M":  "USSOFR3M", "SOFR6M":  "USSOFR6M",
    "SONIA1M": "GBPOIS1M", "SONIA3M": "GBPOIS3M", "SONIA6M": "GBPOIS6M",
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

FUNDING_SOURCE: str = "ois"  # "ois" (default), "carry", or "coc"

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

# ---------------------------------------------------------------------------
# Validation sets for deal data ingestion
# ---------------------------------------------------------------------------

VALID_PRODUCTS: set[str] = {"IAM/LD", "BND", "FXS", "IRS", "IRS-MTM", "HCD"}
VALID_DIRECTIONS: set[str] = {"B", "L", "D", "S"}
VALID_BOOKS: set[str] = {"BOOK1", "BOOK2"}
VALID_PERIMETERS: set[str] = {"CC", "WM", "CIB"}

# ---------------------------------------------------------------------------
# Direction → balance sheet side classification
# ---------------------------------------------------------------------------
# Convention (set by the echeancier legacy parser):
#   L = Loan (bank lends money out) → asset (negative nominal in echeancier)
#   B = Bond purchase → asset (negative nominal in echeancier)
#   D = Deposit (bank receives funds) → liability (positive nominal in echeancier)
#   S = Sell Bond → asset (negative nominal in echeancier)

ASSET_DIRECTIONS: set[str] = {"L", "B", "S"}
LIABILITY_DIRECTIONS: set[str] = {"D"}
DIRECTION_SIDE: dict[str, str] = {
    "L": "asset", "B": "asset", "S": "asset",
    "D": "liability",
}

# ---------------------------------------------------------------------------
# SNB sight liability product codes (configurable per bank)
# ---------------------------------------------------------------------------

SNB_SIGHT_PRODUCTS: set[str] = {"KK", "CC", "SE", "SIGHT", "SICHT"}
VALID_FLOAT_INDICES: set[str] = set(FLOAT_NAME_TO_WASP) | {""}

# IAS hedge strategy leg identifiers (§10.8 direction filtering).
STRATEGY_LEG_BND: set[str] = {"BND-HCD", "BND-NHCD"}
STRATEGY_LEG_IAM: set[str] = {"IAM/LD-HCD", "IAM/LD-NHCD"}

# ---------------------------------------------------------------------------
# Bank-native @Category2 taxonomy (authoritative)
# ---------------------------------------------------------------------------
# Classifies each deal into one balance-sheet / accounting bucket. The
# Synthesis export aggregates along this axis; Phase 5 reconciliation uses it
# to localise drift.
#
#   Book1 (Accrual / IAS) — 6 buckets:
#     OPP_Bond_ASW    asset-swapped bonds, accrual leg
#     OPP_Bond_nASW   plain bonds (govt / corp), no asset-swap
#     OPP_CASH        deposits, loans, money market
#     OPR_FVH         fair-value-hedge designated hedged item
#     OPR_nFVH        open-risk position (no hedge designation)
#     Other           catch-all
#
#   Book2 (Mark-to-Market) — 4 buckets:
#     OPP_Bond_ASW    MtM leg of asset-swap
#     OPR_FVH         MtM leg of fair-value-hedge relationship
#     IRS_FVH         IRS designated as fair-value hedging instrument
#     IRS_FVO         IRS under fair-value option (no hedge designation)
#
# The Synthesis sheet "FVH All" line is the union of the three FVH-flavoured
# buckets (OPP_Bond_ASW ∪ OPR_FVH ∪ IRS_FVH), computed on the fly.

VALID_CATEGORY2_BOOK1: set[str] = {
    "OPP_Bond_ASW", "OPP_Bond_nASW", "OPP_CASH",
    "OPR_FVH", "OPR_nFVH", "Other",
}

VALID_CATEGORY2_BOOK2: set[str] = {
    "OPP_Bond_ASW", "OPR_FVH", "IRS_FVH", "IRS_FVO",
}

VALID_CATEGORY2: set[str] = VALID_CATEGORY2_BOOK1 | VALID_CATEGORY2_BOOK2

CATEGORY2_FVH_ALL: set[str] = {"OPP_Bond_ASW", "OPR_FVH", "IRS_FVH"}

# Bank-native workbook sheet → canonical Book value (the Phase-2 parser uses
# this to tag rows on load; the rest of the pipeline keeps the existing
# "BOOK1" / "BOOK2" string convention).
SHEET_TO_BOOK: dict[str, str] = {
    "Book1_Daily_PnL": "BOOK1",
    "Book2_Daily_PnL": "BOOK2",
}
