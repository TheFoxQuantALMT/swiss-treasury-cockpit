# Configuration

All constants, thresholds, and mappings live in `src/cockpit/config.py`. No magic numbers in computation code.

## Paths

| Constant | Default | Description |
|----------|---------|-------------|
| `PROJECT_ROOT` | auto-detected | Repository root |
| `DATA_DIR` | `{PROJECT_ROOT}/data` | JSON intermediates |
| `OUTPUT_DIR` | `{PROJECT_ROOT}/output` | Rendered HTML dashboards |

## P&L Engine

### OIS Index Mapping

```python
CURRENCY_TO_OIS = {
    "CHF": "CHFSON",
    "EUR": "EUREST",
    "USD": "USSOFR",
    "GBP": "GBPOIS",
}
```

### Rate Column by Product

```python
PRODUCT_RATE_COLUMN = {
    "IAM/LD": "EqOisRate",
    "BND": "YTM",
    "FXS": "EqOisRate",
    "IRS": "Clientrate",
    "IRS-MTM": "Clientrate",
    "HCD": "Clientrate",
}
```

### Day Count by Currency

```python
MM_BY_CURRENCY = {"CHF": 360, "EUR": 360, "USD": 360, "GBP": 365}
```

Note: This is the fallback. When `Product` column is available, the engine uses product-aware day count from `models.py`.

### Supported Currencies

```python
SUPPORTED_CURRENCIES = {"CHF", "EUR", "USD", "GBP"}
```

### Non-Strategy Products

```python
NON_STRATEGY_PRODUCTS = {"BND", "FXS", "IAM/LD", "IRS", "IRS-MTM"}
```

### Shock Scenarios

```python
SHOCKS = ["0", "50", "wirp"]
```

### Floating Rate Index Mapping

```python
FLOAT_NAME_TO_WASP = {
    "SARON": "CHFSON",
    "ESTR": "EUREST",
    "SOFR": "USSOFR",
    "SONIA": "GBPOIS",
}
```

### Echeancier Index to WASP (by tenor)

```python
ECHEANCIER_INDEX_TO_WASP = {
    "3M": {"CHF": "CHFSON3M", "EUR": "EUREST3M", "USD": "USSOFR3M", "GBP": "GBPOIS3M"},
    "6M": {"CHF": "CHFSON6M", "EUR": "EUREST6M", "USD": "USSOFR6M", "GBP": "GBPOIS6M"},
    "1M": {"CHF": "CHFSON1M", "EUR": "EUREST1M", "USD": "USSOFR1M", "GBP": "GBPOIS1M"},
}
```

## Cost of Carry / P&L Decomposition

### Funding Source

```python
FUNDING_SOURCE = "ois"    # default: "ois" or "coc"
```

### Carry-Compounded Curve Indices

```python
CURRENCY_TO_CARRY_INDEX = {
    "CHF": "CSCML5",     # differs from OIS (CHFSON)
    "EUR": "ESAVB1",     # differs from OIS (EUREST)
    "USD": "USSOFR",     # same as OIS
    "GBP": "GBPOIS",     # same as OIS
}
```

### RFR Lookback

```python
LOOKBACK_DAYS = {"CHF": 2, "GBP": 5}
# CHF: SARON 2 business day lookback (SNB Working Group)
# GBP: SONIA 5 business day lookback (BoE Working Group)
```

## Exposure Module

### Liquidity Buckets

```python
LIQUIDITY_BUCKETS = [
    ("O/N", 0, 0),
    ("D+1", 1, 1), ("D+2", 2, 2), ..., ("D+15", 15, 15),
    ("16-30d", 16, 30),
    ("1-3M", 31, 90),
    ("3-6M", 91, 180),
    ("6-12M", 181, 365),
    ("1-2Y", 366, 730),
    ("2-5Y", 731, 1825),
    ("5Y+", 1826, None),
    ("Undefined", None, None),
]
```

### Rating Buckets

```python
RATING_BUCKETS = {
    "AAA-AA": ["AAA", "AA+", "AA", "AA-"],
    "A": ["A+", "A", "A-"],
    "BBB": ["BBB+", "BBB", "BBB-"],
    "Sub-IG": ["BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C", "D"],
    "NR": ["NR"],
}
```

### HQLA Levels

```python
HQLA_LEVELS = ["L1", "L2A", "L2B", "Non-HQLA"]
```

### Currency Classes

```python
CURRENCY_CLASSES = ["Total", "CHF", "USD", "EUR", "GBP", "Others"]
```

### CDS Alert Threshold

```python
CDS_ALERT_THRESHOLD_BPS = 200
```

## Macro Monitoring

### FX Alert Bands

```python
FX_ALERT_BANDS = {
    "EUR_CHF": {"low": 0.90, "high": 0.96},
    "USD_CHF": {"low": 0.78, "high": 0.85},
    "GBP_CHF": {"low": 1.08, "high": 1.16},
}
```

### Energy Thresholds

```python
ENERGY_THRESHOLDS = {
    "brent_high": 120.0,
    "brent_low": 65.0,
    "eu_gas_high": 80.0,
}
```

### Deposit Thresholds

```python
DEPOSIT_THRESHOLDS = {"weekly_change_threshold_bln": 2.0}
```

### Daily Move Thresholds

```python
DAILY_MOVE_THRESHOLDS = {
    "brent_pct": 5.0,
    "eu_gas_pct": 5.0,
    "fx_pct": 1.0,
    "vix_pct": 10.0,
}
```

### Scoring Labels

```python
SCORING_LABELS = {"calm_max": 45, "watch_max": 70}
```

### Geopolitical Scenarios

```python
SCENARIOS = {
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
```

## LLM Models

```python
ANALYST_MODEL = "deepseek-r1:14b"
REVIEWER_MODEL = "qwen3.5:9b"
OLLAMA_HOST = "http://localhost:11434"
MAX_REVIEW_RETRIES = 3
```

## Counterparty Perimeters

```python
_WM_COUNTERPARTIES = {"THCCBFIGE", "BKCCBFIGE", "THCCBZIWE", "WCCCBFIGE", "THCCHFIGE"}
_CIB_COUNTERPARTIES = {"CLI-MT-CIB", "CPFNCLI", "CLI-FI-CIB"}
```
