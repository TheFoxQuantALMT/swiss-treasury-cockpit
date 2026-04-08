# Quant Audit Prompt — Run Until 0 Critical

Paste this into Claude Code. Run iteratively until the output reports 0 CRITICAL issues.

---

## The Prompt

```
Audit this codebase for CRITICAL quant errors using the taxonomy in CLAUDE.md § "Quant Audit Taxonomy".

## Process

1. **Scan** — Read every `.py` file under `src/pnl_engine/` and `src/cockpit/pnl_dashboard/charts/`. For each file, check against EVERY critical category:
   - Sign errors (direction, P&L, EVE cashflow)
   - Day count errors (divisor, accrual, year fraction)
   - Rate misuse (RateRef vs ClientRate)
   - Exponent/scaling (monthly↔annual, bp↔decimal)
   - Formula errors (discounting, missing terms, bisection)
   - Data flow errors (stale matrix, positional vs date alignment)

2. **Cross-check conventions** — Verify every module that references direction, day count, or rate type uses the canonical source from `pnl_engine/config.py`. Grep for hardcoded `["D", "B"]`, `["L", "S"]`, `/ 360`, `/ 365`, `/ 10000` and check each against the canonical convention.

3. **Verify formulas against docstrings** — For compute_eve, compute_daily_pnl, compute_strategy_pnl, compute_repricing_gap, compute_basis_risk, simulate_deal: read the docstring, then read the implementation, and flag any mismatch.

4. **Check test coverage** — For each CRITICAL-class function, verify a test exists that would catch a sign flip or scaling error. Flag untested critical paths.

## Output Format

For each issue found, output:

```
### [SEVERITY] Short title
**File:** path:line
**Category:** (sign | day_count | rate_misuse | scaling | formula | data_flow)
**Evidence:** the specific code and what's wrong
**Impact:** quantitative estimate (e.g., "inverts CHF 5bn mortgage P&L")
**Fix:** specific code change
```

Then output a summary table:

| Severity | Count | Fixed in this pass |
|----------|-------|--------------------|
| CRITICAL | N     | Y/N               |
| HIGH     | N     | Y/N               |

If CRITICAL = 0, output: "✅ CONVERGED — no critical quant errors found."

If CRITICAL > 0, fix all critical issues, run `uv run pytest`, and report results.
```

---

## How to Use

1. Run the prompt above in Claude Code
2. Claude will scan, find issues, fix CRITICAL ones, run tests
3. If CRITICAL > 0 were found and fixed, run the prompt again
4. Repeat until you see "CONVERGED"
5. Typically converges in 2-3 passes

## Why This Works

- **Taxonomy in CLAUDE.md** gives Claude permanent context about what matters.
  It won't waste time on style issues when regulatory correctness is at stake.
- **Explicit categories** force systematic scanning instead of ad-hoc reading.
  Each file is checked against 6 specific failure modes.
- **Cross-check step** catches convention drift (the #1 source of bugs in this
  codebase — direction mapping defined differently in 5 places).
- **Formula-vs-docstring step** catches silent semantic drift where code
  evolves but the formula description doesn't.
- **Test coverage step** prevents regression — if a critical formula has no
  test, the next refactor will silently break it.
- **Fix-and-verify loop** ensures convergence — each pass reduces the count.

## Extending It

Add domain-specific checks as you discover new failure modes:

```
# Add to the "Scan" step:
- NMD model: verify decay is applied continuously (not step-function at month boundaries)
- SARON lookback: verify shift is in business days, not calendar days
- Scenario interpolation: verify shift array is date-aligned to curve, not position-aligned
```

## Scheduling (optional)

Run this after every batch of changes:
```
/loop 0 "Run the quant audit prompt from prompts/quant-audit.md against the current codebase"
```

Or hook it to pre-commit:
```json
// .claude/settings.json
{
  "hooks": {
    "pre-commit": "uv run pytest -x -q && echo 'Tests pass'"
  }
}
```
