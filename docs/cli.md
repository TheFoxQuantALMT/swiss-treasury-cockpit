# CLI Reference

The `cockpit` command is the entry point for all pipeline operations.

```bash
uv run cockpit <command> [options]
```

## Commands

### `fetch` -- Fetch Macro Data

Pulls rates, FX, energy, and deposits from FRED, ECB, SNB, and Yahoo Finance.

```bash
uv run cockpit fetch --date 2026-04-04
uv run cockpit fetch --date 2026-04-04 --dry-run
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--dry-run` | No | Fetch data but don't save to disk |

**Output:** `data/{date}_macro_snapshot.json`

All fetchers run concurrently with circuit breakers. If a source fails, the pipeline falls back to the most recent archived snapshot and reports it in the `stale` array.

---

### `compute` -- Run P&L + Scoring + Portfolio

Runs the P&L engine across shock scenarios, builds the portfolio snapshot, computes currency risk scores, and checks alert thresholds.

```bash
uv run cockpit compute --date 2026-04-04 --input-dir path/to/excels
uv run cockpit compute --date 2026-04-04 --input-dir path/to/excels --funding-source coc
uv run cockpit compute --date 2026-04-04 --input-dir path/to/excels --dry-run
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files (MTD, Echeancier, WIRP, IRS) |
| `--funding-source` | No | Funding rate source: `ois` (default, OIS curve) or `coc` (deal-level CocRate) |
| `--dry-run` | No | Compute but don't save results |

**Output:**
- `data/{date}_pnl.json` -- P&L by currency and shock scenario
- `data/{date}_portfolio.json` -- Portfolio snapshot (exposure, positions, counterparty)
- `data/{date}_scores.json` -- Currency risk scores + alerts + deltas

**Input Excel files** (expected in `--input-dir`):

| File pattern | Parser | Content |
|-------------|--------|---------|
| `*MTD Standard Liquidity PnL Report*` | `parse_mtd` | BOOK1 deals with rates |
| `*Echeancier*` | `parse_echeancier` | Nominal schedule by month |
| `*WIRP*` | `parse_wirp` | Market-implied rate expectations |
| `*IRS*` | `parse_irs_stock` | IRS derivatives portfolio |

---

### `analyze` -- Generate LLM Daily Brief

Generates an LLM-written daily brief using local Ollama agents. Requires Ollama running at `http://localhost:11434` with the configured models.

```bash
uv run cockpit analyze --date 2026-04-04
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--dry-run` | No | Generate brief but don't save |

**Requires:** `uv sync --extra agents` and Ollama running locally.

**Models used:**
- Analyst: `deepseek-r1:14b`
- Reviewer: `qwen3.5:9b`

**Output:** `data/{date}_brief.json`

---

### `render` -- Render HTML Dashboard

Assembles a tabbed HTML cockpit from available JSON intermediates.

```bash
uv run cockpit render --date 2026-04-04
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |

**Output:** `output/{date}_cockpit.html`

The renderer handles missing data gracefully -- each tab renders a placeholder if its corresponding JSON file is absent.

---

### `render-pnl` -- Render Dedicated P&L Dashboard

Renders the 21-tab ALM/Treasury P&L dashboard from Excel inputs. Auto-discovers optional ALM files (budget, scenarios, hedge pairs, NMD profiles, limits, alert thresholds, liquidity schedule).

```bash
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --funding-source coc
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --prev-date 2026-04-04
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files |
| `--funding-source` | No | `ois` (default) or `coc` |
| `--budget-file` | No | Explicit path to budget file (overrides auto-discovery) |
| `--hedge-pairs-file` | No | Explicit path to hedge pairs file |
| `--prev-date` | No | Previous date for DoD attribution and P&L explain |

**Output:** `output/{date}_pnl_dashboard.html`

**Auto-discovered optional files:** `*budget*`, `*scenario*`, `*hedge*`, `*nmd*`, `*limit*`, `*alert*threshold*`, `*liquidity*` in the input directory.

---

### `run-all` -- Execute Full Pipeline

Runs all stages in sequence: fetch -> compute -> analyze -> render.

```bash
uv run cockpit run-all --date 2026-04-04
uv run cockpit run-all --date 2026-04-04 --input-dir path/to/excels --funding-source coc
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files |
| `--funding-source` | No | `ois` (default) or `coc` |
| `--dry-run` | No | Run all stages without saving |

If `analyze` fails (e.g., Ollama unavailable), the pipeline continues to `render` without the daily brief.

## Examples

```bash
# Daily production run
uv run cockpit run-all --date 2026-04-04 --input-dir /data/treasury/20260404

# Re-render with existing data
uv run cockpit render --date 2026-04-04

# Compare OIS vs CocRate funding
uv run cockpit compute --date 2026-04-04 --input-dir /data --funding-source ois
uv run cockpit compute --date 2026-04-04 --input-dir /data --funding-source coc

# Dry run for testing
uv run cockpit run-all --date 2026-04-04 --dry-run
```
