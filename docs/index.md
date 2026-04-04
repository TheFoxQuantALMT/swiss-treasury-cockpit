# Swiss Treasury Cockpit Documentation

## Overview

Swiss Treasury Cockpit is a daily pipeline for treasury risk monitoring at a Swiss bank. It fetches market data from public sources, runs a vectorized P&L engine with rate shock scenarios, scores per-currency risk, and renders an interactive HTML dashboard.

The system consolidates two internal projects:

- **economic-pnl-v2** -- P&L engine, portfolio snapshot, Excel parsers
- **macro-cbwatch** -- market data fetchers, scoring, alerts, LLM agents

## Documentation Index

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System design, data flow, module structure |
| [Installation](installation.md) | Requirements, setup, environment variables |
| [CLI Reference](cli.md) | All commands, options, examples |
| [P&L Engine](pnl-engine.md) | Daily P&L, CoC decomposition, strategy legs, BOOK1/BOOK2 |
| [Data Models](data-models.md) | Canonical `Deal`, `RFRIndex`, `MarketData` dataclasses |
| [Matrices & Curves](matrices-curves.md) | Numpy array construction, OIS curves, WASP integration |
| [CoC Decomposition](coc-decomposition.md) | Simple vs compounded carry, regulatory basis, formulas |
| [Scoring & Alerts](scoring-alerts.md) | Deterministic risk scoring, threshold alerts |
| [Portfolio Snapshot](portfolio-snapshot.md) | Liquidity ladder, positions, counterparty exposure |
| [Data Ingestion](data-ingestion.md) | Fetchers, parsers, DataManager, circuit breakers |
| [LLM Agents](llm-agents.md) | Analyst, reviewer, reporter -- daily brief generation |
| [Rendering](rendering.md) | Jinja2 templates, Plotly charts, 5-tab dashboard |
| [Configuration](configuration.md) | All constants, thresholds, mappings |
| [Testing](testing.md) | Test structure, fixtures, running tests |
| [Regulatory Reference](regulatory-reference.md) | ISDA, IFRS 9, BCBS 368, FINMA standards applied |

## Quick Start

```bash
# Install
uv sync

# Run the full pipeline
uv run cockpit run-all --date 2026-04-04

# Run with deal-level funding rates instead of OIS
uv run cockpit run-all --date 2026-04-04 --funding-source coc
```

## Pipeline at a Glance

```
fetch  -->  compute  -->  analyze (optional)  -->  render
  |            |              |                       |
  v            v              v                       v
macro_       pnl.json       brief.json             cockpit.html
snapshot     portfolio.json
.json        scores.json
```

Each stage is independent. You can re-run `render` without re-fetching, or skip `analyze` if Ollama is unavailable.
