# Cost of Carry (CoC) Decomposition

## Overview

The P&L engine decomposes interest rate P&L into Cost of Carry components, providing both simple (linear) and compounded (geometric) calculations side by side. This enables management reporting with the linear approximation while maintaining regulatory-compliant compounded figures.

## Output Measures

The CoC decomposition produces 5 new Indice rows alongside the existing P&L measures:

| Indice | Formula | Regulatory Basis |
|--------|---------|-----------------|
| `GrossCarry` | `SUM(Nom * RateRef * d_i / D)` | IFRS 9.5.4.1 -- interest income |
| `FundingCost` | `SUM(Nom * Funding * d_i / D)` | FTP / OIS discounting (ISDA CSA) |
| `CoC_Simple` | `GrossCarry - FundingCost` | NII component (BCBS 368) |
| `CoC_Compound` | `Nom_avg * [PROD(1 + r*d/D) - PROD(1 + f*d/D)]` | ISDA 2021 section 6.9 |
| `FundingRate` | nominal-weighted average | Transparency |

## Simple CoC (Linear Approximation)

Per IFRS 9.B5.4.5, the simple carry is a management approximation:

```
GrossCarry_month = SUM over days in month:
    Nominal[d] * RateRef[d] * d_i[d] / D

FundingCost_month = SUM over days in month:
    Nominal[d] * FundingRate[d] * d_i[d] / D

CoC_Simple = GrossCarry - FundingCost
```

Where:
- `d_i` = accrual days (ISDA 2021 section 6.9): calendar days between fixings. Weekdays = 1, Friday -> Monday = 3.
- `D` = day count basis: 360 (Act/360 or 30/360) or 365 (Act/365 for GBP)

This is valid when compounding effects are immaterial (short periods, low rates).

## Compounded CoC (Geometric)

Per ISDA 2021 section 6.9, the compounded carry uses daily compounding in arrears:

```
Compounded Rate = [PROD(1 + r_i * d_i / D) - 1] * D / SUM(d_i)
```

Applied to monthly carry:

```
CoC_Compound_month = Nom_avg * [PROD(1 + RateRef_i * d_i / D)
                              - PROD(1 + Funding_i * d_i / D)]
```

Where:
- `r_i` = RFR fixing for day i (with lookback shift for SARON/SONIA)
- `d_i` = calendar days in period i (1 for weekdays, 3 for Fri -> Mon)
- `D` = day count basis per instrument type
- `Nom_avg` = average daily nominal for the month

The compounded calculation correctly handles:
- Weekend compounding: Friday's rate applies for 3 days
- Mid-month rate shifts: each day uses that day's actual rate
- Lookback conventions: SARON uses T-2 BD fixing, SONIA uses T-5 BD

## Simple vs Compounded: When They Diverge

| Scenario | Divergence | Reason |
|----------|------------|--------|
| Short period (< 1 month) | Minimal (<0.01 bps) | Compounding effect negligible |
| Low rates (< 1%) | Minimal | Rate * rate cross-term is tiny |
| High rates (> 5%) | Noticeable | Geometric vs linear grows |
| Long accrual period (> 3 months) | Material | Compounding accumulates |
| Volatile rates | Material | Path-dependent vs average |

Both are computed side by side. Users choose which to report based on materiality and regulatory requirements.

## Funding Source

The funding leg of the CoC calculation is configurable:

| Source | CLI Flag | Description |
|--------|----------|-------------|
| OIS | `--funding-source ois` | OIS/RFR forward curve. Post-LIBOR standard (ISDA CSA). Default. |
| CocRate | `--funding-source coc` | Deal-specific Cost of Carry rate from the MTD report. |

### OIS Funding (Default)

Uses the same OIS forward curve as the P&L calculation. This is the market-standard approach for collateralized derivatives and treasury management.

### CocRate Funding

Uses the deal-level `CocRate` column from the MTD report. Each deal has its own funding cost, broadcast across all days. Useful for FTP (Funds Transfer Pricing) analysis.

## Day Count Conventions

Day count is per instrument type, not just per currency (ISDA 2006 section 4.16):

| Currency | Money Market (IAM/LD, IRS, FXS, HCD) | Bonds (BND) |
|----------|---------------------------------------|-------------|
| CHF | Act/360 | 30/360 |
| EUR | Act/360 | 30/360 |
| USD | Act/360 | 30/360 |
| GBP | Act/365 Fixed | Act/365 Fixed |

## Accrual Day Weights (d_i)

Per ISDA 2021 section 6.9, `d_i` = calendar days between fixings:

| Day | Next Day | d_i |
|-----|----------|-----|
| Monday | Tuesday | 1 |
| Tuesday | Wednesday | 1 |
| Wednesday | Thursday | 1 |
| Thursday | Friday | 1 |
| Friday | Saturday | 1 |
| Saturday | Sunday | 1 |
| Last Friday in grid | (assumed Monday) | 3 |

The daily calendar grid includes all calendar days. The `d_i` weight ensures that Friday's rate compounds over the weekend correctly.

## RFR Lookback

SARON and SONIA use an observation shift (lookback) that affects which rate is used for daily accrual:

| RFR | Lookback | Convention Source |
|-----|----------|-------------------|
| SARON | 2 BD | SNB Working Group |
| ESTR | 0 | Standard |
| SOFR | 0 | Standard |
| SONIA | 5 BD | BoE Working Group |

The lookback means the rate on accrual day T uses the fixing from T-N business days. This is applied in `build_rate_matrix` when constructing the floating rate array.

## BOOK1 vs BOOK2

- **BOOK1 (Accrual):** Both simple and compounded CoC computed side by side
- **BOOK2 (MTM/FVPL):** Excluded from CoC decomposition. Carry is embedded in the MTM delta. Handled separately via `compute_book2_mtm`.

## WASP Comparison

The engine includes a WASP validation pathway for the compounding implementation:

```python
from cockpit.engine.pnl.curves import load_carry_compounded

# WASP carry-compounded rate for a period
wasp_rate = load_carry_compounded(start_date, end_date, "CHF")

# Compare with internal: PROD(1 + r_i * d_i / D) - 1
# Tolerance: < 0.01 bps
```

WASP uses carry-specific indices (different from OIS forward indices):

| Currency | OIS Index | Carry Index |
|----------|-----------|-------------|
| CHF | CHFSON | CSCML5 |
| EUR | EUREST | ESAVB1 |
| USD | USSOFR | USSOFR |
| GBP | GBPOIS | GBPOIS |

When WASP is unavailable, the internal implementation is used alone. Tests skip the WASP comparison gracefully.

## Implementation Details

The CoC decomposition is integrated into the existing `aggregate_to_monthly` function -- no code duplication. When `funding_daily` is provided, the function computes all CoC columns inside the same month loop. Existing callers (without `funding_daily`) are unaffected.

```python
monthly = aggregate_to_monthly(
    daily_pnl, nominal_daily, ois_daily, rate_daily, days,
    funding_daily=funding_matrix,     # triggers CoC computation
    accrual_days=accrual_days,        # ISDA d_i weights
    mm_daily=mm_broadcast,            # day count divisor per deal per day
)
# monthly now has: PnL, Nominal, OISfwd, RateRef,
#                  GrossCarry, FundingCost, CoC_Simple, CoC_Compound, FundingRate
```
