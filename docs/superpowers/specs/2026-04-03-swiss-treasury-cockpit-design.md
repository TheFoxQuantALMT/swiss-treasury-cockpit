# Swiss Treasury Cockpit — Design Spec

## Date: 2026-04-03

## Overview

A unified static HTML cockpit that combines the economic P&L projection engine (`economic-pnl-v2`) and the central bank monitoring platform (`macro-cbwatch`) into a single tabbed dashboard for a small ALM/treasury team at a Swiss bank.

The cockpit is a **monorepo** consolidating code from both source projects. It outputs a **single self-contained HTML file** with five tabs, generated via Jinja2 templates and Chart.js/Plotly charts. The pipeline runs as **composable CLI steps** that can be executed independently or chained together.

## Source Projects

| Project | Location | What it provides |
|---------|----------|-----------------|
| economic-pnl-v2 | `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2` | P&L engine, portfolio snapshot modules, Excel parsers |
| macro-cbwatch | `/mnt/Projects/Projects/macro-cbwatch` | Data fetchers, scoring engine, alerts, LLM agents, HTML rendering |

### Related Specs

- **Exposure modules spec:** `macro-cbwatch/docs/superpowers/specs/2026-04-03-treasury-analytics-exposure-modules-design.md` — defines `compute_liquidity_ladder()`, `compute_positions()`, `compute_counterparty()`, `build_portfolio_snapshot()` and the `portfolio_snapshot.json` data contract consumed by Tab 4.

## Architecture

Three layers — data, engine, render — orchestrated by a CLI.

```
┌─────────────────────────────────────────────────────────────┐
│                         CLI (cli.py)                        │
│         fetch  |  compute  |  analyze  |  render            │
└──────┬─────────┴─────┬─────┴─────┬─────┴──────┬────────────┘
       │               │           │             │
       ▼               ▼           ▼             ▼
   data/            engine/     agents/       render/
   fetchers/        pnl/        analyst.py    renderer.py
   parsers/         scoring/    reviewer.py   charts.py
   manager.py       alerts/     reporter.py   templates/
                    snapshot/
```

### Data Flow

```
Excel Files (MTD, Echeancier, WIRP, IRS)     FRED / ECB / SNB / yfinance
         │                                              │
         ▼                                              ▼
    parsers/                                       fetchers/
         │                                              │
         ▼                                              ▼
  data/{date}_pnl_input.json                 data/{date}_macro_snapshot.json
         │                                              │
         ├──────────────┬───────────────────────────────┤
         ▼              ▼                               ▼
    engine/pnl/    engine/snapshot/              engine/scoring/
                                                engine/alerts/
         │              │                               │
         ▼              ▼                               ▼
  data/{date}_pnl.json  data/{date}_portfolio.json  data/{date}_scores.json
         │              │                               │
         │              │         agents/ (Ollama)      │
         │              │              │                 │
         │              │              ▼                 │
         │              │     data/{date}_brief.json     │
         │              │              │                 │
         └──────────────┴──────────────┴─────────────────┘
                                │
                                ▼
                        render/renderer.py
                                │
                                ▼
                    output/{date}_cockpit.html
```

## Repository Structure

```
swiss-treasury-cockpit/
├── pyproject.toml
├── src/
│   └── cockpit/
│       ├── __init__.py
│       ├── cli.py              # CLI entry points: fetch, compute, analyze, render, run-all
│       ├── config.py           # Unified config (merged from both projects)
│       │
│       ├── data/               # Data fetching & parsing layer
│       │   ├── fetchers/       # FRED, ECB, SNB, yfinance (from cbwatch)
│       │   │   ├── fred_fetcher.py
│       │   │   ├── ecb_fetcher.py
│       │   │   ├── snb_fetcher.py
│       │   │   ├── yfinance_fetcher.py
│       │   │   └── circuit_breaker.py
│       │   ├── parsers/        # Excel parsers (from economic-pnl)
│       │   │   ├── mtd.py
│       │   │   ├── echeancier.py
│       │   │   ├── wirp.py
│       │   │   ├── irs_stock.py
│       │   │   └── reference_table.py
│       │   └── manager.py      # Unified data manager
│       │
│       ├── engine/             # Compute layer
│       │   ├── pnl/            # P&L engine (from economic-pnl-v2)
│       │   │   ├── matrices.py
│       │   │   ├── engine.py
│       │   │   ├── curves.py
│       │   │   └── forecast.py
│       │   ├── scoring/        # Deterministic scoring (from cbwatch)
│       │   │   └── scoring.py
│       │   ├── alerts/         # Threshold alerts (from cbwatch)
│       │   │   └── alerts.py
│       │   └── snapshot/       # Portfolio snapshot (from exposure modules spec)
│       │       ├── enrichment.py
│       │       ├── exposure.py
│       │       ├── aggregation.py
│       │       ├── counterparty.py
│       │       └── snapshot.py
│       │
│       ├── agents/             # LLM analysis layer (from cbwatch)
│       │   ├── analyst.py
│       │   ├── reviewer.py
│       │   └── reporter.py
│       │
│       └── render/             # HTML generation
│           ├── charts.py       # Chart.js/Plotly chart data builders
│           ├── renderer.py     # Jinja2 orchestrator
│           └── templates/
│               ├── cockpit.html       # Main shell (tab nav, shared CSS/JS)
│               ├── _macro.html        # Tab 1: Macro Overview
│               ├── _fx_energy.html    # Tab 2: FX & Energy
│               ├── _pnl.html          # Tab 3: P&L Projection
│               ├── _portfolio.html    # Tab 4: Portfolio Snapshot
│               └── _brief.html        # Tab 5: Daily Brief
│
├── data/                       # Runtime data (inputs, archive, snapshots)
│   └── archive/                # Daily JSON snapshots for deltas
├── output/                     # Generated HTML + Excel exports
├── tests/
│   ├── test_engine/
│   ├── test_parsers/
│   ├── test_fetchers/
│   ├── test_scoring/
│   ├── test_alerts/
│   ├── test_snapshot/
│   └── test_renderer/
└── docs/
```

## CLI Pipeline

Four independent steps, each reading/writing JSON to `data/`:

```bash
# Step 1: Fetch macro data (FRED, ECB, SNB, yfinance)
uv run cockpit fetch --date 2026-04-03

# Step 2: Compute P&L + scoring + alerts + portfolio snapshot
uv run cockpit compute --date 2026-04-03 --input-dir 202604/20260403

# Step 3: Generate LLM analysis (requires Ollama)
uv run cockpit analyze --date 2026-04-03

# Step 4: Render HTML cockpit
uv run cockpit render --date 2026-04-03

# All steps:
uv run cockpit run-all --date 2026-04-03 --input-dir 202604/20260403
```

**Step dependencies:**
- `fetch` and `compute` are independent — `run-all` can execute them in parallel
- `analyze` depends on `fetch` output (macro data for LLM context)
- `render` depends on all previous outputs — assembles everything into one HTML file
- Each step supports `--dry-run` for testing without side effects
- Date (`--date`) is the single shared coordinate across all steps

**Intermediate data contracts:**

| Step | Output file | Consumed by |
|------|-------------|-------------|
| fetch | `data/{date}_macro_snapshot.json` | compute (scoring/alerts), analyze, render |
| compute | `data/{date}_pnl.json` | render |
| compute | `data/{date}_portfolio.json` | render |
| compute | `data/{date}_scores.json` | render |
| analyze | `data/{date}_brief.json` | render |

## Tab Content

### Tab 1 — Macro Overview

- **Scoring dashboard:** 4 currency cards (CHF/EUR/USD/GBP) with Calm/Watch/Action labels and 0-100 composite scores
- **Active alerts:** color-coded severity badges
- **CB rate summary table:** current rate, last change direction, next meeting date
- **Key dates calendar:** upcoming FOMC, ECB, BNS meetings

Data source: `{date}_macro_snapshot.json`, `{date}_scores.json`

### Tab 2 — FX & Energy

- **FX time series charts:** USD/CHF, EUR/CHF, GBP/CHF with geopolitical scenario bands (Chart.js with zoom/pan)
- **Historical deltas table:** 1d/1w/1m moves
- **Energy charts:** Brent crude, EU gas with alert threshold lines
- **FX alert badges:** breach indicators when outside configured bands

Data source: `{date}_macro_snapshot.json`

### Tab 3 — P&L Projection

- **Monthly forward P&L bar chart** by currency (BOOK1 accrual)
- **Shock scenario comparison:** base vs +50bps vs WIRP as grouped bars
- **BOOK2 MTM summary table:** IRS positions
- **Strategy hedge decomposition:** 4 synthetic legs (IAM/LD-NHCD, IAM/LD-HCD, BND-NHCD, BND-HCD)
- **JS toggle** between stacked and side-by-side views

Data source: `{date}_pnl.json`

### Tab 4 — Portfolio Snapshot

- **Liquidity ladder chart:** 24 Basel-style maturity buckets with inflows/outflows/net/cumulative gap, survival days indicator
- **Positions table:** assets/liabilities by product and currency class (Total/CHF/USD/EUR/GBP/Others)
- **Counterparty concentration donut chart:** top-10 exposures, HHI score
- **Rating distribution bar chart:** AAA-AA / A / BBB / Sub-IG / NR
- **HQLA composition:** L1/L2A/L2B/Non-HQLA breakdown

Data source: `{date}_portfolio.json` (the `portfolio_snapshot.json` contract from the exposure modules spec)

### Tab 5 — Daily Brief

- **LLM-generated narrative** with template-fill `[INTERPRET]` sections
- **Fact-checked badge:** reviewed/unverified status from reviewer agent
- **Inline mini-charts** referenced in the text
- **Structure:** executive summary → per-currency analysis → risks & outlook

Data source: `{date}_brief.json`

## Shared UI

- **Dark theme** consistent with existing treasury dashboard in cbwatch
- **Date selector** in header — loads different day's output if available in `output/`
- **Export button** — print-friendly CSS for PDF generation
- **Chart.js 4.x** for time series and bar charts, **Plotly** for interactive drilldowns
- **Self-contained HTML** — all CSS/JS inline, no external CDN dependencies

## Partial Rendering

The cockpit renders whatever data is available:

| Missing step | Effect |
|-------------|--------|
| `fetch` not run | Tabs 1, 2, 5 show "Run `cockpit fetch` first" placeholder; Tabs 3, 4 render normally |
| `compute` not run | Tabs 3, 4 show placeholder; Tabs 1, 2 render normally |
| `analyze` not run | Tab 5 shows "Run `cockpit analyze` first" placeholder; all other tabs unaffected |
| All steps run | Full cockpit renders |

## Resilience

- **Fetchers:** circuit breaker per source (FRED, ECB, SNB, yfinance) with fallback to previous day's cached data in `data/archive/`
- **Excel parsers:** fail fast with clear error messages if files are missing or malformed — no silent fallbacks
- **LLM layer:** retry loop (max 3 attempts), programmatic number validation by reviewer agent. If Ollama is unreachable, `analyze` fails cleanly, other steps unaffected
- **Step isolation:** each CLI step is independent — a failure in one does not block others

## LLM Boundary

P&L numbers are **never touched by the LLM**. They flow directly from engine to Jinja2 template. The LLM only writes macro commentary in Tab 5 (Daily Brief), using the template-fill pattern from cbwatch where Python pre-fills all numbers and the LLM writes at `[INTERPRET]` markers only.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.13+ |
| Package manager | uv |
| P&L computation | pandas, numpy |
| Data fetching | httpx (async), yfinance |
| Excel parsing | openpyxl |
| Yield curves | waspTools (optional, mock fallback) |
| LLM agents | MS Agent Framework + Ollama (local) |
| HTML templating | Jinja2 |
| Charts | Chart.js 4.x, Plotly, Kaleido |
| Scoring | Deterministic (config-driven, no LLM) |
| Config | pyyaml, pydantic-settings |
| Testing | pytest |

## Testing Strategy

**Unit tests** — per module, fast:
- Engine tests: P&L computation, scoring, alerts (deterministic, no I/O) — ported from economic-pnl's existing 58 tests
- Parser tests: Excel parsing with small fixture files
- Fetcher tests: mock HTTP responses, verify data shape
- Renderer tests: render templates with fixture context dicts, verify HTML structure

**Integration tests:**
- Full pipeline with sample data: fetch (mocked) → compute → render → verify HTML contains expected tab content
- P&L round-trip: parse Excel fixtures → compute → verify numbers match expected output

**No LLM tests** — the agent layer is non-deterministic, validated at runtime by the reviewer agent's programmatic checks.

```bash
uv run pytest tests/ -v              # all tests
uv run pytest tests/test_engine/ -v  # single module group
uv run pytest -k "test_scoring"      # by name
```

## Design Decisions

1. **Monorepo consolidation** — both source projects merged into one repo for unified versioning and simpler deployment to the team
2. **Jinja2 + Chart.js** — extends cbwatch's proven pattern; keeps the stack minimal and familiar
3. **Composable CLI steps** — each step reads/writes JSON, enabling partial runs and independent debugging
4. **Per-tab template partials** — `_macro.html`, `_fx_energy.html`, etc. keep templates maintainable as complexity grows
5. **Self-contained HTML** — no server, no CDN, one file to share — matches team's workflow
6. **P&L numbers bypass LLM** — LLM writes commentary only; numerical integrity maintained by deterministic pipeline
7. **Partial rendering** — cockpit always generates, showing what's available with clear placeholders for missing data
8. **Exposure modules data contract** — Tab 4 consumes `portfolio_snapshot.json` as defined in the existing exposure modules spec, no duplication
