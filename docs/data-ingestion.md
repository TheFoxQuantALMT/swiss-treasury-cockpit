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

### `parse_mtd(path) -> DataFrame`

Parses the MTD Standard Liquidity PnL Report (BOOK1 deals).

**Source sheet:** "Conso Deal Level" (skip first row)

**Key transformations:**
- Column renaming from Excel headers to internal names
- Direction: first character of "ALMT Direction" (B, L, D)
- Perimeter: classified from counterparty code (CC, WM, CIB)
- BOOK1 filter: only IAS Book == "BOOK1" rows
- Credit spread subtraction: BND YTM -= CreditSpread_FIFO
- Rate conversion: percent to decimal (divide by 100)
- Spread conversion: bps to decimal (divide by 10,000)
- Currency filter: only CHF, EUR, USD, GBP
- Maturity filter: valid maturity date required

**Output columns:**

| Column | Type | Description |
|--------|------|-------------|
| Dealid | numeric | Deal identifier |
| Product | str | IAM/LD, BND, FXS, IRS, HCD |
| Currency | str | CHF, EUR, USD, GBP |
| Direction | str | B, L, D |
| Amount | float | Outstanding balance |
| Clientrate | float | Contractual rate (decimal) |
| EqOisRate | float | BD-1 OIS equivalent rate (decimal) |
| YTM | float | Yield to maturity (decimal, bonds only) |
| CocRate | float | Cost of carry rate (decimal) |
| Spread | float | Spread over index (decimal) |
| Valuedate | str | Value date |
| Maturitydate | str | Maturity date |
| Strategy IAS | str/NaN | IAS hedge designation |
| Counterparty | str | Counterparty code |
| Perimetre TOTAL | str | CC, WM, CIB |

### `parse_echeancier(path) -> DataFrame`

Parses the Echeancier (nominal schedule by month).

**Key features:**
- Month columns in `YYYY/MM` format (e.g., "2026/04")
- Join key: `(Dealid, Direction, Currency)`
- Aggregates F+V legs if both present for same deal

### `_month_columns(df) -> list[str]`

Extracts month column names from an echeancier DataFrame. Identifies columns matching the `YYYY/MM` pattern.

### `parse_wirp(path) -> DataFrame`

Parses WIRP (rate expectations) data.

**Output columns:** Indice, Meeting (date), Rate

Used for the WIRP shock scenario: central bank meeting rates are forward-filled to create a step-function rate path.

### `parse_irs_stock(path) -> DataFrame`

Parses the IRS derivatives stock for BOOK2 MTM valuation.

### `parse_reference_table(path) -> DataFrame`

Parses the counterparty reference table.

**Output columns:** counterparty, rating, hqla_level, country

Used by portfolio snapshot enrichment to classify deals by credit quality and HQLA eligibility.
