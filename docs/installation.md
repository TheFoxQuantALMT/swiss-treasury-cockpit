# Installation

## Requirements

- **Python 3.13+**
- **[uv](https://docs.astral.sh/uv/)** package manager
- **Optional:** [Ollama](https://ollama.com/) for LLM daily briefs
- **Optional:** FRED API key for macro data fetching
- **Optional:** waspTools library for WASP yield curve integration

## Setup

```bash
# Clone and install
git clone <repo-url>
cd swiss-treasury-cockpit
uv sync
```

### Optional Dependencies

```bash
# LLM agent support (requires Ollama running locally)
uv sync --extra agents

# Notion integration
uv sync --extra notion
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FRED_API_KEY` | No | FRED API key for macro data. Set in `.env` file. Without it, FRED data is skipped. |
| `WASP_TOOLS_PATH` | No | Path to the waspTools library directory. When set, the engine loads real OIS forward curves. When absent, mock curves are built from WIRP data. |
| `PNL_OIS_BASE` | No | Base directory for P&L input/output files. Defaults to `J:\ALM\ALM\06. Analyses et projets\2024_OIS`. |

### `.env` file example

```
FRED_API_KEY=your_key_here
WASP_TOOLS_PATH=C:\path\to\wasptools
```

## Dependencies

### Core

| Package | Version | Purpose |
|---------|---------|---------|
| pandas | >=2.2.3 | DataFrames, time series |
| numpy | >=2.0.0 | Vectorized P&L arrays |
| openpyxl | >=3.1.5 | Excel file parsing |
| dill | >=0.3.8 | Serialization of ForecastRatePnL |
| httpx | >=0.27 | Async HTTP for fetchers |
| yfinance | >=0.2 | Yahoo Finance data |
| jinja2 | >=3.1 | HTML template rendering |
| pyyaml | >=6.0 | YAML configuration |
| python-dotenv | >=1.0 | `.env` file loading |
| pydantic-settings | >=2.6 | Settings management |
| plotly | >=6.6.0 | Interactive charts |
| kaleido | >=1.2.0 | Plotly static image export |
| loguru | >=0.7 | Structured logging |

### Optional: Agents

| Package | Version | Purpose |
|---------|---------|---------|
| agent-framework | >=1.0.0rc5 | LLM agent orchestration |
| agent-framework-ollama | >=1.0.0b260319 | Ollama backend |
| mlflow-tracing | >=3.10.1 | Agent call tracing |

### Development

| Package | Version | Purpose |
|---------|---------|---------|
| pytest | >=8.3.5 | Test framework |

## Verification

```bash
# Run all tests
uv run pytest

# Run the CLI help
uv run cockpit --help

# Dry run to verify installation
uv run cockpit fetch --date 2026-04-04 --dry-run
```
