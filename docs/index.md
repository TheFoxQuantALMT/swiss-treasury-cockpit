# Swiss Treasury Cockpit Documentation

## Overview

Swiss Treasury Cockpit is a daily pipeline for treasury risk monitoring at a Swiss bank. It fetches market data from public sources, runs a vectorized P&L engine with rate shock scenarios (including BCBS 368), scores per-currency risk, and renders interactive HTML dashboards. The system supports multi-format export (HTML, Excel, PDF) and optional LLM-written daily briefs via local Ollama agents.

The system consolidates two internal projects:

- **economic-pnl-v2** -- P&L engine, portfolio snapshot, Excel parsers
- **macro-cbwatch** -- market data fetchers, scoring, alerts, LLM agents

The CLI exposes **11 commands**: `fetch`, `compute`, `analyze`, `render`, `render-pnl`, `run-all`, `backfill`, `validate`, `what-if`, `decision`, and `export-notion`.

## Documentation Index

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System design, data flow, module structure |
| [Installation](installation.md) | Requirements, setup, environment variables |
| [CLI Reference](cli.md) | All 11 commands, options, examples |
| [P&L Engine](pnl-engine.md) | Daily P&L, CoC decomposition, strategy legs, BOOK1/BOOK2 |
| [Data Models](data-models.md) | Canonical `Deal`, `RFRIndex`, `MarketData` dataclasses |
| [Matrices & Curves](matrices-curves.md) | Numpy array construction, OIS curves, WASP integration |
| [CoC Decomposition](coc-decomposition.md) | Simple vs compounded carry, regulatory basis, formulas |
| [Scoring & Alerts](scoring-alerts.md) | Deterministic risk scoring, threshold alerts |
| [Portfolio Snapshot](portfolio-snapshot.md) | Liquidity ladder, positions, counterparty exposure |
| [Data Ingestion](data-ingestion.md) | Fetchers, parsers, DataManager, circuit breakers |
| [LLM Agents](llm-agents.md) | Analyst, reviewer, reporter -- daily brief generation |
| [Rendering](rendering.md) | Jinja2 templates, 5-tab macro cockpit + 36-tab P&L dashboard |
| [Configuration](configuration.md) | YAML-based config (`config_loader.py`), constants, thresholds |
| [Testing](testing.md) | Test structure, fixtures, running tests |
| [Regulatory Reference](regulatory-reference.md) | ISDA, IFRS 9, BCBS 368, FINMA standards applied |

## Quick Start

```bash
# Install (requires Python 3.13+, uses uv)
uv sync

# Run the full pipeline
uv run cockpit run-all --date 2026-04-04

# Render the 36-tab P&L dashboard (HTML)
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels

# Export to all formats (HTML + Excel + PDF)
uv run cockpit render-pnl --date 2026-04-04 --input-dir path/to/excels --format all

# What-if deal impact analysis
uv run cockpit what-if --date 2026-04-04 --input-dir path/to/excels \
  --product IAM/LD --currency CHF --amount 50000000 --rate 0.025 --direction D --maturity 5

# Data quality validation
uv run cockpit validate --input-dir path/to/excels

# ALCO decision tracking
uv run cockpit decision record --topic "NII Sensitivity" --description "Reduce CHF duration" --priority high --owner "ALM"
```

Optional dependency groups: `uv sync --extra agents` (Ollama), `uv sync --extra notion`.

## Pipeline at a Glance

```
fetch  -->  compute  -->  analyze (optional)  -->  render
  |            |              |                       |
  v            v              v                       v
macro_       pnl.json       brief.json             cockpit.html
snapshot     portfolio.json
.json        scores.json

render-pnl (standalone) ──────────────────────> pnl_dashboard.html / .xlsx / .pdf
  ^
  |  reads Excel inputs directly (deals, echeancier, WIRP, IRS stock, etc.)
```

Each stage is independent. You can re-run `render` without re-fetching, or skip `analyze` if Ollama is unavailable. The `render-pnl` path is a major standalone workflow that reads Excel inputs directly and produces a 36-tab P&L dashboard.

## P&L Dashboard Tabs (36)

Grouped by category (matches the order rendered in `pnl_dashboard.html`):

- **NII Core (5)**: ALCO, Summary, CoC Decomposition, P&L Series, Shock Sensitivity
- **Risk (8)**: EVE, NII-at-Risk, Repricing Gap, FX Mismatch, NMD Audit, Deposits, Risk Cube, Regulatory
- **Attribution (3)**: Budget vs Actual, P&L Attribution, Forecast Tracking
- **Structure & Hedging (4)**: Strategy IAS, Counterparty, Hedge Effectiveness, Hedge Strategy
- **Profitability (4)**: NIM, Fixed/Float, Deal Explorer, Maturity Wall
- **Funding & Scenarios (3)**: FTP, Liquidity, Scenario Studio
- **Market & Monitoring (9)**: BOOK2 MTM, Rate Curves, Trends, Basis Risk, SNB Reserves, Peer Benchmark, NMD Backtest, Alerts, Data Quality

Embedded panels rendered inside the above tabs (no separate buttons): Limit Utilization (in EVE / NII-at-Risk), ALCO Decision Pack (in ALCO).

## Key Modules

Beyond the core pipeline, notable additions:

- **`calendar.py`** -- Swiss business day calendar (10 holidays, Easter algorithm, numpy busday)
- **`config_loader.py`** -- YAML-based runtime config with caching, deep-merge over defaults
- **`decisions.py`** -- ALCO decision audit trail (JSONL append-only store)
- **`data/quality.py`** -- Data quality checks (match rates, orphan deals, field coverage, rate staleness)
- **`export/`** -- Excel (`openpyxl`) and PDF (`weasyprint`/`pdfkit`) exporters
- **`integrations/`** -- Notion export (MCP), FINMA peer benchmark comparison
