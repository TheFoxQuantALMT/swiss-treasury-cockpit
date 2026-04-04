# Scoring & Alerts

## Scoring Engine

Deterministic per-currency risk scores (0-100) with no LLM involvement. Pure Python + config.

### How It Works

```python
from cockpit.engine.scoring.scoring import compute_scores

scores = compute_scores(macro_data)
# Returns: {"USD": CurrencyScore(...), "EUR": ..., "CHF": ..., "GBP": ...}
```

Each currency is scored across 4 indicator families:

| Family | Indicators |
|--------|------------|
| **Inflation** | CPI trends, breakevens, inflation expectations |
| **Policy** | Central bank rates, forward guidance, meeting outcomes |
| **Liquidity** | Sight deposits, money market conditions, reserve ratios |
| **Growth** | GDP growth, employment indicators, PMI data |

### Scoring Process

1. **Extract indicators** from macro snapshot data
2. **Normalize** each indicator to 0-100 via piecewise linear interpolation
3. **Aggregate** per family (average of available indicators)
4. **Composite** score per currency (average of 4 families)
5. **Label** based on thresholds: Calm / Watch / Action

### Labels

| Score Range | Label | Meaning |
|-------------|-------|---------|
| 0 - 45 | **Calm** | Normal conditions, no action required |
| 46 - 70 | **Watch** | Elevated risk, monitor closely |
| 71 - 100 | **Action** | High risk, consider hedging or position adjustment |

### Normalization

```python
from cockpit.engine.scoring.scoring import normalize

# Piecewise linear mapping: [(raw_value, score), ...]
score = normalize(2.5, [(0, 0), (2, 50), (5, 100)])
# -> 62.5
```

Values below the first breakpoint get the first score. Values above the last get the last score. Between breakpoints: linear interpolation.

### Data Classes

```python
@dataclass
class FamilyScore:
    name: str                   # "Inflation", "Policy", "Liquidity", "Growth"
    score: float                # 0-100
    label: str                  # "Calm", "Watch", "Action"
    confidence: str             # "high" (all indicators available), "low" (some missing)
    indicators: dict[str, float | None]  # individual indicator values
    missing: list[str]          # names of missing indicators

@dataclass
class CurrencyScore:
    currency: str               # "USD", "EUR", "CHF", "GBP"
    composite: float            # 0-100
    label: str                  # "Calm", "Watch", "Action"
    families: dict[str, FamilyScore]  # 4 families
    driver: str                 # name of highest-scoring family
```

---

## Alert System

Threshold-based alerts for FX levels, energy prices, deposits, and rate changes.

### How It Works

```python
from cockpit.engine.alerts.alerts import check_alerts

alerts = check_alerts(current_data, deltas)
# Returns: [{"type": "fx_breach", "severity": "high", ...}, ...]
```

### Alert Types

#### FX Breach

Triggered when FX rates cross configured alert bands:

| Pair | Low Band | High Band |
|------|----------|-----------|
| EUR/CHF | 0.90 | 0.96 |
| USD/CHF | 0.78 | 0.85 |
| GBP/CHF | 1.08 | 1.16 |

#### Energy Breach

Triggered when energy prices cross thresholds:

| Metric | Threshold |
|--------|-----------|
| Brent high | 120.0 USD/bbl |
| Brent low | 65.0 USD/bbl |
| EU gas high | 80.0 EUR/MWh |

#### Deposit Breach

Triggered when weekly sight deposit changes exceed the threshold:

| Metric | Threshold |
|--------|-----------|
| Weekly change | 2.0 billion CHF |

#### Daily Move

Triggered when daily percentage moves exceed thresholds:

| Metric | Threshold |
|--------|-----------|
| Brent | 5.0% |
| EU gas | 5.0% |
| FX pairs | 1.0% |
| VIX | 10.0% |

#### Rate Change

Triggered when central bank rates change (any direction).

### Alert Payload

```python
{
    "type": "fx_breach",          # fx_breach, energy_breach, deposit_breach,
                                  # daily_move, rate_change
    "severity": "high",           # high, medium, low
    "metric": "EUR/CHF",
    "current": 0.8990,
    "threshold": 0.90,
    "direction": "below",         # below, above
    "message": "EUR/CHF below 0.90 -- potential SNB intervention zone",
}
```

---

## Historical Comparison

The comparison module computes 1-day, 1-week, and 1-month changes.

```python
from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief

deltas = compute_deltas(current_data)
# Returns: {
#     "usd_chf": {
#         "current": 0.7950,
#         "1d": {"value": 0.7940, "change": 0.0010, "pct": 0.13},
#         "1w": {"value": 0.7880, "change": 0.0070, "pct": 0.89},
#         "1m": {"value": 0.8100, "change": -0.0150, "pct": -1.85},
#     },
#     "brent": {...},
#     ...
# }

# Formatted for LLM brief
table = format_deltas_for_brief(deltas)
```

Comparison data is loaded from the `data/archive/` directory, which stores daily snapshots of fetched data.
