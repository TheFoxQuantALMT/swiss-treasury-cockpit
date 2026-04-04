# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Swiss Treasury Cockpit — a unified static HTML dashboard combining the economic P&L projection engine and central bank monitoring platform for a Swiss bank ALM/treasury team. Outputs a single self-contained tabbed HTML file.

## Commands

```bash
# Install dependencies
uv sync

# Install with optional LLM agent support
uv sync --extra agents

# Run tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_config.py -v

# Run tests matching a name
uv run pytest -k "test_scoring" -v

# Pipeline steps (composable, independent)
uv run cockpit fetch --date 2026-04-03
uv run cockpit compute --date 2026-04-03 --input-dir 202604/20260403
uv run cockpit analyze --date 2026-04-03
uv run cockpit render --date 2026-04-03
uv run cockpit run-all --date 2026-04-03 --input-dir 202604/20260403

# Dry run (no file writes)
uv run cockpit fetch --date 2026-04-03 --dry-run
```

## Architecture

Three layers orchestrated by a CLI:

- **`src/cockpit/data/`** — Data ingestion. `parsers/` reads Excel files (MTD, Echeancier, WIRP, IRS Stock). `fetchers/` pulls macro data from FRED, ECB, SNB, yfinance with circuit breakers and fallback to cached archives.
- **`src/cockpit/engine/`** — Computation. `pnl/` is the vectorized P&L engine (numpy matrices, OIS-spread computation). `snapshot/` computes liquidity ladder, position aggregation, counterparty analysis. `scoring/` is deterministic 0-100 risk scoring per currency. `alerts/` checks threshold breaches.
- **`src/cockpit/render/`** — HTML generation. `charts.py` builds Chart.js data dicts. `renderer.py` is the Jinja2 orchestrator. `templates/` has per-tab HTML partials assembled into a single self-contained file.
- **`src/cockpit/agents/`** — Optional LLM layer (Ollama). Analyst writes macro commentary at `[INTERPRET]` markers. Reviewer validates numbers programmatically. P&L numbers never pass through the LLM.

Each CLI step reads/writes JSON to `data/`. Steps are independent — `render` assembles whatever is available, showing placeholders for missing data.

## Key Conventions

- Config constants live in `src/cockpit/config.py` (no YAML parsing at runtime)
- P&L numbers are deterministic and bypass the LLM — only macro commentary uses agents
- The HTML output is fully self-contained (no CDN, all CSS/JS inline)
- Dark theme with CSS variables (--bg-primary, --accent-blue, etc.)
- Scoring is config-driven: piecewise linear normalization → Calm/Watch/Action labels
- FX alert bands, energy thresholds, and scenario probabilities are in config.py
