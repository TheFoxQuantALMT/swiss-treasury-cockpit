"""Canonical data models for the P&L engine.

The project defines the ideal data model. Input parsers adapt external data
to fit these models — never the reverse. Fields missing from a data source
get explicit defaults or null.

Regulatory references:
    - ISDA 2006 Definitions §4.16: day count conventions
    - ISDA 2021 Definitions §6.9: RFR compounding in arrears
    - IFRS 9.5.4.1 / B5.4.5: effective interest rate method
    - BCBS 368: IRRBB NII sensitivity
    - SNB Working Group: SARON 2-BD lookback
    - BoE Working Group: SONIA 5-BD lookback
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DayCountConvention(str, Enum):
    """ISDA 2006 §4.16 day count conventions."""

    ACT_360 = "Act/360"
    ACT_365 = "Act/365"
    THIRTY_360 = "30/360"

    @property
    def divisor(self) -> int:
        """Annual divisor used in rate × days / divisor."""
        return {"Act/360": 360, "Act/365": 365, "30/360": 360}[self.value]


class CompoundingMethod(str, Enum):
    """How interest compounds over an accrual period."""

    NONE = "none"                # fixed rate, no compounding
    IN_ARREARS = "in_arrears"    # ISDA 2021 §6.9 standard for RFR
    IN_ADVANCE = "in_advance"    # non-standard, legacy


class FundingSource(str, Enum):
    """Which rate is used for the funding leg of CoC."""

    OIS = "ois"    # OIS/RFR curve — post-LIBOR standard (ISDA CSA)
    COC = "coc"    # Deal-specific Cost of Carry rate
    FTP = "ftp"    # Funds Transfer Pricing rate


# ---------------------------------------------------------------------------
# Deal
# ---------------------------------------------------------------------------

@dataclass
class Deal:
    """Canonical deal representation — all fields needed for P&L decomposition.

    Parsers (e.g. ``mtd.py``) map source data INTO this model.
    """

    # Identification
    deal_id: str
    product: str                        # IAM/LD, BND, FXS, IRS, IRS-MTM, HCD
    currency: str                       # CHF, EUR, USD, GBP
    direction: str                      # B(orrow), L(end), D(eposit)

    # Dates
    trade_date: date | None = None
    value_date: date | None = None
    maturity_date: date | None = None

    # Notional
    nominal: float = 0.0
    amount: float = 0.0                 # outstanding balance

    # Rates (all in decimal, e.g. 0.035 = 3.5%)
    client_rate: float = 0.0            # contractual rate
    eq_ois_rate: float = 0.0            # equivalent OIS rate (BD-1 rate)
    ytm: float = 0.0                    # yield to maturity (bonds)
    coc_rate: float = 0.0               # cost of carry rate (deal-specific funding)
    spread: float = 0.0                 # spread over floating index

    # Floating rate leg
    floating_index: str = ""            # e.g. "SARON", "ESTR", "SOFR", "SONIA"
    is_floating: bool = False

    # Conventions — per deal, not per currency (ISDA 2006 §4.16)
    day_count: DayCountConvention = DayCountConvention.ACT_360
    compounding_method: CompoundingMethod = CompoundingMethod.NONE
    lookback_days: int = 0              # RFR observation shift (SARON=2, SONIA=5)
    lockout_days: int = 0               # fixing frozen before payment date
    payment_lag_days: int = 0
    accrual_frequency: str = "daily"    # daily, monthly, quarterly
    business_day_calendar: str = ""     # e.g. "ZURICH", "TARGET2", "NYSE", "LONDON"

    # Classification
    book: str = "BOOK1"                 # BOOK1 (accrual) or BOOK2 (MTM/FVPL)
    perimeter: str = "CC"               # CC, WM, CIB
    strategy_ias: str | None = None     # IAS hedge designation
    counterparty: str = ""

    # Funding
    funding_source: FundingSource = FundingSource.OIS


# ---------------------------------------------------------------------------
# RFR Index
# ---------------------------------------------------------------------------

@dataclass
class RFRIndex:
    """Definition of a Risk-Free Rate index.

    Encapsulates conventions per RFR (ISDA 2021 §6.9, SNB WG, BoE WG)
    and provider-specific curve identifiers.
    """

    name: str                           # canonical: "SARON", "ESTR", "SOFR", "SONIA"
    currency: str
    day_count: DayCountConvention
    lookback_days: int                  # observation shift in business days
    lockout_days: int = 0               # fixing frozen before payment
    compounding: CompoundingMethod = CompoundingMethod.IN_ARREARS

    # Provider-specific mappings (adapter layer fills these)
    wasp_ois_index: str = ""            # e.g. "CHFSON" — forward rate curve
    wasp_carry_index: str = ""          # e.g. "CSCML5" — compounded carry curve


# ---------------------------------------------------------------------------
# Market Data
# ---------------------------------------------------------------------------

@dataclass
class BusinessDayCalendar:
    """Holiday calendar for a trading center."""

    name: str                           # e.g. "ZURICH", "TARGET2", "NYSE", "LONDON"
    holidays: list[date] = field(default_factory=list)

    def is_business_day(self, d: date) -> bool:
        """True if *d* is a weekday and not a holiday."""
        return d.weekday() < 5 and d not in self.holidays


@dataclass
class MarketData:
    """Market data snapshot — provider-agnostic.

    Parsers/fetchers populate this from any source (WASP, FRED, ECB, files).
    """

    ref_date: date
    rfr_fixings: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # index_name → [{"date": date, "rate": float}, ...]
    ois_curves: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # index_name → [{"date": date, "value": float}, ...]
    fx_rates: dict[str, float] = field(default_factory=dict)
    # pair → rate (e.g. "USD_CHF" → 0.82)
    calendars: dict[str, BusinessDayCalendar] = field(default_factory=dict)
    # center_name → calendar


# ---------------------------------------------------------------------------
# Registry of standard RFR indices
# ---------------------------------------------------------------------------

RFR_REGISTRY: dict[str, RFRIndex] = {
    "SARON": RFRIndex(
        name="SARON",
        currency="CHF",
        day_count=DayCountConvention.ACT_360,
        lookback_days=2,
        wasp_ois_index="CHFSON",
        wasp_carry_index="CSCML5",
    ),
    "ESTR": RFRIndex(
        name="ESTR",
        currency="EUR",
        day_count=DayCountConvention.ACT_360,
        lookback_days=0,
        wasp_ois_index="EUREST",
        wasp_carry_index="ESAVB1",
    ),
    "SOFR": RFRIndex(
        name="SOFR",
        currency="USD",
        day_count=DayCountConvention.ACT_360,
        lookback_days=0,
        wasp_ois_index="USSOFR",
        wasp_carry_index="USSOFR",
    ),
    "SONIA": RFRIndex(
        name="SONIA",
        currency="GBP",
        day_count=DayCountConvention.ACT_365,
        lookback_days=5,
        wasp_ois_index="GBPOIS",
        wasp_carry_index="GBPOIS",
    ),
}

# Currency → default RFR index
CURRENCY_TO_RFR: dict[str, str] = {
    "CHF": "SARON",
    "EUR": "ESTR",
    "USD": "SOFR",
    "GBP": "SONIA",
}

# Product → day count convention (ISDA 2006 §4.16)
# Money market instruments use Act/360 (Act/365 for GBP)
# Bonds use 30/360 (Act/365 for GBP)
PRODUCT_DAY_COUNT: dict[str, dict[str, DayCountConvention]] = {
    "BND": {
        "CHF": DayCountConvention.THIRTY_360,
        "EUR": DayCountConvention.THIRTY_360,
        "USD": DayCountConvention.THIRTY_360,
        "GBP": DayCountConvention.ACT_365,
    },
    # All other products default to currency convention
    "_default": {
        "CHF": DayCountConvention.ACT_360,
        "EUR": DayCountConvention.ACT_360,
        "USD": DayCountConvention.ACT_360,
        "GBP": DayCountConvention.ACT_365,
    },
}


def get_day_count(product: str, currency: str) -> DayCountConvention:
    """Resolve day count convention for a product/currency pair."""
    product_map = PRODUCT_DAY_COUNT.get(product, PRODUCT_DAY_COUNT["_default"])
    return product_map.get(currency, DayCountConvention.ACT_360)


def get_lookback_days(currency: str) -> int:
    """Resolve RFR lookback days for a currency."""
    rfr_name = CURRENCY_TO_RFR.get(currency)
    if rfr_name and rfr_name in RFR_REGISTRY:
        return RFR_REGISTRY[rfr_name].lookback_days
    return 0
