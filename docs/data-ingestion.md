# Data Ingestion

## DataManager

The `DataManager` orchestrates concurrent fetching from all market data sources with graceful degradation.

```python
from cockpit.data.manager import DataManager

dm = DataManager(fred_api_key="your_key")
results = asyncio.run(dm.refresh_all_data())
```

### Behavior

1. **Archive** current data before fetching (daily snapshots in `data/archive/`)
2. **Fetch** all sources concurrently via `asyncio.gather`
3. **Fallback** to most recent archive for any failed source
4. **Report** stale sources in the `stale` array

### Output

```python
{
    "rates": {
        "fed_funds_rate": ...,
        "ecb_rate": ...,
        "snb_rate": ...,
        "saron": ...,
    },
    "fx": {
        "usd_chf_latest": {"value": 0.82, "date": "2026-04-04"},
        "eur_chf_latest": {"value": 0.93, "date": "2026-04-04"},
        "gbp_chf_latest": {"value": 1.12, "date": "2026-04-04"},
    },
    "energy": {
        "brent": {"value": 85.2, "date": "2026-04-04"},
        "eu_gas": {"value": 32.5, "date": "2026-04-04"},
        "vix": {"value": 18.3, "date": "2026-04-04"},
    },
    "sight_deposits": {...},
    "stale": [],                    # list of failed sources
    "timestamp": "2026-04-04",
}
```

---

## Fetchers

All fetchers use the `CircuitBreaker` pattern for resilient API calls.

### FREDFetcher

Fetches US macro data from the Federal Reserve Economic Data API.

| Series | Data |
|--------|------|
| Fed funds rate | Current target rate |
| CPI | Consumer price index |
| GDP | Gross domestic product |
| Unemployment | Unemployment rate |

Requires `FRED_API_KEY` environment variable.

### ECBFetcher

Fetches ECB data via SDMX API.

| Series | Data |
|--------|------|
| ECB policy rate | Main refinancing rate |
| EUR/CHF | Exchange rate |

### SNB Fetcher

Fetches Swiss National Bank data via SDMX API.

| Function | Data |
|----------|------|
| `fetch_sight_deposits()` | Sight deposits at SNB |
| `fetch_saron()` | SARON fixing rate |

### YFinanceFetcher

Fetches market data from Yahoo Finance.

| Ticker | Data |
|--------|------|
| USDCHF=X | USD/CHF exchange rate |
| GBPCHF=X | GBP/CHF exchange rate |
| BZ=F | Brent crude futures |
| TTF=F | EU natural gas (TTF) |
| ^VIX | VIX volatility index |

### CircuitBreaker

Wraps API calls with failure tracking:
- Opens after consecutive failures
- Stays open for a cooldown period
- Half-opens to test recovery
- Prevents cascading failures

---

## Parsers

Excel parsers for internal treasury data. All return `pd.DataFrame`.

Each data source has two parsers: an **ideal-format** parser (clean schema, thin validation) and a **legacy adapter** that auto-detects the format and delegates to the ideal parser when possible.

### Input File Formats

#### Ideal format (4 files)

| File | Sheet | Parser | Description |
|------|-------|--------|-------------|
| `deals.xlsx` | Deals | `parse_deals()` | Unified BOOK1 + BOOK2 deals |
| `schedule.xlsx` | Schedule | `parse_schedule()` | Monthly nominal balances |
| `wirp.xlsx` | WIRP | `parse_wirp_ideal()` | Rate expectations |
| `reference_table.xlsx` | Reference | `parse_reference_table()` | Counterparty metadata |

#### Legacy format (5 files)

| File | Parser | Notes |
|------|--------|-------|
| `*MTD Standard Liquidity PnL Report*` | `parse_mtd()` | Auto-detects ideal format |
| `*Echeancier*` | `parse_echeancier()` | Auto-detects ideal format |
| `*WIRP*` | `parse_wirp()` | Auto-detects ideal format |
| `*IRS*` | `parse_irs_stock()` | Separate BOOK2 IRS stock |
| `reference_table.xlsx` | `parse_reference_table()` | Already clean |

`ForecastRatePnL.load_data()` tries ideal-format files first (`*deals*`, `*schedule*`, `*wirp*`), then falls back to legacy globs.

---

### `parse_deals(path) -> DataFrame`

Parses ideal-format `deals.xlsx` — unified BOOK1 + BOOK2 deals with clean schema.

**Source sheet:** "Deals" (header row 1)

**Input columns (snake_case) → internal names:**

| Input | Internal | Type | Values |
|-------|----------|------|--------|
| `deal_id` | Dealid | int | Numeric join key |
| `product` | Product | str | IAM/LD, BND, FXS, IRS, IRS-MTM, HCD |
| `currency` | Currency | str | CHF, EUR, USD, GBP |
| `direction` | Direction | str | B, L, D, S (single char) |
| `book` | IAS Book | str | BOOK1, BOOK2 |
| `amount` | Amount | float | Signed balance |
| `client_rate` | Clientrate | float | Decimal (0.0125 = 1.25%) |
| `eq_ois_rate` | EqOisRate | float | Decimal |
| `ytm` | YTM | float | Decimal, net of credit spread |
| `coc_rate` | CocRate | float | Decimal |
| `spread` | Spread | float | Decimal (not bps) |
| `floating_index` | Floating Rates Short Name | str | SARON, ESTR, SOFR, SONIA, "" |
| `trade_date` | Tradedate | date | ISO 8601 |
| `value_date` | Valuedate | date | ISO 8601 |
| `maturity_date` | Maturitydate | date | Required |
| `strategy_ias` | Strategy IAS | str | Hedge designation |
| `perimeter` | Périmètre TOTAL | str | CC, WM, CIB (explicit) |
| `counterparty` | Counterparty | str | Counterparty code |
| `pay_receive` | pay_receive | str | PAY, RECEIVE (BOOK2 only) |
| `notional` | notional | float | BOOK2 only |
| `last_fixing_date` | last_fixing_date | date | Most recent floating rate reset (BOOK2 only) |
| `next_fixing_date` | next_fixing_date | date | Next floating rate reset (BOOK2 only) |

**Validation:** deal_id non-null, product/currency/direction/book in allowed sets, maturity_date valid, rates |v| < 0.50, perimeter defaults to CC.

**BOOK split:** `ForecastRatePnL._split_deals_by_book()` splits by `IAS Book`: BOOK1 → accrual P&L, BOOK2 → adapted to WASP `stockSwapMTM` column format.

### `parse_mtd(path) -> DataFrame` (legacy)

Parses the MTD Standard Liquidity PnL Report. Auto-detects ideal format (checks for "Deals" sheet) and delegates to `parse_deals()` if found.

**Legacy transformations:**
- Direction: first character of "ALMT Direction" (B: Bond, L: Loan, D: Deposit, S: Sold)
- Perimeter: derived from counterparty code (CC, WM, CIB)
- BOOK1 filter: only IAS Book == "BOOK1" rows
- Credit spread subtraction: BND YTM -= CreditSpread_FIFO
- Rate conversion: percent → decimal (÷ 100)
- Spread conversion: bps → decimal (÷ 10,000)

---

### `parse_schedule(path) -> DataFrame`

Parses ideal-format `schedule.xlsx` — monthly nominal balances with clean schema.

**Source sheet:** "Schedule" (header row 1)

**Input columns:**

| Input | Internal | Type | Notes |
|-------|----------|------|-------|
| `deal_id` | Dealid | int | Plain numeric (not "Type@ID") |
| `direction` | Direction | str | B, L, D, S |
| `currency` | Currency | str | CHF, EUR, USD, GBP |
| `rate_type` | Rate Type | str | F or V |
| `YYYY/MM` | (same) | float | Monthly balance columns |

**Pre-conditions (source system responsibility):** RFR V-legs pre-filtered, reverse repos pre-filtered, V-leg balances pre-forward-filled, direction explicit.

### `parse_echeancier(path) -> DataFrame` (legacy)

Parses the legacy Echeancier. Auto-detects ideal format (checks for "Schedule" sheet) and delegates to `parse_schedule()` if found.

**Legacy transformations:** "Type@ID" splitting, RFR V-leg filtering, reverse repo filtering, direction from deal type/balance sign, V-leg forward-fill.

---

### `parse_wirp_ideal(path) -> DataFrame`

Parses ideal-format `wirp.xlsx` — rate expectations with proper header and WASP index names.

**Source sheet:** "WIRP" (header row 1)

| Input | Internal | Type | Example |
|-------|----------|------|---------|
| `index` | Indice | str | CHFSON, EUREST, USSOFR, GBPOIS |
| `meeting_date` | Meeting | date | 2026-06-19 |
| `rate` | Rate | float | 0.0125 (decimal) |
| `change_bps` | Hike / Cut | float | -25 |

### `parse_wirp(path) -> DataFrame` (legacy)

Parses legacy WIRP. Auto-detects ideal format and delegates. Legacy uses usecols/skiprows/forward-fill.

---

### `_month_columns(df) -> list[str]`

Extracts month column names matching the `YYYY/MM` pattern.

### `parse_irs_stock(path) -> DataFrame` (legacy)

Parses the IRS derivatives stock for BOOK2 MTM valuation. Only needed with legacy input layout — unified `deals.xlsx` includes BOOK2 rows directly.

### `parse_reference_table(path) -> DataFrame`

Parses the counterparty reference table.

**Output columns:** counterparty, rating, hqla_level, country

Used by portfolio snapshot enrichment to classify deals by credit quality and HQLA eligibility.
