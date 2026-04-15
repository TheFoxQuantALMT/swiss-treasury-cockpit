---
  Review this project from a Quant specialist perspective. Launch 3 agents in parallel:

  **Agent 1 — Calculation Correctness**
  Review all files under src/pnl_engine/ and src/cockpit/engine/pnl/. Check:
  - Day count conventions (ACT/360 vs ACT/365, 365 vs 365.25)
  - Discounting formulas (EVE, KRD, convexity, reverse stress)
  - Compounding (SARON ISDA 2021 §6.9, CoC_Compound)
  - NMD decay/beta math, replication NNLS, CPR survival factors
  - Sign conventions (Direction D/L vs Amount sign, hedge legs)
  - Boundary conditions (zero nominal, empty arrays, division by zero)
  - BCBS 368 compliance (scenario interpolation, outlier test thresholds)
  Report each finding as: file:line, severity (high/medium/low), what's wrong, what the fix should be.

  **Agent 2 — UX & Reliability**
  Review src/cockpit/commands/, src/cockpit/data/, src/cockpit/pnl_dashboard/charts/. Check:
  - Silent failures: bare except, swallowed errors, missing logging
  - Data validation: missing columns handled, empty DataFrame guards, type coercion
  - User feedback: progress indicators, error messages, graceful degradation
  - Parser robustness: column name mismatches, encoding, date parsing edge cases
  - Dashboard data contracts: has_data flags, empty-state returns, NaN handling
  Report each finding as: file:line, severity, what's wrong, what the fix should be.

  **Agent 3 — Code Structure & Maintainability**
  Review the full src/ tree. Check:
  - Duplicated logic (same calculation in multiple places)
  - Unused imports, dead code, unreachable branches
  - Inconsistent patterns (e.g., different null-checking styles for same type)
  - Missing type hints on public functions
  - Config values hardcoded instead of using config.py
  - Mutable default arguments, input mutation
  Report each finding as: file:line, severity, what's wrong, what the fix should be.

  For ALL agents: do NOT report style-only issues (naming, docstrings, comments). Only report things that affect correctness, reliability, or maintainability.     
  Verify each finding before reporting — check that the "bug" isn't handled elsewhere. Sort findings by severity (high first).

  ---
  Tips for using it:
  - Run it periodically (e.g., after each feature wave) to catch regressions
  - After getting results, ask "What is the best way to fix all?" to get a batched fix plan
  - The 3-agent structure avoids context overload — each agent focuses on its domain
  - The "verify before reporting" instruction reduces false positives significantly