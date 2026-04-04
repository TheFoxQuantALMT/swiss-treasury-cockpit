# Regulatory Reference

This document maps each regulatory standard to where and how it is applied in the codebase.

## Standards Applied

| Standard | Full Name | Relevance |
|----------|-----------|-----------|
| ISDA 2006 section 4.16 | Day Count Fraction | Day count conventions per instrument type |
| ISDA 2021 section 6.9 | Compounding in Arrears | RFR compounding formula with d_i weights |
| IFRS 9.5.4.1 | Interest Revenue | Effective interest rate method |
| IFRS 9.B5.4.5 | EIR Approximation | Simple carry as management approximation |
| BCBS 368 section 3.2 | IRRBB NII | Interest rate risk in the banking book |
| SNB Working Group | SARON Convention | 2 business day lookback |
| BoE Working Group | SONIA Convention | 5 business day lookback |

---

## ISDA 2006 section 4.16: Day Count Conventions

**What it specifies:** The method for calculating the day count fraction in interest computations.

**Where applied:**
- `src/cockpit/engine/models.py` -- `DayCountConvention` enum, `PRODUCT_DAY_COUNT` mapping, `get_day_count()` function
- `src/cockpit/engine/pnl/matrices.py` -- `build_mm_vector()` uses product-aware day count

**How applied:**

Day count is per instrument type, not just per currency:

| Currency | Money Market (IAM/LD, IRS, FXS, HCD) | Bonds (BND) |
|----------|---------------------------------------|-------------|
| CHF | Act/360 | 30/360 |
| EUR | Act/360 | 30/360 |
| USD | Act/360 | 30/360 |
| GBP | Act/365 Fixed | Act/365 Fixed |

The divisor `D` (360 or 365) is used in:
- Daily P&L: `Nominal * (OIS - RateRef) / D`
- Simple carry: `SUM(Nominal * Rate * d_i / D)`
- Compounded carry: `PROD(1 + r_i * d_i / D)`

---

## ISDA 2021 section 6.9: Compounding in Arrears

**What it specifies:** The formula for compounding Risk-Free Rates (RFR) over an accrual period.

**Where applied:**
- `src/cockpit/engine/pnl/engine.py` -- `aggregate_to_monthly()`, CoC_Compound calculation
- `src/cockpit/engine/pnl/matrices.py` -- `build_accrual_days()` computes d_i weights

**Formula:**

```
Compounded Rate = [PROD(1 + r_i * d_i / D) - 1] * D / SUM(d_i)
```

Where:
- `r_i` = RFR fixing for period i (with lookback shift for SARON/SONIA)
- `d_i` = calendar days in period i (1 for weekdays, 3 for Fri->Mon)
- `D` = day count basis (360 or 365)

**Applied to CoC:**

```
CoC_Compound = Nom_avg * [PROD(1 + RateRef_i * d_i / D)
                        - PROD(1 + Funding_i * d_i / D)]
```

**Key implementation details:**
- Weekend compounding: `d_i = 3` for Friday (Fri, Sat, Sun accrued to Friday's rate)
- Holiday handling: `d_i` = calendar day difference (currently Sat/Sun convention only; full holiday calendar via `BusinessDayCalendar` is supported in the data model)
- Last day of grid: if Friday, `d_i = 3` (assumed next fixing is Monday)

---

## IFRS 9.5.4.1 / 9.B5.4.5: Interest Revenue and EIR

**What it specifies:**
- 9.5.4.1: Interest revenue shall be calculated using the effective interest rate (EIR) method
- 9.B5.4.5: For floating-rate instruments, the EIR can be approximated by periodic recalculation

**Where applied:**
- `src/cockpit/engine/pnl/engine.py` -- GrossCarry calculation
- Simple CoC is labeled as "IFRS 9.B5.4.5 management approximation"

**How applied:**

The simple carry `SUM(Nom * Rate * d_i / D)` is the linear approximation of interest income. It equals the EIR method when:
- The accrual period is short (intra-month)
- Rates are low (compounding cross-term is negligible)

The compounded carry provides the geometrically correct figure for comparison.

---

## BCBS 368 section 3.2: IRRBB NII Sensitivity

**What it specifies:** Requirements for measuring Net Interest Income (NII) sensitivity to interest rate changes.

**Where applied:**
- Shock scenarios: `["0", "50", "wirp"]` apply parallel yield curve shifts
- CoC_Simple and CoC_Compound provide NII decomposition under each shock

**How applied:**

The P&L engine runs all three shock scenarios, producing CoC measures under each. The difference between shock=0 (base) and shock=50 (+50 bps) gives the NII sensitivity to a parallel rate shift:

```
NII_sensitivity = CoC(shock=50) - CoC(shock=0)
```

This is a subset of the full IRRBB NII calculation (which also includes repricing risk, basis risk, and optionality).

---

## SNB Working Group: SARON Convention

**What it specifies:** The observation shift (lookback) convention for SARON-based instruments.

**Where applied:**
- `src/cockpit/config.py` -- `LOOKBACK_DAYS = {"CHF": 2, ...}`
- `src/cockpit/engine/models.py` -- `RFR_REGISTRY["SARON"].lookback_days = 2`
- `src/cockpit/engine/pnl/matrices.py` -- `build_rate_matrix()` applies 2-BD lookback for CHF

**How applied:**

For CHF floating-rate deals, the rate on accrual day T uses the SARON fixing from T-2 business days. This shifts the observation period so that rates are known before the accrual period begins.

```python
# In build_rate_matrix:
lookback = LOOKBACK_DAYS.get(currency, 0)  # CHF -> 2
if lookback > 0:
    shifted_dates = day_dates - np.timedelta64(lookback, "D")
    sorter = np.searchsorted(curve_dates, shifted_dates, side="right") - 1
```

---

## BoE Working Group: SONIA Convention

**What it specifies:** The observation shift (lookback) convention for SONIA-based instruments.

**Where applied:**
- `src/cockpit/config.py` -- `LOOKBACK_DAYS = {..., "GBP": 5}`
- `src/cockpit/engine/models.py` -- `RFR_REGISTRY["SONIA"].lookback_days = 5`
- `src/cockpit/engine/pnl/matrices.py` -- `build_rate_matrix()` applies 5-BD lookback for GBP

**How applied:**

Same mechanism as SARON, but with 5 business day lookback for GBP floating-rate deals.

---

## WASP Carry Indices

The WASP library uses different curve indices for OIS forward rates and carry-compounded rates:

| Currency | OIS Index | Carry Index | Regulatory Basis |
|----------|-----------|-------------|-----------------|
| CHF | CHFSON | CSCML5 | SNB/ISDA convention |
| EUR | EUREST | ESAVB1 | ECB/ISDA convention |
| USD | USSOFR | USSOFR | Same (Fed convention) |
| GBP | GBPOIS | GBPOIS | Same (BoE convention) |

The carry-compounded function `load_carry_compounded()` uses the carry indices, while `load_daily_curves()` uses the OIS indices. This distinction is important for validation: the internal compounding implementation should match WASP's `carryCompounded()` function within 0.01 bps.

---

## IAS Hedge Accounting

**What it specifies:** IAS 39 / IFRS 9 hedge accounting designation for interest rate hedges.

**Where applied:**
- `src/cockpit/engine/pnl/engine.py` -- `compute_strategy_pnl()` decomposes hedge-designated deals into 4 legs

**How applied:**

Deals with `Strategy IAS` designation are split into:
1. **NHCD (Non-Hedge Carrying Debt):** P&L = `Nominal * (OIS - Rate) / MM` (standard formula)
2. **HCD (Hedge Carrying Debt):** P&L = `Nominal * marginRate / MM` (no OIS subtraction)

Where `marginRate = EqOisRate + YTM - Clientrate_HCD`.

Direction filtering ensures valid combinations:
- BND legs: exclude Lend (L) and Deposit (D) directions
- IAM/LD legs: exclude Borrow (B) direction
