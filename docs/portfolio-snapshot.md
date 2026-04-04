# Portfolio Snapshot

## Overview

The portfolio snapshot module builds a comprehensive view of the treasury portfolio, organized into three sections: exposure (liquidity ladder), position aggregation, and counterparty concentration.

```python
from cockpit.engine.snapshot import build_portfolio_snapshot

snapshot = build_portfolio_snapshot(
    echeancier=schedule_df,
    deals=deals_df,
    ref_table=ref_table_df,
    fx_rates={"USD": 0.82, "EUR": 0.93, "GBP": 1.12},
    ref_date=date(2026, 4, 4),
)
```

## Pipeline

```
deals + ref_table --> enrich_deals()
                          |
                          v
                    enriched deals
                     /    |    \
                    v     v     v
         exposure()  positions()  counterparty()
              |          |              |
              v          v              v
        liquidity    position      counterparty
        ladder       aggregation   concentration
              \          |              /
               v         v             v
              build_portfolio_snapshot()
                          |
                          v
                portfolio_snapshot.json
```

## Enrichment

`enrich_deals(deals, ref_table)` joins reference data (rating, HQLA level, country) onto deal records by counterparty. Missing reference data gets explicit defaults.

## Liquidity Ladder

`compute_liquidity_ladder(echeancier, deals, ref_date)` classifies exposures into time buckets based on days to maturity:

| Bucket | Days |
|--------|------|
| O/N | 0 |
| D+1 to D+15 | 1-15 (individual days) |
| 16-30d | 16-30 |
| 1-3M | 31-90 |
| 3-6M | 91-180 |
| 6-12M | 181-365 |
| 1-2Y | 366-730 |
| 2-5Y | 731-1825 |
| 5Y+ | 1826+ |
| Undefined | Missing maturity |

## Position Aggregation

`compute_positions(deals, fx_rates, ref_date)` aggregates positions by:

- **Currency class:** Total, CHF, USD, EUR, GBP, Others
- **Rating bucket:** AAA-AA, A, BBB, Sub-IG, NR
- **HQLA level:** L1, L2A, L2B, Non-HQLA

FX rates convert all positions to CHF equivalent.

## Counterparty Concentration

`compute_counterparty(deals, cds_spreads, ref_date)` analyzes:

- Top counterparty exposures
- CDS spread alerts (threshold: 200 bps)
- Concentration by perimeter (CC, WM, CIB)

### Perimeter Classification

Counterparties are classified by perimeter based on code:

| Perimeter | Counterparty Codes |
|-----------|--------------------|
| WM | THCCBFIGE, BKCCBFIGE, THCCBZIWE, WCCCBFIGE, THCCHFIGE |
| CIB | CLI-MT-CIB, CPFNCLI, CLI-FI-CIB |
| CC | All others |

## Output Format

```json
{
    "generated_at": "2026-04-04T08:30:00",
    "ref_date": "2026-04-04",
    "exposure": {
        "ladder": [
            {"bucket": "O/N", "amount_chf": 150000000, ...},
            {"bucket": "D+1", "amount_chf": 80000000, ...},
            ...
        ]
    },
    "positions": {
        "by_currency": {...},
        "by_rating": {...},
        "by_hqla": {...}
    },
    "counterparty": {
        "top_exposures": [...],
        "cds_alerts": [...],
        "by_perimeter": {...}
    }
}
```

## Serialization

```python
from cockpit.engine.snapshot import write_snapshot

write_snapshot(snapshot, Path("data/2026-04-04_portfolio.json"))
```
