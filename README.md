# Swiss Treasury Cockpit

A daily pipeline for treasury risk monitoring that fetches market data, runs a P&L engine with rate shock scenarios, scores per-currency risk, and renders an interactive HTML dashboard.

## Pipeline

The cockpit runs as a 4-stage pipeline, with each stage producing dated JSON intermediates:

```
fetch  ──>  compute  ──>  analyze (optional)  ──>  render
```

| Stage | What it does | Output |
|-------|-------------|--------|
| **fetch** | Pulls rates, FX, energy, deposits from FRED, ECB, SNB, Yahoo Finance | `{date}_macro_snapshot.json` |
| **compute** | Runs P&L engine across shock scenarios, builds portfolio snapshot, scores currencies, checks alert thresholds | `{date}_pnl.json`, `{date}_portfolio.json`, `{date}_scores.json` |
| **analyze** | Generates an LLM daily brief via local Ollama agents (DeepSeek-R1 analyst + Qwen reviewer) | `{date}_brief.json` |
| **render** | Assembles a tabbed HTML cockpit with Plotly charts | `output/{date}_cockpit.html` |

Each stage is independent — you can re-run `render` without re-fetching, or skip `analyze` entirely if Ollama is not available.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- Optional: [Ollama](https://ollama.com/) for LLM daily briefs
- Optional: FRED API key (set `FRED_API_KEY` in `.env`)

## Installation

```bash
uv sync
```

For LLM agent support:

```bash
uv sync --extra agents
```

## Usage

```bash
# Run the full pipeline
uv run cockpit run-all --date 2026-04-04

# Or run individual stages
uv run cockpit fetch --date 2026-04-04
uv run cockpit compute --date 2026-04-04 --input-dir path/to/excel/files
uv run cockpit analyze --date 2026-04-04
uv run cockpit render --date 2026-04-04

# Dry run (fetch/compute/analyze without writing output)
uv run cockpit fetch --date 2026-04-04 --dry-run
```

The `--input-dir` flag for `compute` points to a directory containing the Excel input files (MTD deals, echeancier schedules, WIRP rate expectations, IRS stock, reference table).

## Dashboard Tabs

The rendered HTML cockpit contains 5 tabs:

1. **Macro Overview** — Currency risk scorecards (Calm/Watch/Action), central bank rates, triggered alerts
2. **FX & Energy** — FX spot history with alert bands, Brent and EU gas charts, scenario overlays
3. **P&L** — Interest rate P&L by currency and shock scenario (0bp, +50bp, WIRP-implied)
4. **Portfolio** — Liquidity ladder, position aggregation by currency/rating/HQLA, counterparty exposure
5. **Daily Brief** — LLM-generated market commentary (when available)

## Data Sources

| Source | Data | Protocol |
|--------|------|----------|
| FRED | Fed funds rate, CPI, GDP, unemployment | REST API |
| ECB | ECB rates, EUR/CHF | SDMX API |
| SNB | Sight deposits, SNB policy rate | SDMX API |
| Yahoo Finance | USD/CHF, GBP/CHF, Brent, EU gas, VIX | yfinance |

All fetchers run concurrently with circuit breakers. If a source fails, the pipeline falls back to the most recent archived snapshot.

## P&L Engine

The engine computes daily P&L as `Nominal × (OIS - RateRef) × d_i / MM` across a 60-month forward date grid, then aggregates to monthly. `d_i` is the calendar-day weight per fixing (1 on weekdays, 3 for Friday → Monday) built from the Swiss business calendar; `MM` is 360 for CHF/EUR/USD (ACT/360) or 365 for GBP (ACT/365). `Nominal` is **already signed** by the [direction convention](docs/pnl-engine.md#direction-convention) — assets (L/B) are negative, liabilities (D/S) are positive — so the P&L sign falls out naturally.

It runs three shock scenarios by default:

- **0bp** — no shift (base case)
- **+50bp** — parallel yield curve shift
- **WIRP** — market-implied rate path from WIRP expectations

`--shocks extended` adds the 6 BCBS 368 non-parallel rate shocks (parallel ±200bp, short ±300bp, steepener, flattener) with tenor-dependent interpolation. Deals with IAS hedge designations are decomposed into 4 synthetic strategy legs. When the WASP rate curve library is unavailable, the engine builds mock forward curves from WIRP data.

## Scoring

Deterministic per-currency risk scores (0-100) across four indicator families:

- **Inflation** — CPI trends, breakevens
- **Policy** — Central bank rates, forward guidance
- **Liquidity** — Sight deposits, money market conditions
- **Growth** — GDP, employment indicators

Composite scores map to labels: **Calm** (0-45), **Watch** (46-70), **Action** (71-100).

## Documentation

Full documentation is available in [`docs/`](docs/index.md):

- [Architecture](docs/architecture.md) -- System design, data flow, module structure
- [Installation](docs/installation.md) -- Requirements, setup, environment variables
- [CLI Reference](docs/cli.md) -- All 11 commands, options, examples
- [P&L Engine](docs/pnl-engine.md) -- Daily P&L, direction convention, strategy legs, BCBS 368
- [CoC Decomposition](docs/coc-decomposition.md) -- Simple vs compounded carry, formulas
- [Data Models](docs/data-models.md) -- Canonical Deal, RFRIndex, MarketData
- [Data Ingestion](docs/data-ingestion.md) -- Fetchers, parsers, DataManager, circuit breakers
- [Matrices & Curves](docs/matrices-curves.md) -- Numpy array construction, OIS curves, WASP integration
- [Scoring & Alerts](docs/scoring-alerts.md) -- Risk scoring, threshold alerts
- [Portfolio Snapshot](docs/portfolio-snapshot.md) -- Liquidity ladder, positions, counterparty exposure
- [Rendering](docs/rendering.md) -- 5-tab macro cockpit + 36-tab P&L dashboard
- [LLM Agents](docs/llm-agents.md) -- Analyst, reviewer, reporter for daily briefs
- [Configuration](docs/configuration.md) -- YAML-based config, constants, thresholds
- [Regulatory Reference](docs/regulatory-reference.md) -- ISDA, IFRS 9, BCBS 368, FINMA standards
- [Testing](docs/testing.md) -- Test structure, fixtures, running tests

## Testing

```bash
uv run pytest
```

## Project Structure

```
src/
  cockpit/
    cli.py              # CLI entry point — 11 commands (fetch, compute, ...)
    commands/           # One module per CLI command (fetch, compute, render, ...)
    config.py           # All constants and thresholds
    config_loader.py    # YAML-based runtime config (cockpit.config.yaml) with caching
    calendar.py         # Swiss business day calendar (10 holidays, Easter algorithm)
    decisions.py        # ALCO decision audit trail (JSONL append-only)
    data/
      manager.py        # Concurrent data fetching orchestrator
      quality.py        # Data quality checks (match rates, orphans, staleness)
      fetchers/         # FRED, ECB, SNB, yfinance async fetchers (circuit-breaker)
      parsers/          # Excel parsers (MTD, echeancier, WIRP, IRS stock, NMD,
                        #   limits, budget, scenarios, custom_scenarios, ...)
    engine/
      models.py         # Canonical Deal, RFRIndex, MarketData
      pnl/              # Vectorized P&L engine (forecast, engine, matrices, curves,
                        #   pnl_explain, forecast_tracking)
      scoring/          # Deterministic currency risk scoring
      alerts/           # Threshold-based alert system
      snapshot/         # Portfolio snapshot (enrichment, ladder, positions, counterparty)
      comparison.py     # Day-over-day delta computation
    agents/             # LLM daily brief (analyst, reviewer, reporter) — optional
    pnl_dashboard/      # 36-tab ALM/treasury dashboard
      renderer.py       # Jinja2 HTML assembly
      charts/           # 8-submodule chart builder package + orchestrator
      templates/        # Per-tab HTML partials + _macros.html
    render/             # 5-tab macro cockpit (Jinja2 + Plotly)
    export/             # Excel (openpyxl), PDF (weasyprint/pdfkit) exporters
    integrations/       # Notion export (MCP), FINMA peer benchmark
  pnl_engine/           # Standalone analytics modules (EVE, NMD, basis_risk,
                        #   reverse_stress, replication, saron, snb_reserves,
                        #   hedge_optimizer, locked_in_nii, what_if, ...)
data/                   # JSON intermediates (gitignored except archive/)
output/                 # Rendered dashboards (gitignored)
```
