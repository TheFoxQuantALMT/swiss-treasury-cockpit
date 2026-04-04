# P&L Engine

## Overview

The P&L engine computes economic interest rate P&L for a portfolio of treasury instruments (loans, deposits, bonds, IRS) across shock scenarios. It operates on a 60-month forward date grid using vectorized numpy arrays.

The engine is split into two accounting books:

- **BOOK1 (Accrual):** OIS-spread P&L on loans, deposits, bonds, hedge components. Includes Cost of Carry decomposition (simple and compounded).
- **BOOK2 (MTM/FVPL):** Mark-to-market P&L on IRS positions via WASP `stockSwapMTM`. The result is NPV, not interest accrual.

## Entry Point: `ForecastRatePnL`

```python
from cockpit.engine.pnl.forecast import ForecastRatePnL

pnl = ForecastRatePnL(
    dateRun=datetime(2026, 4, 4),
    dateRates=datetime(2026, 4, 4),
    export=True,
    input_dir="path/to/excels",
    funding_source="ois",  # or "coc"
)

# Results
pnl.pnlAll     # wide DataFrame (months as columns)
pnl.pnlAllS    # stacked long DataFrame with MultiIndex

# Re-run with different shock without reloading data
pnl.update_pnl(Shock="50")
```

### Constructor Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dateRun` | datetime | required | Stock/run reference date. Controls which deal data loads. |
| `dateRates` | datetime | dateRun | Market date for forward curves. Before this: realized rates. After: forwards. |
| `export` | bool | True | Write Excel workbook after computation. |
| `base_dir` | Path | `PNL_OIS_BASE` env | Root directory for default input/output paths. |
| `input_dir` | Path | auto | Directory containing Excel input files. |
| `output_dir` | Path | auto | Directory for output files. |
| `funding_source` | str | `"ois"` | Funding rate for CoC: `"ois"` (OIS curve) or `"coc"` (deal-level CocRate). |

### Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pnlData` | DataFrame | Deal-level data from MTD parser |
| `scheduleData` | DataFrame | Echeancier (nominal schedule) |
| `wirpData` | DataFrame | WIRP rate expectations |
| `irsStock` | DataFrame | IRS derivatives stock |
| `pnlAll` | DataFrame | Final P&L in wide format (months as columns) |
| `pnlAllS` | DataFrame | Final P&L in stacked/long format |

## Core Formula

### Daily P&L (BOOK1)

```
PnL_daily = Nominal * (OIS_fwd - RateRef) / MM
```

Where:
- `Nominal` = outstanding amount for the day (from echeancier schedule)
- `OIS_fwd` = OIS forward rate for that day and currency
- `RateRef` = deal reference rate (see [Rate Resolution](#rate-resolution))
- `MM` = day count divisor (360 or 365 per ISDA 2006 section 4.16)

### Monthly Aggregation

Daily P&L is summed to monthly. Rates are nominal-weighted averages.

```
PnL_month = SUM(PnL_daily)  for all days in month
Nominal_month = AVG(Nominal_daily)  over calendar days
OISfwd_month = WAVG(OIS_daily, Nominal_daily)
RateRef_month = WAVG(RateRef_daily, Nominal_daily)
```

## Rate Resolution

Each deal's reference rate depends on its product type:

| Product | Rate Column | Description |
|---------|------------|-------------|
| `IAM/LD` | `EqOisRate` | Equivalent OIS rate (BD-1 rate) |
| `BND` | `YTM` | Yield to maturity (after credit spread subtraction) |
| `FXS` | `EqOisRate` | Equivalent OIS rate |
| `IRS` | `Clientrate` | Contractual interest rate |
| `IRS-MTM` | `Clientrate` | Contractual interest rate |
| `HCD` | `Clientrate` | Contractual interest rate |

For floating-rate deals, the rate comes from the reference curve (SARON, ESTR, SOFR, SONIA) with lookback shift applied for SARON (2 BD) and SONIA (5 BD).

## Date Grid

The engine builds a daily calendar grid from the first echeancier month to 60 months forward:

```python
days = build_date_grid(start, months=60)  # daily pd.DatetimeIndex
```

All matrices are `(n_deals x n_days)` arrays aligned to this grid.

## Alive Mask

A boolean `(n_deals x n_days)` mask marks where each deal is alive:

```
alive[i, j] = (day[j] >= max(ValueDate[i], first_of_month(dateRun)))
            AND (day[j] <= MaturityDate[i])
```

This handles mid-month maturities correctly -- a deal maturing on the 15th contributes P&L only for days 1-15.

## Shock Scenarios

Three shock specifications:

| Shock | Description |
|-------|-------------|
| `"0"` | Base case -- no yield curve shift |
| `"50"` | +50 bps parallel shift |
| `"wirp"` | Market-implied rate path from WIRP expectations |

WIRP shock replaces OIS forward rates with central bank meeting expectations (forward-filled between meetings).

## Strategy Decomposition (IAS Hedge Accounting)

Deals with `Strategy IAS` designation are decomposed into 4 synthetic legs:

| Leg | Condition | P&L Formula |
|-----|-----------|-------------|
| `IAM/LD-NHCD` | IAM/LD exists in strategy | `Nominal_spread * (OIS - EqOisRate) * DIM / MM` |
| `IAM/LD-HCD` | IAM/LD exists in strategy | `Nominal_HCD * marginRate * DIM / MM` |
| `BND-NHCD` | BND exists in strategy | `Nominal_spread * (OIS - YTM) * DIM / MM` |
| `BND-HCD` | BND exists in strategy | `Nominal_HCD * marginRate * DIM / MM` |

Where `marginRate = EqOisRate + YTM - Clientrate_HCD`.

Direction filtering removes invalid leg/direction combinations:
- BND legs exclude Direction L and D
- IAM/LD legs exclude Direction B

## BOOK2: IRS MTM

IRS-MTM deals are valued via WASP `stockSwapMTM` (mark-to-market NPV). Pre-filtering:
- Maturity > dateRun
- Strategy IAS is null (strategy IRS are handled via the strategy path)

Falls back to zero MTM when WASP is unavailable.

## Output Format

### Wide Format (`pnlAll`)

```
| Perimetre TOTAL | Deal currency | Product2BuyBack | Direction | Indice    | Shock | 2026-04 | 2026-05 | ... |
|-----------------|---------------|-----------------|-----------|-----------|-------|---------|---------|-----|
| CC              | CHF           | IAM/LD          | L         | PnL       | 0     | -12345  | -11234  | ... |
| CC              | CHF           | IAM/LD          | L         | Nominal   | 0     | 5000000 | 4800000 | ... |
| CC              | CHF           | IAM/LD          | L         | CoC_Simple| 0     | 8234    | 7890    | ... |
```

### Indice Rows

| Indice | Aggregation | Description |
|--------|-------------|-------------|
| `Nominal` | average | Average daily nominal for the month |
| `OISfwd` | weighted avg | Nominal-weighted OIS forward rate |
| `PnL` | sum | Total P&L for the month |
| `RateRef` | weighted avg | Nominal-weighted reference rate |
| `GrossCarry` | sum | Interest income: `SUM(Nom * Rate * d_i / D)` |
| `FundingCost` | sum | Funding cost: `SUM(Nom * Funding * d_i / D)` |
| `CoC_Simple` | sum | `GrossCarry - FundingCost` |
| `CoC_Compound` | sum | `Nom_avg * [PROD(1 + r*d/D) - PROD(1 + f*d/D)]` |
| `FundingRate` | weighted avg | Nominal-weighted average funding rate |

### Stacked Format (`pnlAllS`)

7-level MultiIndex: `(Perimetre TOTAL, Deal currency, Product2BuyBack, Direction, Indice, Month, Shock)` with a single `Value` column.

## Serialization

```python
from cockpit.engine.pnl.forecast import save_pnl, load_pnl, compare_pnl

# Save/load via dill
path = save_pnl(pnl)
loaded = load_pnl(path)

# Day-over-day comparison
delta = compare_pnl(new_pnl, prev_pnl)
# Returns wide format with Level (Value_new, Value_prev, Delta)
```
