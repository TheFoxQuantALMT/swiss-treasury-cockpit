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

### Data Loading

`load_data()` supports two input layouts:

- **Ideal format:** `deals.xlsx` (unified BOOK1+BOOK2), `schedule.xlsx`, `wirp.xlsx`
- **Legacy format:** `*MTD*`, `*Echeancier*`, `*WIRP*`, `*IRS*` (separate files)

Ideal format is tried first (`*deals*` glob); falls back to legacy if not found. When a unified deals file is loaded, `_split_deals_by_book()` splits by `IAS Book`: BOOK1 rows go to `pnlData`, BOOK2 rows are adapted to WASP column format for `irsStock`.

### Key Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `pnlData` | DataFrame | BOOK1 deal-level data |
| `scheduleData` | DataFrame | Nominal schedule (monthly balances) |
| `wirpData` | DataFrame | WIRP rate expectations |
| `irsStock` | DataFrame | BOOK2 IRS stock (for WASP MTM) |
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

## Realized vs Forecast Split

When `dateRates` is provided, monthly P&L is split into Realized and Forecast components:

- **Realized:** days <= dateRates (rates are historical fixings)
- **Forecast:** days > dateRates (rates are forward projections)

For the current month (containing dateRates), three rows are produced per deal:
- `PnL_Type = "Total"` — full month
- `PnL_Type = "Realized"` — days up to dateRates
- `PnL_Type = "Forecast"` — days after dateRates

Past months have only `"Realized"` rows. Future months have only `"Forecast"` rows.

**Key invariant:** `Total = Realized + Forecast` for every (deal, month) combination.

When `date_rates=None` (backward compatibility), all rows have `PnL_Type = "Total"`.

The split applies to all metrics: PnL, Nominal, GrossCarry, FundingCost, CoC_Simple, CoC_Compound.

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
- BND legs exclude Direction L and D (loans/deposits are not bonds)
- IAM/LD legs exclude Direction B and S (bought/sold bonds are not money market)

## BOOK2: IRS MTM

IRS-MTM deals are valued via WASP `stockSwapMTM` (mark-to-market NPV). Pre-filtering:
- Maturity > dateRun
- Strategy IAS is null (strategy IRS are handled via the strategy path)

When WASP is unavailable, falls back to an analytical MTM approximation:

```
MTM ≈ sign × Notional × (ClientRate - OIS_proxy) × remaining_years
```

Where sign is +1 for RECEIVE, -1 for PAY. This is a first-order PV approximation adequate for dashboard display.

## BCBS 368 Scenarios

The engine supports 6 non-parallel tenor-dependent rate shock scenarios (`pnl_engine/scenarios.py`):

| Scenario | Short End | Long End |
|----------|-----------|----------|
| `parallel_up` | +200bp | +200bp |
| `parallel_down` | -200bp | -200bp |
| `short_up` | +300bp @ O/N | 0bp @ 20Y |
| `short_down` | -300bp @ O/N | 0bp @ 20Y |
| `steepener` | -100bp | +100bp |
| `flattener` | +100bp | -100bp |

Shifts are interpolated from BCBS standard tenor points (O/N, 3M, 6M, 1Y, 2Y, 3Y, 5Y, 10Y, 20Y, 30Y) to the daily date grid using `numpy.interp`. Applied per currency.

```python
engine.run_scenarios(scenarios_df)  # returns stacked DataFrame with Shock=scenario_name
```

## EVE (Economic Value of Equity)

BCBS 368 requires both NII (earnings) and EVE (economic value) measures. The EVE module (`pnl_engine/eve.py`) computes:

- **Base EVE**: PV of future cash flows (interest + principal) discounted at OIS forward rates
- **ΔEVE**: Change in EVE under each BCBS scenario
- **Modified Duration**: Weighted-average time of discounted cash flows
- **Key Rate Duration (KRD)**: Sensitivity at each BCBS tenor point (1bp bump)

```python
engine.run_eve(scenarios=scenarios_df)
engine.eve_results      # per-deal EVE DataFrame
engine.eve_scenarios    # ΔEVE by scenario × currency
engine.eve_krd          # KRD at each tenor point
```

## NMD Behavioral Model

Non-Maturing Deposits (sight deposits) have no contractual maturity. The NMD module (`pnl_engine/nmd.py`) applies behavioral assumptions:

- **Decay profile**: `nominal(t) = nominal(0) × exp(-decay_rate × t)` — exponential runoff
- **Deposit beta**: `effective_rate = floor + beta × max(0, OIS - floor)` — partial rate passthrough
- **Behavioral maturity**: Used for repricing gap analysis instead of contractual maturity

Standard tiers (SNB/EBA convention):
- **Core**: stable, long behavioral maturity (5-7Y), low beta (0.3-0.5)
- **Volatile**: rate-sensitive, short maturity (1-2Y), high beta (0.7-0.9)
- **Term**: contractual maturity, beta=1.0

Profiles are loaded from `nmd_profiles.xlsx` and injected via `PnlEngine(nmd_profiles=...)`.

## Convexity / Gamma

Derived from the parallel ±200bp EVE scenarios on the dashboard:

```
Effective Duration = -(ΔEVE_up - ΔEVE_down) / (2 × EVE × Δr)
Convexity (γ)     = (ΔEVE_up + ΔEVE_down) / (EVE × Δr²)
```

Where Δr = 0.02 (200bp). Positive convexity means the portfolio benefits from large rate moves in either direction. Computed at total and per-currency level.

## Parametric Earnings-at-Risk (EaR)

Simplified parametric EaR estimated from BCBS scenario ΔNII deltas:

```
EaR 95% = μ - 1.645 × σ
EaR 99% = μ - 2.326 × σ
```

Where μ and σ are the mean and standard deviation of ΔNII across all BCBS scenarios. Assumes normal distribution. For more accurate tail risk, historical simulation with curve time series is recommended.

## FTP (Funds Transfer Pricing)

Per-deal internal transfer rate enabling a 3-way margin split:

| Margin | Formula | Interpretation |
|--------|---------|---------------|
| Client Margin | `ClientRate - FTP` | Spread earned from client pricing |
| ALM Margin | `FTP - OIS` | Spread earned from funding mismatch |
| Total NII | `ClientRate - OIS` | Sum of both margins |

FTP is a column (`FTP`) in `deals.xlsx` containing per-deal FTP rates in decimal. Aggregated by perimeter (CC/WM/CIB) for business unit profitability analysis.

## Liquidity Forecast

Daily (90-day) + monthly cash flow projections per deal, parsed from `liquidity_schedule.xlsx`. Same wide format as `schedule.xlsx` but with additional daily columns (`YYYY/MM/DD`). Powers:

- Inflow/outflow bars with cumulative gap line
- Survival horizon (first day cumulative net goes negative)
- Top 10 maturing deals in next 30 days

## P&L Explain

The P&L explain module (`cockpit/engine/pnl/pnl_explain.py`) decomposes ΔNII between two dates into actionable drivers:

| Driver | Formula / Logic |
|--------|----------------|
| Time / Roll-down | Residual after other effects (includes passage of time, curve roll) |
| New Deals | Sum P&L of deals entering the portfolio since prev date |
| Maturing Deals | Negative of prev P&L for deals that matured |
| Rate Effect | `Nom_prev × ΔOIS / MM` on existing portfolio |
| Spread Effect | `Nom_prev × ΔSpread / MM` (change in client-OIS margin) |

The waterfall reads: `Prev NII → +Time → +New → -Matured → +Rate → +Spread → Current NII`

Requires `--prev-date` flag to provide comparison baseline.

## Output Format

### Wide Format (`pnlAll`)

```
| Perimetre TOTAL | Deal currency | Product2BuyBack | Direction | Indice    | PnL_Type | Shock | 2026-04 | 2026-05 | ... |
|-----------------|---------------|-----------------|-----------|-----------|----------|-------|---------|---------|-----|
| CC              | CHF           | IAM/LD          | L         | PnL       | Total    | 0     | -12345  | -11234  | ... |
| CC              | CHF           | IAM/LD          | L         | PnL       | Realized | 0     | -4115   |         | ... |
| CC              | CHF           | IAM/LD          | L         | PnL       | Forecast | 0     | -8230   | -11234  | ... |
| CC              | CHF           | IAM/LD          | L         | Nominal   | Total    | 0     | 5000000 | 4800000 | ... |
| CC              | CHF           | IAM/LD          | L         | CoC_Simple| Total    | 0     | 8234    | 7890    | ... |
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

8-level MultiIndex: `(Perimetre TOTAL, Deal currency, Product2BuyBack, Direction, Indice, PnL_Type, Month, Shock)` with a single `Value` column.

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
