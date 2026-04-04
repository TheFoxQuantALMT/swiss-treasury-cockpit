# Data Models

## Design Philosophy

The project defines the ideal data model in `src/cockpit/engine/models.py`. Input parsers adapt external data to fit these models -- never the reverse. Fields missing from a data source get explicit defaults or null.

## `Deal`

Canonical deal representation with all fields needed for P&L decomposition.

```python
@dataclass
class Deal:
    # Identification
    deal_id: str
    product: str                    # IAM/LD, BND, FXS, IRS, IRS-MTM, HCD
    currency: str                   # CHF, EUR, USD, GBP
    direction: str                  # B(orrow), L(end), D(eposit)

    # Dates
    trade_date: date | None = None
    value_date: date | None = None
    maturity_date: date | None = None

    # Notional
    nominal: float = 0.0
    amount: float = 0.0             # outstanding balance

    # Rates (all in decimal, e.g. 0.035 = 3.5%)
    client_rate: float = 0.0        # contractual rate
    eq_ois_rate: float = 0.0        # equivalent OIS rate (BD-1 rate)
    ytm: float = 0.0                # yield to maturity (bonds)
    coc_rate: float = 0.0           # cost of carry rate (deal-specific funding)
    spread: float = 0.0             # spread over floating index

    # Floating rate leg
    floating_index: str = ""        # "SARON", "ESTR", "SOFR", "SONIA"
    is_floating: bool = False

    # Conventions (ISDA 2006 section 4.16 -- per deal, not per currency)
    day_count: DayCountConvention = DayCountConvention.ACT_360
    compounding_method: CompoundingMethod = CompoundingMethod.NONE
    lookback_days: int = 0          # RFR observation shift (SARON=2, SONIA=5)
    lockout_days: int = 0           # fixing frozen before payment date
    payment_lag_days: int = 0
    accrual_frequency: str = "daily"
    business_day_calendar: str = "" # "ZURICH", "TARGET2", "NYSE", "LONDON"

    # Classification
    book: str = "BOOK1"             # BOOK1 (accrual) or BOOK2 (MTM/FVPL)
    perimeter: str = "CC"           # CC, WM, CIB
    strategy_ias: str | None = None # IAS hedge designation
    counterparty: str = ""

    # Funding
    funding_source: FundingSource = FundingSource.OIS
```

## Enums

### `DayCountConvention`

Per ISDA 2006 section 4.16:

| Value | Divisor | Used by |
|-------|---------|---------|
| `ACT_360` | 360 | CHF/EUR/USD money market instruments |
| `ACT_365` | 365 | GBP all instruments |
| `THIRTY_360` | 360 | CHF/EUR/USD bonds |

```python
class DayCountConvention(str, Enum):
    ACT_360 = "Act/360"
    ACT_365 = "Act/365"
    THIRTY_360 = "30/360"

    @property
    def divisor(self) -> int:
        return {"Act/360": 360, "Act/365": 365, "30/360": 360}[self.value]
```

### `CompoundingMethod`

| Value | Description |
|-------|-------------|
| `NONE` | Fixed rate, no compounding |
| `IN_ARREARS` | ISDA 2021 section 6.9 standard for RFR |
| `IN_ADVANCE` | Non-standard, legacy |

### `FundingSource`

| Value | Description |
|-------|-------------|
| `OIS` | OIS/RFR curve -- post-LIBOR standard (ISDA CSA) |
| `COC` | Deal-specific Cost of Carry rate |
| `FTP` | Funds Transfer Pricing rate |

## `RFRIndex`

Definition of a Risk-Free Rate index with provider-specific curve identifiers:

```python
@dataclass
class RFRIndex:
    name: str                       # "SARON", "ESTR", "SOFR", "SONIA"
    currency: str
    day_count: DayCountConvention
    lookback_days: int              # observation shift in business days
    lockout_days: int = 0
    compounding: CompoundingMethod = CompoundingMethod.IN_ARREARS
    wasp_ois_index: str = ""        # e.g. "CHFSON"
    wasp_carry_index: str = ""      # e.g. "CSCML5"
```

### RFR Registry

Pre-configured RFR indices:

| Name | Currency | Day Count | Lookback | OIS Index | Carry Index |
|------|----------|-----------|----------|-----------|-------------|
| SARON | CHF | Act/360 | 2 BD | CHFSON | CSCML5 |
| ESTR | EUR | Act/360 | 0 | EUREST | ESAVB1 |
| SOFR | USD | Act/360 | 0 | USSOFR | USSOFR |
| SONIA | GBP | Act/365 | 5 BD | GBPOIS | GBPOIS |

Note: Carry indices differ from OIS indices for EUR (ESAVB1 vs EUREST) and CHF (CSCML5 vs CHFSON).

## `MarketData`

Provider-agnostic market data snapshot:

```python
@dataclass
class MarketData:
    ref_date: date
    rfr_fixings: dict[str, list[dict[str, Any]]]     # index -> [{date, rate}, ...]
    ois_curves: dict[str, list[dict[str, Any]]]       # index -> [{date, value}, ...]
    fx_rates: dict[str, float]                        # pair -> rate ("USD_CHF" -> 0.82)
    calendars: dict[str, BusinessDayCalendar]          # center -> calendar
```

## `BusinessDayCalendar`

```python
@dataclass
class BusinessDayCalendar:
    name: str                       # "ZURICH", "TARGET2", "NYSE", "LONDON"
    holidays: list[date]

    def is_business_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays
```

## Helper Functions

### `get_day_count(product, currency) -> DayCountConvention`

Resolves the correct day count convention for a product/currency pair:

```python
get_day_count("BND", "CHF")     # -> THIRTY_360
get_day_count("BND", "GBP")     # -> ACT_365
get_day_count("IAM/LD", "CHF")  # -> ACT_360
get_day_count("IAM/LD", "GBP")  # -> ACT_365
```

### `get_lookback_days(currency) -> int`

Resolves RFR lookback days from the RFR registry:

```python
get_lookback_days("CHF")  # -> 2 (SARON)
get_lookback_days("GBP")  # -> 5 (SONIA)
get_lookback_days("EUR")  # -> 0 (ESTR)
```

## Day Count Convention by Product

| Currency | Money Market (IAM/LD, IRS, FXS, HCD) | Bonds (BND) | Divisor |
|----------|---------------------------------------|-------------|---------|
| CHF | Act/360 | 30/360 | 360 |
| EUR | Act/360 | 30/360 | 360 |
| USD | Act/360 | 30/360 | 360 |
| GBP | Act/365 | Act/365 | 365 |
