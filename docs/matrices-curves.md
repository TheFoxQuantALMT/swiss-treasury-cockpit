# Matrices & Curves

## Matrix Construction (`matrices.py`)

All P&L computation operates on `(n_deals x n_days)` numpy arrays aligned to a common daily date grid. This module builds those arrays.

### `build_date_grid(start, months=60) -> DatetimeIndex`

Creates a daily calendar grid from `start` for `months` months.

```python
days = build_date_grid(pd.Timestamp("2026-04-01"), months=60)
# -> DatetimeIndex from 2026-04-01 to 2031-03-31, daily frequency
```

### `expand_nominal_to_daily(nominals_wide, days) -> ndarray`

Expands monthly nominal columns (from echeancier) to daily resolution.

- Input: DataFrame with columns like `"2026/04"`, `"2026/05"`, etc.
- Output: `(n_deals, n_days)` array where each day gets the nominal of its month.

### `build_alive_mask(deals, days, date_run=None) -> ndarray`

Boolean `(n_deals, n_days)` mask: True where a deal is alive.

```
alive[i, j] = (day[j] >= max(Valuedate[i], first_of_month(dateRun)))
            AND (day[j] <= Maturitydate[i])
```

Handles mid-month maturities: a deal maturing April 15 contributes only for days 1-15.

### `build_mm_vector(deals) -> ndarray`

Day count divisor per deal (ISDA 2006 section 4.16). Product-aware:

| Product | CHF/EUR/USD | GBP |
|---------|-------------|-----|
| BND | 360 (30/360) | 365 (Act/365) |
| IAM/LD, IRS, FXS, HCD | 360 (Act/360) | 365 (Act/365) |

When `Product` column exists, uses `get_day_count(product, currency).divisor`. Falls back to currency-only mapping otherwise.

### `build_accrual_days(days) -> ndarray`

Calendar days each fixing accrues for, per ISDA 2021 section 6.9.

Returns `(n_days,)` array of `d_i` weights:
- Weekday to weekday: `d_i = 1`
- Between non-consecutive days: actual calendar day difference
- Last day of grid, if Friday: `d_i = 3` (Fri -> Mon convention)

This is critical for correct compounding: Friday's rate must be weighted for 3 calendar days (Fri, Sat, Sun) in the compounding product.

### `build_rate_matrix(deals, days, ref_curves=None) -> ndarray`

Build `(n_deals, n_days)` reference rate matrix.

- **Fixed-rate deals:** broadcast `RateRef` across all days.
- **Floating-rate deals:** branch on `fixing_tenor_days` (computed upstream by `_resolve_rate_ref`):
  - **Tenor == 0 (overnight RFR)** — interpolate the forward curve daily, then apply the lookback shift:
    - SARON (CHF): 2 business day lookback (SNB Working Group)
    - SONIA (GBP): 5 business day lookback (BoE Working Group)
    - ESTR, SOFR: 0-day lookback (daily observation, no shift).
  - **Tenor > 0 (term floater, e.g. `SARON3M`, `ESTR6M`)** — hold the rate constant over each fixing period `[t_k, t_k + tenor)`:
    - For the segment containing today: use the contractual `current_fixing_rate` column from MTD.
    - For past/future segments: sample the forward curve at the fixing date `t_k = last_fixing + k·tenor`.
    - If `current_fixing_rate` is missing in the active segment, fall back to `RateRef` with a WARNING (may be wrong for IRS where `RateRef` reflects the fixed leg).
    - If fixing dates are entirely absent, degrade to the overnight branch with a WARNING.

The overnight lookback shift means the rate on accrual day T uses the fixing from T-N calendar days. Term floaters do not take a lookback — the fixing at `t_k` applies for the whole `[t_k, t_k + tenor)` window.

### Tenor inference precedence (`_resolve_rate_ref`)

`fixing_tenor_days` is derived in this order:

1. **Date diff:** `(next_fixing_date − last_fixing_date).days` when both columns are populated — this is authoritative and overrides the short-name suffix.
2. **Suffix regex:** `r"(\d+)([MWY])$"` on `Floating Rates Short Name` (e.g. `SARON3M` → 90, `EURIBOR6M` → 180, `ESTR1W` → 7).
3. **Default:** `0` (overnight / unknown).

### RFR-drop guard

Floating legs where `fixing_tenor_days == 0` AND `ref_index ∈ CURRENCY_TO_OIS.values()` are dropped: for these, `OIS − RefRate ≡ 0` and the echeancier V-leg was already removed, so they only pollute output with zero-nominal rows. Term floaters sharing the same base index (e.g. `SARON3M` → `CHFSON3M`) survive because their tenor is positive.

### `build_funding_matrix(deals, days, ois_matrix, funding_source="ois") -> ndarray`

Build `(n_deals, n_days)` funding rate matrix:

| Mode | Behavior |
|------|----------|
| `"ois"` | Returns `ois_matrix` directly (zero-copy) |
| `"coc"` | Broadcasts deal-level `CocRate` across all days |

## Curve Loading (`curves.py`)

### `load_daily_curves(date, indices, shock, mock_data=None) -> DataFrame`

Load daily forward rate curves. Three modes:

1. **WASP available:** Calls `wt.dailyFwdRate()` for each index in parallel (ThreadPoolExecutor)
2. **Mock data provided:** Uses the DataFrame directly
3. **Neither:** Raises `RuntimeError`

Returns DataFrame with columns: `Indice`, `Date`, `value`, `dateM` (period).

### `overlay_wirp(base, wirp) -> DataFrame`

Overlays WIRP (central bank meeting) expectations onto base OIS curves. WIRP rates are forward-filled between meeting dates.

### `load_carry_compounded(start, end, currency) -> float | None`

Load WASP carry-compounded rate for a period. Uses carry-specific indices:

| Currency | OIS Index | Carry Index |
|----------|-----------|-------------|
| CHF | CHFSON | **CSCML5** |
| EUR | EUREST | **ESAVB1** |
| USD | USSOFR | USSOFR |
| GBP | GBPOIS | GBPOIS |

Returns `None` if WASP is unavailable. Used for validation against internal compounding.

### `load_carry_compounded_series(start, end, currency) -> DataFrame | None`

Monthly carry-compounded series via WASP. Returns DataFrame with `[Date, Currency, CarryCompounded]` for each month-end from start to end.

### `CurveCache`

In-memory cache for forward curves. Keyed by `(type, date, shock)` tuples. Returns defensive copies to prevent mutation.

```python
cache = CurveCache()
cache.put(("ois", "2026-04-04", "0"), curves_df)
cached = cache.get(("ois", "2026-04-04", "0"))  # returns a copy
```

## WASP Integration

The engine uses WASP (`waspTools`) for:

1. **OIS forward curves:** `wt.dailyFwdRate(dateC, indice, startDay, endDay, Shock)`
2. **IRS MTM:** `wt.stockSwapMTM(irs_stock, calc_date, shock)`
3. **Carry compounding:** `wt.Fwd(startDate, endDate, indice, market)`

WASP is loaded from `WASP_TOOLS_PATH` environment variable. When unavailable, the engine uses:
- **Mock OIS curves** built from WIRP data (step function from meeting rates)
- **Zero MTM** for IRS positions
- **None** for carry comparison (tests skip gracefully)

### Market Ramps

WASP uses different market ramps for OIS and carry:
- OIS forward: `"MESA AGG MARKET"` (standard market ramp)
- Carry compounded: `"MESA MARKET ALMT"` (alternative ramp)
