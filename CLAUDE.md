# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Swiss Treasury Cockpit — a daily pipeline that fetches market data, runs a P&L engine with rate shock scenarios, scores currency risk, and renders an HTML dashboard. Optionally generates LLM-written daily briefs via local Ollama agents.

## Build & Run

```bash
# Install (requires Python 3.13+, uses uv)
uv sync

# Run full pipeline
uv run cockpit run-all --date 2026-04-04

# Individual steps
uv run cockpit fetch --date 2026-04-04
uv run cockpit compute --date 2026-04-04 --input-dir path/to/excels
uv run cockpit analyze --date 2026-04-04   # requires Ollama running locally
uv run cockpit render --date 2026-04-04

# Tests
uv run pytest                    # all tests
uv run pytest tests/test_cli.py  # single file
uv run pytest -k test_name       # single test by name
```

Optional dependency groups: `uv sync --extra agents` (Ollama agent framework), `uv sync --extra notion`.

## Architecture

The pipeline flows through 4 CLI stages, each reading/writing dated JSON files in `data/`:

```
fetch → {date}_macro_snapshot.json
compute → {date}_pnl.json, {date}_portfolio.json, {date}_scores.json
analyze → {date}_brief.json  (optional, needs Ollama)
render → output/{date}_cockpit.html
```

### Key modules under `src/cockpit/`

- **`data/`** — Market data ingestion
  - `manager.py`: `DataManager` orchestrates concurrent fetching (FRED, ECB, SNB, yfinance) with graceful degradation and archive fallback
  - `fetchers/`: Individual async fetchers with circuit breaker pattern
  - `parsers/`: Excel parsers for internal data (MTD deals, echeancier schedules, WIRP rate expectations, IRS stock, reference table)

- **`engine/`** — Computation core
  - `pnl/`: Vectorized P&L engine. `forecast.py` is the stateful entry point (`ForecastRatePnL`). `engine.py` has the functional core: daily P&L = `Nominal * (OIS - RateRef) / MM`, aggregated to monthly, with IAS hedge strategy decomposition into 4 synthetic legs. `matrices.py` builds the numpy arrays (nominal schedule, alive mask, rate matrix). `curves.py` handles OIS curve loading with WIRP mock fallback when WASP is unavailable.
  - `scoring/`: Deterministic 0-100 scoring per currency (CHF/EUR/USD/GBP) across families (inflation, policy, liquidity, growth) → Calm/Watch/Action labels
  - `alerts/`: Threshold-based alerts on FX bands, energy, deposits, daily moves
  - `snapshot/`: Portfolio snapshot assembly — enrichment → liquidity ladder → positions → counterparty aggregation
  - `comparison.py`: Day-over-day delta computation

- **`agents/`** — LLM daily brief generation (optional, requires `agent-framework` + Ollama)
  - `analyst.py`: Template-fill approach — Python pre-fills all numbers, LLM only writes `[INTERPRET]` bullets (prevents hallucination)
  - `reviewer.py`: Programmatic fact-checker + LLM reviewer with retry loop
  - `reporter.py`: Converts brief text to styled HTML

- **`pnl_dashboard/`** — Dedicated P&L dashboard (21 tabs): ALCO Risk Summary (with limit breach log), Summary, CoC, P&L Series, Sensitivity, EVE (with IRRBB outlier test, tenor ladder, convexity/gamma), NII-at-Risk (with parametric EaR), Repricing Gap, FX Mismatch, NMD Audit Trail, Budget vs Actual, Attribution/P&L Explain, Forecast Tracking, Strategy IAS, Counterparty, Hedge Effectiveness (with scenario cross-ref), FTP & Business Unit, Liquidity Forecast, BOOK2 MTM, Rate Curves, Alerts. Uses Jinja2 + Chart.js.
- **`render/`** — Jinja2 HTML renderer with 5 tab templates (macro, FX/energy, P&L, portfolio, brief) + Plotly charts
- **`config.py`** — All constants: OIS mappings, shock levels, FX alert bands, scoring thresholds, liquidity buckets, counterparty perimeters

### P&L Engine Concepts

- **Shocks**: `["0", "50", "wirp"]` — basis point parallel shifts of the yield curve. "wirp" uses market-implied rate expectations.
- **BCBS 368 Scenarios**: 6 non-parallel rate shocks (parallel ±200bp, short ±300bp, steepener, flattener) with tenor-dependent interpolation via `numpy.interp`. Defined in `pnl_engine/scenarios.py`.
- **EVE (Economic Value of Equity)**: PV of all future cash flows discounted at OIS. Computed per deal in `pnl_engine/eve.py`. Includes ΔEVE scenarios and Key Rate Duration (KRD) at BCBS tenor points.
- **NMD (Non-Maturing Deposits)**: Behavioral decay model for sight deposits in `pnl_engine/nmd.py`. Applies exponential decay (`exp(-decay × t)`) and deposit beta (partial rate passthrough) for deposits without contractual maturity. `apply_nmd_decay()` returns a match log for audit trail.
- **Convexity/Gamma**: Derived from parallel ±200bp EVE scenarios. Effective duration = -(ΔEVE_up - ΔEVE_down)/(2×EVE×Δr). Convexity = (ΔEVE_up + ΔEVE_down)/(EVE×Δr²).
- **Parametric EaR**: Earnings-at-Risk estimated from BCBS scenario ΔNII deltas assuming normal distribution. EaR = μ - zσ at 95%/99% confidence.
- **P&L Explain**: Waterfall decomposition of ΔNII between two dates in `cockpit/engine/pnl/pnl_explain.py`. Drivers: time/roll-down, new deals, maturing deals, rate effect, spread effect.
- **dateRun** vs **dateRates**: dateRun controls which deal data loads; dateRates controls where realized rates end and forwards begin.
- **Strategy IAS**: Deals with IAS hedge designation get decomposed into 4 legs (IAM/LD-NHCD, IAM/LD-HCD, BND-NHCD, BND-HCD) with direction filtering.
- **WASP**: External rate curve library. When unavailable, the engine builds mock curves from WIRP data (graceful degradation).
- **FTP (Funds Transfer Pricing)**: Per-deal internal transfer rate. Enables 3-way margin split: Client Margin (ClientRate - FTP), ALM Margin (FTP - OIS), Total NII = sum. Aggregated by perimeter (CC/WM/CIB) for business unit profitability.
- **Liquidity Forecast**: Daily (90d) + monthly cash flow projections per deal. Same wide format as schedule.xlsx. Powers the Liquidity Forecast tab with inflow/outflow bars, cumulative gap, survival horizon, and top maturing deals.

### Data Flow

Input Excel files (MTD, echeancier, reference_table, WIRP, IRS stock) are parsed by `data/parsers/`. The P&L engine joins deals to echeancier by `(Dealid, Direction, Currency)`, expands nominal schedules to daily arrays, and runs vectorized computation across a 60-month date grid.

### Optional ALM Input Files

All optional — auto-discovered by `cmd_render_pnl()` via glob patterns:

| File | Parser | Description |
|------|--------|-------------|
| `budget.xlsx` | `parse_budget()` | Monthly NII budget per currency |
| `scenarios.xlsx` | `parse_scenarios()` | BCBS 368 tenor-dependent rate shocks |
| `hedge_pairs.xlsx` | `parse_hedge_pairs()` | Hedge relationship designations |
| `nmd_profiles.xlsx` | `parse_nmd_profiles()` | NMD behavioral decay profiles |
| `limits.xlsx` | `parse_limits()` | Board-approved NII/EVE limits |
| `alert_thresholds.xlsx` | `parse_alert_thresholds()` | Per-currency alert threshold overrides |
| `liquidity_schedule.xlsx` | `parse_liquidity_schedule()` | Daily (90d) + monthly cash flow projections per deal |

Note: FTP (Funds Transfer Pricing) is a column (`FTP`) in `deals.xlsx`, not a separate file. It contains per-deal FTP rates in decimal.
