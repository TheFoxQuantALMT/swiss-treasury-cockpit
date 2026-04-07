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
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels --shocks extended
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels --format xlsx
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels --format all  # html + xlsx + pdf
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels --custom-scenarios path/to/custom_scenarios.xlsx
uv run cockpit what-if --date 2026-04-04 --input-dir path/to/excels --product IAM/LD --currency CHF --amount 50000000 --rate 0.025 --direction D --maturity 5
uv run cockpit decision record --topic "NII Sensitivity" --description "Reduce CHF duration" --priority high --owner "ALM"
uv run cockpit decision list --month 2026-04
uv run cockpit decision update --date 2026-04-06 --topic "NII Sensitivity" --status closed
uv run cockpit export-notion --date 2026-04-04 --input-dir path/to/excels --parent-page-id <notion-page-id>
uv run cockpit backfill --from 2026-03-01 --to 2026-04-04 --input-dir path/to/excels
uv run cockpit validate --input-dir path/to/excels

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

- **`pnl_dashboard/`** — Dedicated P&L dashboard (35 tabs). Uses Jinja2 + Chart.js with shared `_macros.html` (kpi_card, chart_container, data_table, metric_badge, empty_state).
  - **Charts package** (`charts/`): Split into 8 submodules — `core.py` (Summary, CoC, P&L Series, Sensitivity, Strategy, Book2, Curves), `risk.py` (FX Mismatch, Repricing Gap, Counterparty, Alerts, EVE, Limits), `attribution.py` (FTP, Liquidity, NMD Audit, ALCO, Budget, Attribution, Forecast Tracking), `profitability.py` (Hedge Effectiveness, NII-at-Risk, Deal Explorer, Fixed/Float, NIM), `structure.py` (Maturity Wall, Trends, Regulatory), `scenarios.py` (Risk Cube, Deposit Behavior, Scenario Studio, Hedge Strategy), `monitoring.py` (ALCO Decision Pack, Data Quality, Basis Risk, SNB Reserves, Peer Benchmark, NMD Backtest), `orchestrator.py` (main entry point + enrichment wiring).
  - **Tab list**: ALCO Risk Summary (Decision Pack, exec summary, decisions required), Summary (with Locked-in NII KPI), CoC Decomposition, P&L Series, Shock Sensitivity (with sensitivity explain), EVE (IRRBB outlier test, tenor ladder, convexity/gamma), NII-at-Risk (parametric EaR), Repricing Gap, FX Mismatch, NMD Audit Trail (with replication portfolio), Deposit Behavior Intelligence (beta validation, beta sensitivity ±0.1, concentration), Risk Cube (heatmaps), Regulatory Scorecard, Budget vs Actual, P&L Attribution (waterfall), Forecast Tracking, Strategy IAS, Counterparty, Hedge Effectiveness (scenario cross-ref), Hedge Strategy Optimizer (with DV01-based hedge recommendations), NIM & Profitability (Jaws), Fixed/Float Mix, Deal Explorer, Maturity Wall, Scenario Studio (NII+ΔEVE ranking, reverse stress, decision matrix), FTP & Business Unit, Liquidity Forecast, Basis Risk (spread compression sensitivity), SNB Reserves (2.5% compliance), Peer Benchmark (FINMA aggregates), NMD Backtest (placeholder), BOOK2 MTM, Rate Curves, Historical Trends, Alerts, Data Quality.
- **`render/`** — Jinja2 HTML renderer with 5 tab templates (macro, FX/energy, P&L, portfolio, brief) + Plotly charts
- **`config.py`** — All constants, loaded from `config_loader.py` which reads `config/cockpit.config.yaml` with deep-merge over defaults
- **`config_loader.py`** — YAML-based runtime config with caching (`load_config()`, `reset_cache()`)
- **`calendar.py`** — Swiss business day calendar (10 holidays, Easter algorithm, numpy busday)
- **`decisions.py`** — ALCO decision audit trail (JSONL append-only store)
- **`data/quality.py`** — Data quality checks (match rates, orphan deals, field coverage, rate staleness)
- **`integrations/`** — External system connectors
  - `notion_export.py`: Push ALCO Decision Pack to Notion via MCP
  - `peer_benchmark.py`: FINMA aggregate IRRBB statistics comparison
- **`export/`** — Output format exporters
  - `excel_export.py`: Multi-sheet Excel workbook (openpyxl)
  - `pdf_export.py`: PDF via weasyprint/pdfkit

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
- **Liquidity Forecast**: Daily (90d) + monthly cash flow projections per deal. Same wide format as rate_schedule.xlsx. Powers the Liquidity Forecast tab with inflow/outflow bars, cumulative gap, survival horizon, and top maturing deals.
- **Basis Risk**: Spread compression sensitivity by product and currency (±50bp shocks) in `pnl_engine/basis_risk.py`.
- **CPR (Prepayment)**: Monthly survival factor `(1-CPR)^(1/12)` for fixed-rate mortgages in `pnl_engine/prepayment.py`.
- **Reverse Stress Test**: Bisection search for the shock level that breaches NII limit or ΔEVE/Tier1 threshold in `pnl_engine/reverse_stress.py`.
- **Replication Portfolio**: Least-squares fit of NMD behavioral cashflows to bullet bonds at standard tenors in `pnl_engine/replication.py`.
- **SARON Compounding**: ISDA 2021 compounded-in-arrears with 2-day lookback per SNB convention in `pnl_engine/saron.py`.
- **SNB Reserves**: 2.5% minimum on CHF sight liabilities with HQLA deduction in `pnl_engine/snb_reserves.py`.
- **Hedge Optimizer**: DV01-based IRS notional recommendation per currency in `pnl_engine/hedge_optimizer.py`.
- **Locked-in NII**: Fixed-rate deal NII as percentage of total (certainty metric) in `pnl_engine/locked_in_nii.py`.
- **Sensitivity Explain**: Waterfall decomposition of sensitivity change into drivers in `pnl_engine/sensitivity_explain.py`.
- **What-If Simulator**: Incremental NII + EVE impact of a hypothetical deal in `pnl_engine/what_if.py`.

### Data Flow

Input Excel files (MTD, echeancier, reference_table, WIRP, IRS stock) are parsed by `data/parsers/`. The P&L engine joins deals to echeancier by `(Dealid, Direction, Currency)`, expands nominal schedules to daily arrays, and runs vectorized computation across a 60-month date grid.

### Optional ALM Input Files

All optional — auto-discovered by `cmd_render_pnl()` via glob patterns:

| File | Parser | Description |
|------|--------|-------------|
| `budget.xlsx` | `parse_budget()` | Monthly NII budget per currency |
| `scenarios.xlsx` | `parse_scenarios()` | BCBS 368 tenor-dependent rate shocks |
| `nmd_profiles.xlsx` | `parse_nmd_profiles()` | NMD behavioral decay profiles |
| `limits.xlsx` | `parse_limits()` | Board-approved NII/EVE limits |
| `alert_thresholds.xlsx` | `parse_alert_thresholds()` | Per-currency alert threshold overrides |
| `liquidity_schedule.xlsx` | `parse_liquidity_schedule()` | Daily (90d) + monthly cash flow projections per deal |
| `custom_scenarios.xlsx` | `parse_custom_scenarios()` | User-defined stress tests (tenor × scenario grid) |

Note: FTP (Funds Transfer Pricing) is a column (`FTP`) in `deals.xlsx`, not a separate file. It contains per-deal FTP rates in decimal.

### Key Standalone Modules under `src/pnl_engine/`

The P&L engine package contains specialized analytics modules that are wired into the dashboard orchestrator:

- `basis_risk.py` — NII sensitivity to spread compression per product/currency
- `prepayment.py` — CPR model for fixed-rate mortgages (monthly survival factor)
- `reverse_stress.py` — Bisection search for breach shock level (NII limit or ΔEVE/Tier1)
- `replication.py` — Least-squares bullet bond replication of NMD cashflows
- `saron.py` — ISDA 2021 SARON compounding with lookback shift
- `snb_reserves.py` — SNB minimum reserve (2.5% sight liabilities, HQLA deduction)
- `hedge_optimizer.py` — DV01-based IRS notional recommendation
- `locked_in_nii.py` — Fixed-rate NII certainty metric
- `sensitivity_explain.py` — Sensitivity change waterfall decomposition
- `what_if.py` — Incremental deal impact simulator
- `nmd_backtest.py` — Modeled vs actual runoff comparison (R²/RMSE/MAE)
- `scenarios.py` — BCBS 368 scenario interpolation engine
- `eve.py` — EVE discounting + KRD + IRRBB outlier test
- `nmd.py` — Behavioral decay model + beta sensitivity
