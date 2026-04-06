# Configuration

All constants, thresholds, and mappings live in `src/cockpit/config.py`. No magic numbers in computation code.

## YAML Configuration System

Runtime-tunable values are loaded from a YAML file so you can change thresholds, scenarios, and model settings without editing Python code.

### How It Works

| Item | Detail |
|------|--------|
| Config file | `config/cockpit.config.yaml` |
| Loader | `src/cockpit/config_loader.py` |
| Entry point | `load_config()` (with caching) |
| Cache reset | `reset_cache()` (useful in tests) |
| Merge strategy | Deep-merge — user values override built-in defaults recursively |
| All keys optional | Missing keys fall back to built-in defaults in `config_loader.DEFAULTS` |

At startup, `src/cockpit/config.py` calls `load_config()` once and assigns the merged values to module-level constants (e.g., `FX_ALERT_BANDS`, `SCENARIOS`, `ANALYST_MODEL`). The rest of the codebase imports from `config.py` as before.

### Supported Keys

Every key below is optional. Shown values are the built-in defaults.

```yaml
# --- FX Alert Bands ---
fx_alert_bands:
  EUR_CHF: { low: 0.90, high: 0.96 }
  USD_CHF: { low: 0.78, high: 0.85 }
  GBP_CHF: { low: 1.08, high: 1.16 }

# --- Energy Thresholds ---
energy_thresholds:
  brent_high: 120.0
  brent_low: 65.0
  eu_gas_high: 80.0

# --- Deposit Thresholds ---
deposit_thresholds:
  weekly_change_threshold_bln: 2.0

# --- Daily Move Thresholds ---
daily_move_thresholds:
  brent_pct: 5.0
  eu_gas_pct: 5.0
  fx_pct: 1.0
  vix_pct: 10.0

# --- Scoring Labels (0-100 scale) ---
scoring_labels:
  calm_max: 45
  watch_max: 70

# --- CDS Alert ---
cds_alert_threshold_bps: 200

# --- Geopolitical Scenarios ---
scenarios:
  ceasefire_rapid:
    probability: 0.30
    brent_target: 65
    usd_chf_range: [0.82, 0.84]
    eur_chf_range: [0.92, 0.94]
  conflict_contained:
    probability: 0.45
    brent_target: [100, 120]
    usd_chf_range: [0.79, 0.82]
    eur_chf_range: [0.90, 0.93]
  escalation_major:
    probability: 0.25
    brent_target: [130, 150]
    usd_chf_range: [0.75, 0.78]
    eur_chf_range: [0.88, 0.91]

# --- LLM Models ---
analyst_model: "deepseek-r1:14b"
reviewer_model: "qwen3.5:9b"
ollama_host: "http://localhost:11434"
max_review_retries: 3

# --- P&L Engine Overrides ---
shocks: ["0", "50", "wirp"]
```

### Deep-Merge Behavior

The loader uses recursive dictionary merging. You only need to specify the keys you want to override. For example, to widen the EUR/CHF alert band without touching other pairs:

```yaml
fx_alert_bands:
  EUR_CHF: { low: 0.92, high: 0.98 }
```

USD_CHF and GBP_CHF keep their defaults.

### Malformed YAML

If the YAML file is malformed, the loader logs a warning and falls back entirely to built-in defaults. The pipeline does not crash.

### Usage in Code

```python
from cockpit.config_loader import load_config

cfg = load_config()                          # cached after first call
cfg["fx_alert_bands"]["EUR_CHF"]["low"]      # -> 0.90 (or overridden value)

# Force re-read (e.g., after modifying the YAML in a test):
from cockpit.config_loader import reset_cache
reset_cache()
cfg = load_config()
```

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
