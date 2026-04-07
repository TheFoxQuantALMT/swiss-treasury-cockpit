# Quant Review — Fix Plan

_Planned: 2026-04-07. 22 issues, 5 waves. All complete._

---

## Wave 1: Day Count Foundation — DONE
- [x] **1a.** Wire `build_accrual_days()` to Swiss calendar
- [x] **1b.** EVE year fractions: 365.25 → 365.0 (ACT/365)
- [x] **1c.** Scenarios year fractions: 365.25 → 365.0
- [x] **1d.** SARON compounding: accept accrual_days (d_i) parameter
- [x] **1e.** Realized/forecast split: per-sub-period denominator

## Wave 2: EVE Fixes — DONE
- [x] **2a.** EVE principal return: only terminal maturity, not intermediate amortization
- [x] **2b.** KRD: BCBS piecewise-constant step bumps instead of Gaussian
- [x] **2c.** Reverse stress: optional convexity for quadratic ΔEVE

## Wave 3: Curve & NMD — DONE
- [x] **3a.** Rate matrix: np.interp linear interpolation instead of LOCF
- [x] **3b.** WIRP overlay: merge_asof with 2-day tolerance
- [x] **3c.** NMD decay: per-month boundary, broadcast to days
- [x] **3d.** Replication: active-set NNLS iteration (numpy only)

## Wave 4: Silent Failures — DONE
- [x] **4a.** render.py: classify exceptions, load summary counter
- [x] **4b.** mtd.py: log dropped row counts by category
- [x] **4c.** core.py: warn on NaN coercion
- [x] **4d.** All builders: enforce has_data in empty-state returns
- [x] **4e.** scenarios.py: warn on missing currency columns

## Wave 5: Structural — DONE
- [x] **5a.** orchestrator: auto-build matrices guard
- [x] **5b.** Config: already deduplicated (no change needed)
- [x] **5c.** Progress: step markers in compute/render
- [x] **5d.** Valid products moved to pnl_engine/config.py
- [x] **5e.** Don't mutate beta_sensitivity input dict
- [x] **5f.** Auto-clear cache on dateRates change

## Verification
- [x] Full test suite: 608 passed, 6 skipped
