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

Renders the 35-tab ALM/Treasury P&L dashboard from Excel inputs. Auto-discovers optional ALM files (budget, scenarios, hedge pairs, NMD profiles, limits, alert thresholds, liquidity schedule, custom scenarios).

```bash
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --funding-source coc
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --prev-date 2026-04-04
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --shocks extended
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --format xlsx
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --format all
uv run cockpit render-pnl --date 2026-04-05 --input-dir path/to/excels --custom-scenarios path/to/custom_scenarios.xlsx
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files |
| `--funding-source` | No | `ois` (default) or `coc` |
| `--budget` | No | Explicit path to budget file (overrides auto-discovery) |
| `--hedge-pairs` | No | Explicit path to hedge pairs file |
| `--prev-date` | No | Previous date for DoD attribution and P&L explain |
| `--prev-input-dir` | No | Directory for previous date's Excel inputs (defaults to `--input-dir`) |
| `--shocks` | No | Comma-separated shock list (e.g. `-200,-100,0,50,100,200,wirp`) or `extended` for full grid |
| `--format` | No | Output format: `html` (default), `xlsx`, `pdf`, or `all` (html + xlsx + pdf) |
| `--custom-scenarios` | No | Path to `custom_scenarios.xlsx` for user-defined stress tests |

**Output:** `output/{date}_pnl_dashboard.html` (and/or `.xlsx`, `.pdf` depending on `--format`)

**Auto-discovered optional files:** `*budget*`, `*scenario*`, `*hedge*`, `*nmd*`, `*limit*`, `*alert*threshold*`, `*liquidity*` in the input directory.

---

### `backfill` -- Backfill Date Range

Runs `render-pnl` for each business day in a date range to populate KPI history and trends. Automatically skips weekends and Swiss public holidays.

```bash
uv run cockpit backfill --from 2026-03-01 --to 2026-04-04 --input-dir path/to/excels
uv run cockpit backfill --from 2026-03-01 --to 2026-04-04 --input-dir path/to/excels --funding-source coc
```

| Option | Required | Description |
|--------|----------|-------------|
| `--from` | Yes | Start date (YYYY-MM-DD) |
| `--to` | Yes | End date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files |
| `--funding-source` | No | `ois` (default) or `coc` |

**Output:** One `output/{date}_pnl_dashboard.html` per business day in the range.

Failures on individual dates are logged but do not stop the backfill. A summary of succeeded/failed counts is printed at the end.

---

### `validate` -- Validate Input Files

Validates input Excel files against expected schemas. Checks for required files, required columns, known product codes, and data coverage. Reports errors (missing required files/columns) and warnings (missing optional files, unknown products).

```bash
uv run cockpit validate --input-dir path/to/excels
```

| Option | Required | Description |
|--------|----------|-------------|
| `--input-dir` | Yes | Directory containing Excel input files |

**Checked files:**

| File | Status | Checks |
|------|--------|--------|
| deals/MTD | Required | Required columns (`Dealid`, `Product`, `Direction`), known products |
| echeancier/schedule | Required | Parseable |
| budget, hedge pairs, scenarios, NMD profiles, limits, liquidity, WIRP, IRS stock | Optional | Presence reported |

Exits with code 1 if any errors are found.

---

### `what-if` -- Simulate Hypothetical Deal

Simulates adding a hypothetical deal to the current portfolio and displays the incremental impact on NII and EVE.

```bash
uv run cockpit what-if --date 2026-04-04 --input-dir path/to/excels \
    --product IAM/LD --currency CHF --amount 50000000 --rate 0.025 \
    --direction D --maturity 5
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | Yes | Directory containing Excel input files |
| `--product` | Yes | Product type (`IAM/LD`, `BND`, `IRS`) |
| `--currency` | Yes | Currency (`CHF`, `EUR`, `USD`, `GBP`) |
| `--amount` | Yes | Notional amount |
| `--rate` | Yes | Client rate (decimal, e.g. `0.025` for 2.5%) |
| `--direction` | No | Direction: `D` (deposit, default), `L` (loan), `S` (swap), `B` (bond) |
| `--maturity` | No | Maturity in years (default: 5) |
| `--funding-source` | No | `ois` (default) or `coc` |

**Output (to stdout):**
- Spread (bp)
- Delta NII (12-month and lifetime)
- Delta EVE
- DV01 contribution

---

### `decision` -- ALCO Decision Audit Trail

Record, list, update, or summarize ALCO decisions. Decisions are stored as append-only JSONL files in `data/decisions/{YYYY-MM}_decisions.jsonl`.

```bash
# Record a new decision
uv run cockpit decision record --topic "NII Sensitivity" --description "Reduce CHF duration" \
    --priority high --owner "ALM"

# List decisions for a month
uv run cockpit decision list --month 2026-04

# List most recent decisions (default: 20)
uv run cockpit decision list -n 10

# Update a decision's status
uv run cockpit decision update --date 2026-04-06 --topic "NII Sensitivity" --status closed

# Show summary counts by status
uv run cockpit decision summary
```

| Option | Required | Description |
|--------|----------|-------------|
| `action` | Yes | Subcommand: `record`, `list`, `update`, or `summary` |
| `--topic` | record, update | Decision topic |
| `--description` | No | Decision description (record only) |
| `--priority` | No | Priority: `critical`, `high`, `medium` (default), `low` (record only) |
| `--owner` | No | Decision owner (record only) |
| `--date` | update | Date of the decision to update (YYYY-MM-DD) |
| `--status` | update | New status: `open`, `closed`, `deferred` |
| `--month` | No | Filter by year-month `YYYY-MM` (list only) |
| `-n` | No | Number of recent decisions to list (default: 20) |

**Storage:** `data/decisions/{YYYY-MM}_decisions.jsonl`

---

### `export-notion` -- Export to Notion

Exports the ALCO Decision Pack to a Notion page. Requires the `NOTION_TOKEN` environment variable and `uv sync --extra notion`.

```bash
uv run cockpit export-notion --date 2026-04-04 --input-dir path/to/excels \
    --parent-page-id <notion-page-id>
```

| Option | Required | Description |
|--------|----------|-------------|
| `--date` | Yes | Reference date (YYYY-MM-DD) |
| `--input-dir` | No | Directory containing Excel input files |
| `--parent-page-id` | No | Notion parent page or database ID (if omitted, blocks are built but not pushed) |
| `--funding-source` | No | `ois` (default) or `coc` |

**Requires:** `uv sync --extra notion` and `NOTION_TOKEN` environment variable.

---

### `run-all` -- Execute Full Pipeline

Runs all stages in sequence: fetch -> compute -> analyze -> render -> render-pnl.

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

If `analyze` fails (e.g., Ollama unavailable), the pipeline continues to `render` without the daily brief. If `--input-dir` is provided, `render-pnl` is also run automatically after `render`.

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

# P&L dashboard with extended shocks and Excel export
uv run cockpit render-pnl --date 2026-04-04 --input-dir /data --shocks extended --format all

# Backfill a month of KPI history
uv run cockpit backfill --from 2026-03-01 --to 2026-04-04 --input-dir /data

# Validate input files before running
uv run cockpit validate --input-dir /data

# What-if: simulate a new CHF deposit
uv run cockpit what-if --date 2026-04-04 --input-dir /data \
    --product IAM/LD --currency CHF --amount 50000000 --rate 0.025 --direction D --maturity 5

# Record and track ALCO decisions
uv run cockpit decision record --topic "NII Sensitivity" --description "Reduce CHF duration" --priority high --owner "ALM"
uv run cockpit decision list --month 2026-04

# Export ALCO pack to Notion
uv run cockpit export-notion --date 2026-04-04 --input-dir /data --parent-page-id abc123
```
