# Swiss Treasury Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified static HTML cockpit that consolidates the economic P&L engine (economic-pnl-v2) and central bank monitoring platform (macro-cbwatch) into a single tabbed dashboard.

**Architecture:** Three layers (data, engine, render) orchestrated by a composable CLI. Code is ported from two source repos into `src/cockpit/`, with new glue code for the CLI, Jinja2 renderer, and HTML templates. Each CLI step (fetch, compute, analyze, render) reads/writes JSON intermediates to `data/`.

**Tech Stack:** Python 3.13+, uv, pandas, numpy, httpx, yfinance, openpyxl, Jinja2, Chart.js 4.x, Plotly, pytest. Optional: waspTools (yield curves), agent-framework + Ollama (LLM analysis).

**Spec:** `docs/superpowers/specs/2026-04-03-swiss-treasury-cockpit-design.md`

**Source projects:**
- economic-pnl-v2: `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2`
- macro-cbwatch: `/mnt/Projects/Projects/macro-cbwatch`

---

## File Map

| Action | File | Source | Responsibility |
|--------|------|--------|---------------|
| Create | `pyproject.toml` | New | Project config, dependencies, CLI script entry |
| Create | `src/cockpit/__init__.py` | New | Package marker |
| Create | `src/cockpit/config.py` | Merge both | Unified constants from economic-pnl config.py + cbwatch config.yaml |
| Copy+Adapt | `src/cockpit/data/parsers/mtd.py` | economic-pnl `parsers.py` | `parse_mtd()` |
| Copy+Adapt | `src/cockpit/data/parsers/echeancier.py` | economic-pnl `parsers.py` | `parse_echeancier()` |
| Copy+Adapt | `src/cockpit/data/parsers/wirp.py` | economic-pnl `parsers.py` | `parse_wirp()` |
| Copy+Adapt | `src/cockpit/data/parsers/irs_stock.py` | economic-pnl `parsers.py` | `parse_irs_stock()` |
| Copy+Adapt | `src/cockpit/data/parsers/reference_table.py` | economic-pnl `parsers.py` | `parse_reference_table()` |
| Copy+Adapt | `src/cockpit/data/fetchers/circuit_breaker.py` | cbwatch `automation/fetchers/circuit_breaker.py` | CircuitBreaker class |
| Copy+Adapt | `src/cockpit/data/fetchers/fred_fetcher.py` | cbwatch `automation/fetchers/fred_fetcher.py` | FREDFetcher class |
| Copy+Adapt | `src/cockpit/data/fetchers/ecb_fetcher.py` | cbwatch `automation/fetchers/ecb_fetcher.py` | ECBFetcher class |
| Copy+Adapt | `src/cockpit/data/fetchers/snb_fetcher.py` | cbwatch `automation/fetchers/snb_fetcher.py` | SNB fetch functions |
| Copy+Adapt | `src/cockpit/data/fetchers/yfinance_fetcher.py` | cbwatch `automation/fetchers/yfinance_fetcher.py` | YFinanceFetcher class |
| Create | `src/cockpit/data/manager.py` | Adapted from cbwatch `data_manager.py` | Unified DataManager (macro + archive) |
| Copy+Adapt | `src/cockpit/engine/pnl/matrices.py` | economic-pnl `matrices.py` | Matrix construction |
| Copy+Adapt | `src/cockpit/engine/pnl/curves.py` | economic-pnl `curves.py` | Yield curve loading |
| Copy+Adapt | `src/cockpit/engine/pnl/engine.py` | economic-pnl `engine.py` | P&L computation |
| Copy+Adapt | `src/cockpit/engine/pnl/forecast.py` | economic-pnl `forecast.py` | ForecastRatePnL orchestrator |
| Copy+Adapt | `src/cockpit/engine/snapshot/enrichment.py` | economic-pnl `enrichment.py` | enrich_deals() |
| Copy+Adapt | `src/cockpit/engine/snapshot/exposure.py` | economic-pnl `exposure.py` | compute_liquidity_ladder() |
| Copy+Adapt | `src/cockpit/engine/snapshot/aggregation.py` | economic-pnl `aggregation.py` | compute_positions() |
| Copy+Adapt | `src/cockpit/engine/snapshot/counterparty.py` | economic-pnl `counterparty.py` | compute_counterparty() |
| Copy+Adapt | `src/cockpit/engine/snapshot/snapshot.py` | economic-pnl `snapshot.py` | build_portfolio_snapshot() |
| Copy+Adapt | `src/cockpit/engine/scoring/scoring.py` | cbwatch `automation/scoring.py` | compute_scores() |
| Copy+Adapt | `src/cockpit/engine/alerts/alerts.py` | cbwatch `automation/alerts.py` | check_alerts() |
| Copy+Adapt | `src/cockpit/engine/comparison.py` | cbwatch `automation/comparison.py` | compute_deltas() |
| Copy+Adapt | `src/cockpit/agents/models.py` | cbwatch `automation/agents/models.py` | Pydantic models |
| Copy+Adapt | `src/cockpit/agents/tools.py` | cbwatch `automation/agents/tools.py` | Reviewer verification tools |
| Copy+Adapt | `src/cockpit/agents/analyst.py` | cbwatch `automation/agents/analyst.py` | Analyst agent |
| Copy+Adapt | `src/cockpit/agents/reviewer.py` | cbwatch `automation/agents/reviewer.py` | Reviewer agent |
| Copy+Adapt | `src/cockpit/agents/reporter.py` | cbwatch `automation/agents/reporter.py` | Reporter agent |
| Create | `src/cockpit/render/charts.py` | New (adapted from cbwatch charts.py) | Chart data builders for all 5 tabs |
| Create | `src/cockpit/render/renderer.py` | New | Jinja2 orchestrator |
| Create | `src/cockpit/render/templates/cockpit.html` | New | Main HTML shell with tab navigation |
| Create | `src/cockpit/render/templates/_macro.html` | New | Tab 1: Macro Overview partial |
| Create | `src/cockpit/render/templates/_fx_energy.html` | New | Tab 2: FX & Energy partial |
| Create | `src/cockpit/render/templates/_pnl.html` | New | Tab 3: P&L Projection partial |
| Create | `src/cockpit/render/templates/_portfolio.html` | New | Tab 4: Portfolio Snapshot partial |
| Create | `src/cockpit/render/templates/_brief.html` | New | Tab 5: Daily Brief partial |
| Create | `src/cockpit/cli.py` | New | CLI entry points (fetch, compute, analyze, render, run-all) |
| Create | `tests/test_config.py` | New | Config constants validation |
| Create | `tests/test_parsers/` | Ported from economic-pnl | Parser tests |
| Create | `tests/test_engine/` | Ported from economic-pnl | Engine tests |
| Create | `tests/test_snapshot/` | Ported from economic-pnl | Snapshot module tests |
| Create | `tests/test_scoring.py` | New | Scoring smoke tests |
| Create | `tests/test_renderer.py` | New | Template rendering tests |
| Create | `tests/test_cli.py` | New | CLI integration tests |

> **Port convention:** "Copy+Adapt" means copy the source file, update imports from `economic_pnl.*` or `automation.*` to `cockpit.*`, and adjust any relative references. The logic stays identical.

---

### Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/cockpit/__init__.py`
- Create: `src/cockpit/data/__init__.py`
- Create: `src/cockpit/data/parsers/__init__.py`
- Create: `src/cockpit/data/fetchers/__init__.py`
- Create: `src/cockpit/engine/__init__.py`
- Create: `src/cockpit/engine/pnl/__init__.py`
- Create: `src/cockpit/engine/scoring/__init__.py`
- Create: `src/cockpit/engine/alerts/__init__.py`
- Create: `src/cockpit/engine/snapshot/__init__.py`
- Create: `src/cockpit/agents/__init__.py`
- Create: `src/cockpit/render/__init__.py`
- Create: `data/.gitkeep`
- Create: `data/archive/.gitkeep`
- Create: `output/.gitkeep`
- Create: `.gitignore`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "swiss-treasury-cockpit"
version = "0.1.0"
description = "Unified treasury cockpit combining P&L engine and central bank monitoring"
requires-python = ">=3.13"
dependencies = [
    "pandas>=2.2.3",
    "numpy>=2.0.0",
    "openpyxl>=3.1.5",
    "dill>=0.3.8",
    "httpx>=0.27",
    "yfinance>=0.2",
    "jinja2>=3.1",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "pydantic-settings>=2.6",
    "plotly>=6.6.0",
    "kaleido>=1.2.0",
    "loguru>=0.7",
]

[project.optional-dependencies]
agents = [
    "agent-framework>=1.0.0rc5",
    "agent-framework-ollama>=1.0.0b260319",
    "mlflow-tracing>=3.10.1",
]
notion = [
    "notion-client>=2.0",
]

[dependency-groups]
dev = [
    "pytest>=8.3.5",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/cockpit"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[project.scripts]
cockpit = "cockpit.cli:main"
```

- [ ] **Step 2: Create .gitignore**

```gitignore
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
.pytest_cache/
data/*.json
data/archive/
output/*.html
output/*.xlsx
output/*.pkl
.env
*.pkl
```

- [ ] **Step 3: Create all __init__.py files and .gitkeep files**

Create empty `__init__.py` in each package directory:
```
src/cockpit/__init__.py
src/cockpit/data/__init__.py
src/cockpit/data/parsers/__init__.py
src/cockpit/data/fetchers/__init__.py
src/cockpit/engine/__init__.py
src/cockpit/engine/pnl/__init__.py
src/cockpit/engine/scoring/__init__.py
src/cockpit/engine/alerts/__init__.py
src/cockpit/engine/snapshot/__init__.py
src/cockpit/agents/__init__.py
src/cockpit/render/__init__.py
```

Create `.gitkeep` in:
```
data/.gitkeep
data/archive/.gitkeep
output/.gitkeep
```

- [ ] **Step 4: Initialize uv and verify**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv sync`
Expected: dependencies install successfully

- [ ] **Step 5: Verify pytest runs**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest --co`
Expected: "no tests ran" (no test files yet), but no import errors

- [ ] **Step 6: Initialize git and commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git init
git add pyproject.toml .gitignore src/ data/.gitkeep data/archive/.gitkeep output/.gitkeep
git commit -m "feat: project scaffold with directory structure and dependencies"
```

---

### Task 2: Unified Config

**Files:**
- Create: `src/cockpit/config.py`
- Create: `tests/test_config.py`

This merges constants from economic-pnl `config.py` and cbwatch `config.yaml` into a single Python module.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
from cockpit.config import (
    # From economic-pnl
    CURRENCY_TO_OIS,
    PRODUCT_RATE_COLUMN,
    SUPPORTED_CURRENCIES,
    MM_BY_CURRENCY,
    SHOCKS,
    LIQUIDITY_BUCKETS,
    RATING_BUCKETS,
    HQLA_LEVELS,
    CURRENCY_CLASSES,
    CDS_ALERT_THRESHOLD_BPS,
    # From cbwatch
    FX_ALERT_BANDS,
    ENERGY_THRESHOLDS,
    DEPOSIT_THRESHOLDS,
    DAILY_MOVE_THRESHOLDS,
    SCORING_LABELS,
    SCENARIOS,
    DATA_DIR,
    OUTPUT_DIR,
)


def test_currency_to_ois():
    assert CURRENCY_TO_OIS["CHF"] == "CHFSON"
    assert CURRENCY_TO_OIS["EUR"] == "EUREST"
    assert CURRENCY_TO_OIS["USD"] == "USSOFR"
    assert CURRENCY_TO_OIS["GBP"] == "GBPOIS"


def test_product_rate_column():
    assert PRODUCT_RATE_COLUMN["IAM/LD"] == "EqOisRate"
    assert PRODUCT_RATE_COLUMN["BND"] == "YTM"
    assert PRODUCT_RATE_COLUMN["HCD"] == "Clientrate"


def test_supported_currencies():
    assert SUPPORTED_CURRENCIES == {"CHF", "EUR", "USD", "GBP"}


def test_mm_by_currency():
    assert MM_BY_CURRENCY["CHF"] == 360
    assert MM_BY_CURRENCY["GBP"] == 365


def test_shocks():
    assert SHOCKS == ["0", "50", "wirp"]


def test_liquidity_buckets_count():
    assert len(LIQUIDITY_BUCKETS) == 24


def test_liquidity_buckets_daily_detail():
    labels = [b[0] for b in LIQUIDITY_BUCKETS]
    assert labels[0] == "O/N"
    assert labels[1] == "D+1"
    assert labels[15] == "D+15"
    assert labels[16] == "16-30d"


def test_rating_buckets_cover_all_grades():
    all_ratings = []
    for ratings in RATING_BUCKETS.values():
        all_ratings.extend(ratings)
    assert "AAA" in all_ratings
    assert "NR" in all_ratings
    assert "D" in all_ratings


def test_hqla_levels():
    assert HQLA_LEVELS == ["L1", "L2A", "L2B", "Non-HQLA"]


def test_currency_classes():
    assert CURRENCY_CLASSES == ["Total", "CHF", "USD", "EUR", "GBP", "Others"]


def test_cds_threshold():
    assert CDS_ALERT_THRESHOLD_BPS == 200


def test_fx_alert_bands():
    assert FX_ALERT_BANDS["EUR_CHF"]["low"] == 0.90
    assert FX_ALERT_BANDS["EUR_CHF"]["high"] == 0.96
    assert FX_ALERT_BANDS["USD_CHF"]["low"] == 0.78
    assert FX_ALERT_BANDS["USD_CHF"]["high"] == 0.85
    assert FX_ALERT_BANDS["GBP_CHF"]["low"] == 1.08
    assert FX_ALERT_BANDS["GBP_CHF"]["high"] == 1.16


def test_energy_thresholds():
    assert ENERGY_THRESHOLDS["brent_high"] == 120.0
    assert ENERGY_THRESHOLDS["brent_low"] == 65.0
    assert ENERGY_THRESHOLDS["eu_gas_high"] == 80.0


def test_deposit_thresholds():
    assert DEPOSIT_THRESHOLDS["weekly_change_threshold_bln"] == 2.0


def test_daily_move_thresholds():
    assert DAILY_MOVE_THRESHOLDS["brent_pct"] == 5.0
    assert DAILY_MOVE_THRESHOLDS["fx_pct"] == 1.0
    assert DAILY_MOVE_THRESHOLDS["vix_pct"] == 10.0


def test_scoring_labels():
    assert SCORING_LABELS["calm_max"] == 45
    assert SCORING_LABELS["watch_max"] == 70


def test_scenarios():
    assert "ceasefire_rapid" in SCENARIOS
    assert "conflict_contained" in SCENARIOS
    assert "escalation_major" in SCENARIOS


def test_data_dir():
    assert DATA_DIR.name == "data"


def test_output_dir():
    assert OUTPUT_DIR.name == "output"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cockpit.config'`

- [ ] **Step 3: Write the implementation**

Create `src/cockpit/config.py`:

```python
"""Unified configuration for Swiss Treasury Cockpit.

Merges constants from economic-pnl (P&L engine) and macro-cbwatch (CB monitoring).
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"

# ---------------------------------------------------------------------------
# P&L Engine constants (from economic-pnl config.py)
# ---------------------------------------------------------------------------

CURRENCY_TO_OIS: dict[str, str] = {
    "CHF": "CHFSON",
    "EUR": "EUREST",
    "USD": "USSOFR",
    "GBP": "GBPOIS",
}

PRODUCT_RATE_COLUMN: dict[str, str] = {
    "IAM/LD": "EqOisRate",
    "BND": "YTM",
    "FXS": "EqOisRate",
    "IRS": "Clientrate",
    "IRS-MTM": "Clientrate",
    "HCD": "Clientrate",
}

NON_STRATEGY_PRODUCTS: set[str] = {"BND", "FXS", "IAM/LD", "IRS", "IRS-MTM"}

SUPPORTED_CURRENCIES: set[str] = {"CHF", "EUR", "USD", "GBP"}

MM_BY_CURRENCY: dict[str, int] = {
    "CHF": 360,
    "EUR": 360,
    "USD": 360,
    "GBP": 365,
}

ECHEANCIER_INDEX_TO_WASP: dict[str, dict[str, str]] = {
    "3M": {"CHF": "CHFSON3M", "EUR": "EUREST3M", "USD": "USSOFR3M", "GBP": "GBPOIS3M"},
    "6M": {"CHF": "CHFSON6M", "EUR": "EUREST6M", "USD": "USSOFR6M", "GBP": "GBPOIS6M"},
    "1M": {"CHF": "CHFSON1M", "EUR": "EUREST1M", "USD": "USSOFR1M", "GBP": "GBPOIS1M"},
}

FLOAT_NAME_TO_WASP: dict[str, str] = {
    "SARON": "CHFSON",
    "ESTR": "EUREST",
    "SOFR": "USSOFR",
    "SONIA": "GBPOIS",
}

SHOCKS: list[str] = ["0", "50", "wirp"]

# ---------------------------------------------------------------------------
# Exposure module constants (from economic-pnl config.py)
# ---------------------------------------------------------------------------

LIQUIDITY_BUCKETS: list[tuple[str, int | None, int | None]] = [
    ("O/N", 0, 0),
    ("D+1", 1, 1),
    ("D+2", 2, 2),
    ("D+3", 3, 3),
    ("D+4", 4, 4),
    ("D+5", 5, 5),
    ("D+6", 6, 6),
    ("D+7", 7, 7),
    ("D+8", 8, 8),
    ("D+9", 9, 9),
    ("D+10", 10, 10),
    ("D+11", 11, 11),
    ("D+12", 12, 12),
    ("D+13", 13, 13),
    ("D+14", 14, 14),
    ("D+15", 15, 15),
    ("16-30d", 16, 30),
    ("1-3M", 31, 90),
    ("3-6M", 91, 180),
    ("6-12M", 181, 365),
    ("1-2Y", 366, 730),
    ("2-5Y", 731, 1825),
    ("5Y+", 1826, None),
    ("Undefined", None, None),
]

RATING_BUCKETS: dict[str, list[str]] = {
    "AAA-AA": ["AAA", "AA+", "AA", "AA-"],
    "A": ["A+", "A", "A-"],
    "BBB": ["BBB+", "BBB", "BBB-"],
    "Sub-IG": ["BB+", "BB", "BB-", "B+", "B", "B-", "CCC", "CC", "C", "D"],
    "NR": ["NR"],
}

HQLA_LEVELS: list[str] = ["L1", "L2A", "L2B", "Non-HQLA"]

CURRENCY_CLASSES: list[str] = ["Total", "CHF", "USD", "EUR", "GBP", "Others"]

CDS_ALERT_THRESHOLD_BPS: int = 200

# ---------------------------------------------------------------------------
# Counterparty perimeters (from economic-pnl config.py)
# ---------------------------------------------------------------------------

_WM_COUNTERPARTIES: set[str] = {
    "THCCBFIGE", "BKCCBFIGE", "THCCBZIWE", "WCCCBFIGE", "THCCHFIGE",
}

_CIB_COUNTERPARTIES: set[str] = {
    "CLI-MT-CIB", "CPFNCLI", "CLI-FI-CIB",
}

# ---------------------------------------------------------------------------
# Macro monitoring constants (from cbwatch config.yaml)
# ---------------------------------------------------------------------------

FX_ALERT_BANDS: dict[str, dict[str, float]] = {
    "EUR_CHF": {"low": 0.90, "high": 0.96},
    "USD_CHF": {"low": 0.78, "high": 0.85},
    "GBP_CHF": {"low": 1.08, "high": 1.16},
}

ENERGY_THRESHOLDS: dict[str, float] = {
    "brent_high": 120.0,
    "brent_low": 65.0,
    "eu_gas_high": 80.0,
}

DEPOSIT_THRESHOLDS: dict[str, float] = {
    "weekly_change_threshold_bln": 2.0,
}

DAILY_MOVE_THRESHOLDS: dict[str, float] = {
    "brent_pct": 5.0,
    "eu_gas_pct": 5.0,
    "fx_pct": 1.0,
    "vix_pct": 10.0,
}

SCORING_LABELS: dict[str, int] = {
    "calm_max": 45,
    "watch_max": 70,
}

SCENARIOS: dict[str, dict] = {
    "ceasefire_rapid": {
        "probability": 0.30,
        "brent_target": 65,
        "usd_chf_range": [0.82, 0.84],
        "eur_chf_range": [0.92, 0.94],
    },
    "conflict_contained": {
        "probability": 0.45,
        "brent_target": [100, 120],
        "usd_chf_range": [0.79, 0.82],
        "eur_chf_range": [0.90, 0.93],
    },
    "escalation_major": {
        "probability": 0.25,
        "brent_target": [130, 150],
        "usd_chf_range": [0.75, 0.78],
        "eur_chf_range": [0.88, 0.91],
    },
}

# ---------------------------------------------------------------------------
# LLM models (from cbwatch config.yaml)
# ---------------------------------------------------------------------------

ANALYST_MODEL: str = "deepseek-r1:14b"
REVIEWER_MODEL: str = "qwen3.5:9b"
OLLAMA_HOST: str = "http://localhost:11434"
MAX_REVIEW_RETRIES: int = 3
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/config.py tests/test_config.py
git commit -m "feat(config): unified config merging economic-pnl and cbwatch constants"
```

---

### Task 3: Port Excel Parsers

**Files:**
- Create: `src/cockpit/data/parsers/mtd.py`
- Create: `src/cockpit/data/parsers/echeancier.py`
- Create: `src/cockpit/data/parsers/wirp.py`
- Create: `src/cockpit/data/parsers/irs_stock.py`
- Create: `src/cockpit/data/parsers/reference_table.py`
- Create: `tests/test_parsers/__init__.py`
- Create: `tests/test_parsers/test_reference_table.py`

Source: `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/parsers.py`

The economic-pnl parsers are all in one file. We split them into separate files per parser function, updating imports from `economic_pnl.config` to `cockpit.config`.

- [ ] **Step 1: Split and copy parsers**

For each parser, copy the relevant function from the source `parsers.py` into its own file. The import changes needed in each file:

```python
# Old (in every function that uses config):
from economic_pnl.config import PRODUCT_RATE_COLUMN, MM_BY_CURRENCY
# New:
from cockpit.config import PRODUCT_RATE_COLUMN, MM_BY_CURRENCY
```

**mtd.py** — Copy the `parse_mtd()` function and its imports. This function reads the "Conso Deal Level" sheet, renames columns, converts rates to decimal, and filters to supported currencies.

**echeancier.py** — Copy `parse_echeancier()` and the helper `_month_columns()`. This reads the "Operations Propres EoM" sheet and carries V-leg balances forward.

**wirp.py** — Copy `parse_wirp()`. Reads "Sheet1", melts to long format with (Indice, Meeting, Rate, Hike/Cut).

**irs_stock.py** — Copy `parse_irs_stock()`. Reads with header row 3.

**reference_table.py** — Copy `parse_reference_table()`. Reads counterparty reference data, fills missing with defaults.

Read the source file at `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/parsers.py` to get the exact code for each function.

- [ ] **Step 2: Update `__init__.py` to re-export**

Update `src/cockpit/data/parsers/__init__.py`:

```python
from cockpit.data.parsers.mtd import parse_mtd
from cockpit.data.parsers.echeancier import parse_echeancier
from cockpit.data.parsers.wirp import parse_wirp
from cockpit.data.parsers.irs_stock import parse_irs_stock
from cockpit.data.parsers.reference_table import parse_reference_table

__all__ = [
    "parse_mtd",
    "parse_echeancier",
    "parse_wirp",
    "parse_irs_stock",
    "parse_reference_table",
]
```

- [ ] **Step 3: Write a smoke test for reference_table parser**

Create `tests/test_parsers/__init__.py` (empty).

Create `tests/test_parsers/test_reference_table.py`:

```python
import pandas as pd
from cockpit.data.parsers import parse_reference_table
from pathlib import Path
import tempfile


def _write_ref_excel(path: Path) -> None:
    df = pd.DataFrame({
        "counterparty": ["THCCBFIGE", "WM-CLI-GE", "CLI-MT-CIB", "UNKNOWN-X"],
        "rating": ["AA+", "A", "BBB-", "NR"],
        "hqla_level": ["L1", "L2A", "L2B", "Non-HQLA"],
        "country": ["CH", "CH", "FR", "US"],
    })
    df.to_excel(path, index=False, engine="openpyxl")


def test_parse_reference_table():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp = Path(f.name)
    _write_ref_excel(tmp)
    result = parse_reference_table(tmp)
    assert len(result) == 4
    assert list(result.columns) == ["counterparty", "rating", "hqla_level", "country"]
    assert result.iloc[0]["counterparty"] == "THCCBFIGE"
    assert result.iloc[0]["rating"] == "AA+"
    tmp.unlink()


def test_parse_reference_table_fills_missing():
    df = pd.DataFrame({
        "counterparty": ["ABC"],
        "rating": [None],
        "hqla_level": [None],
        "country": [None],
    })
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp = Path(f.name)
    df.to_excel(tmp, index=False, engine="openpyxl")
    result = parse_reference_table(tmp)
    assert result.iloc[0]["rating"] == "NR"
    assert result.iloc[0]["hqla_level"] == "Non-HQLA"
    assert result.iloc[0]["country"] == "XX"
    tmp.unlink()
```

- [ ] **Step 4: Run tests to verify parsers import and work**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_parsers/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/data/parsers/ tests/test_parsers/
git commit -m "feat(parsers): port Excel parsers from economic-pnl, split into per-file modules"
```

---

### Task 4: Port Macro Data Fetchers

**Files:**
- Create: `src/cockpit/data/fetchers/circuit_breaker.py`
- Create: `src/cockpit/data/fetchers/fred_fetcher.py`
- Create: `src/cockpit/data/fetchers/ecb_fetcher.py`
- Create: `src/cockpit/data/fetchers/snb_fetcher.py`
- Create: `src/cockpit/data/fetchers/yfinance_fetcher.py`

Source: `/mnt/Projects/Projects/macro-cbwatch/automation/fetchers/`

- [ ] **Step 1: Copy fetcher files**

Copy each file from `macro-cbwatch/automation/fetchers/` to `src/cockpit/data/fetchers/`. The only import change needed is:

```python
# Old:
from automation.fetchers.circuit_breaker import CircuitBreaker
# New:
from cockpit.data.fetchers.circuit_breaker import CircuitBreaker
```

Read each source file and copy with updated imports. The files are:
- `circuit_breaker.py` — no internal imports, copy as-is
- `fred_fetcher.py` — update circuit_breaker import
- `ecb_fetcher.py` — update circuit_breaker import
- `snb_fetcher.py` — update circuit_breaker import
- `yfinance_fetcher.py` — update circuit_breaker import

- [ ] **Step 2: Update `__init__.py`**

Update `src/cockpit/data/fetchers/__init__.py`:

```python
from cockpit.data.fetchers.circuit_breaker import CircuitBreaker
from cockpit.data.fetchers.fred_fetcher import FREDFetcher
from cockpit.data.fetchers.ecb_fetcher import ECBFetcher
from cockpit.data.fetchers.snb_fetcher import fetch_sight_deposits, fetch_saron
from cockpit.data.fetchers.yfinance_fetcher import YFinanceFetcher

__all__ = [
    "CircuitBreaker",
    "FREDFetcher",
    "ECBFetcher",
    "fetch_sight_deposits",
    "fetch_saron",
    "YFinanceFetcher",
]
```

- [ ] **Step 3: Write import smoke test**

Create `tests/test_fetchers/__init__.py` (empty).

Create `tests/test_fetchers/test_imports.py`:

```python
def test_circuit_breaker_import():
    from cockpit.data.fetchers import CircuitBreaker
    cb = CircuitBreaker(name="test")
    assert cb.name == "test"
    assert not cb.is_open()


def test_fetcher_classes_import():
    from cockpit.data.fetchers import FREDFetcher, ECBFetcher, YFinanceFetcher
    assert FREDFetcher is not None
    assert ECBFetcher is not None
    assert YFinanceFetcher is not None


def test_snb_functions_import():
    from cockpit.data.fetchers import fetch_sight_deposits, fetch_saron
    assert callable(fetch_sight_deposits)
    assert callable(fetch_saron)
```

- [ ] **Step 4: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_fetchers/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/data/fetchers/ tests/test_fetchers/
git commit -m "feat(fetchers): port macro data fetchers from cbwatch"
```

---

### Task 5: Port Data Manager

**Files:**
- Create: `src/cockpit/data/manager.py`
- Create: `tests/test_data_manager.py`

Source: `/mnt/Projects/Projects/macro-cbwatch/automation/fetchers/data_manager.py`

- [ ] **Step 1: Copy and adapt DataManager**

Copy `data_manager.py` from cbwatch, updating imports:

```python
# Old:
from automation.fetchers.fred_fetcher import FREDFetcher
from automation.fetchers.ecb_fetcher import ECBFetcher
from automation.fetchers.snb_fetcher import fetch_sight_deposits, fetch_saron
from automation.fetchers.yfinance_fetcher import YFinanceFetcher
# New:
from cockpit.data.fetchers import FREDFetcher, ECBFetcher, fetch_sight_deposits, fetch_saron, YFinanceFetcher
from cockpit.config import DATA_DIR
```

Also update any hardcoded `data/` paths to use `DATA_DIR` from config.

Read the source file at `/mnt/Projects/Projects/macro-cbwatch/automation/fetchers/data_manager.py` to get exact code and adapt.

- [ ] **Step 2: Write smoke test**

Create `tests/test_data_manager.py`:

```python
from cockpit.data.manager import DataManager


def test_data_manager_init():
    dm = DataManager(fred_api_key="test-key")
    assert dm is not None
```

- [ ] **Step 3: Run test**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_data_manager.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/data/manager.py tests/test_data_manager.py
git commit -m "feat(data): port DataManager from cbwatch with unified config paths"
```

---

### Task 6: Port P&L Engine

**Files:**
- Create: `src/cockpit/engine/pnl/matrices.py`
- Create: `src/cockpit/engine/pnl/curves.py`
- Create: `src/cockpit/engine/pnl/engine.py`
- Create: `src/cockpit/engine/pnl/forecast.py`
- Create: `tests/test_engine/__init__.py`
- Create: `tests/test_engine/test_matrices.py`
- Create: `tests/test_engine/test_engine.py`

Source: `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/`

- [ ] **Step 1: Copy engine files with updated imports**

Copy each file, updating imports throughout:

```python
# Old pattern:
from economic_pnl.config import CURRENCY_TO_OIS, PRODUCT_RATE_COLUMN, ...
from economic_pnl.matrices import build_date_grid, expand_nominal_to_daily, ...
from economic_pnl.curves import load_daily_curves, overlay_wirp, CurveCache
from economic_pnl.engine import compute_daily_pnl, aggregate_to_monthly, ...

# New pattern:
from cockpit.config import CURRENCY_TO_OIS, PRODUCT_RATE_COLUMN, ...
from cockpit.engine.pnl.matrices import build_date_grid, expand_nominal_to_daily, ...
from cockpit.engine.pnl.curves import load_daily_curves, overlay_wirp, CurveCache
from cockpit.engine.pnl.engine import compute_daily_pnl, aggregate_to_monthly, ...
```

Read each source file to get exact code:
- `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/matrices.py`
- `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/curves.py`
- `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/engine.py`
- `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/forecast.py`

**forecast.py** also needs parser imports updated:

```python
# Old:
from economic_pnl.parsers import parse_mtd, parse_echeancier, parse_wirp, parse_irs_stock
# New:
from cockpit.data.parsers import parse_mtd, parse_echeancier, parse_wirp, parse_irs_stock
```

- [ ] **Step 2: Update `__init__.py`**

Update `src/cockpit/engine/pnl/__init__.py`:

```python
from cockpit.engine.pnl.forecast import ForecastRatePnL, save_pnl, load_pnl, compare_pnl

__all__ = ["ForecastRatePnL", "save_pnl", "load_pnl", "compare_pnl"]
```

- [ ] **Step 3: Port key tests from economic-pnl**

Copy tests from `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/tests/test_matrices.py` and `tests/test_engine.py`, updating imports:

```python
# Old:
from economic_pnl.matrices import build_date_grid, ...
from economic_pnl.engine import compute_daily_pnl, ...

# New:
from cockpit.engine.pnl.matrices import build_date_grid, ...
from cockpit.engine.pnl.engine import compute_daily_pnl, ...
```

- [ ] **Step 4: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_engine/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/engine/pnl/ tests/test_engine/
git commit -m "feat(engine): port P&L engine from economic-pnl-v2"
```

---

### Task 7: Port Snapshot Modules

**Files:**
- Create: `src/cockpit/engine/snapshot/enrichment.py`
- Create: `src/cockpit/engine/snapshot/exposure.py`
- Create: `src/cockpit/engine/snapshot/aggregation.py`
- Create: `src/cockpit/engine/snapshot/counterparty.py`
- Create: `src/cockpit/engine/snapshot/snapshot.py`
- Create: `tests/test_snapshot/__init__.py`
- Create: `tests/test_snapshot/test_enrichment.py`

Source: `/mnt/Projects/Projects/Treasury Macro Cockpit Design/.worktrees/economic-pnl-v2/src/economic_pnl/`

- [ ] **Step 1: Copy snapshot module files**

Copy each file, updating imports:

```python
# Old:
from economic_pnl.config import LIQUIDITY_BUCKETS, RATING_BUCKETS, ...
from economic_pnl.enrichment import enrich_deals
from economic_pnl.exposure import compute_liquidity_ladder
from economic_pnl.aggregation import compute_positions
from economic_pnl.counterparty import compute_counterparty
from economic_pnl.engine import weighted_average

# New:
from cockpit.config import LIQUIDITY_BUCKETS, RATING_BUCKETS, ...
from cockpit.engine.snapshot.enrichment import enrich_deals
from cockpit.engine.snapshot.exposure import compute_liquidity_ladder
from cockpit.engine.snapshot.aggregation import compute_positions
from cockpit.engine.snapshot.counterparty import compute_counterparty
from cockpit.engine.pnl.engine import weighted_average
```

Read each source file to get exact code:
- `enrichment.py`, `exposure.py`, `aggregation.py`, `counterparty.py`, `snapshot.py`

- [ ] **Step 2: Update `__init__.py`**

Update `src/cockpit/engine/snapshot/__init__.py`:

```python
from cockpit.engine.snapshot.snapshot import build_portfolio_snapshot, write_snapshot

__all__ = ["build_portfolio_snapshot", "write_snapshot"]
```

- [ ] **Step 3: Port enrichment test**

Copy from economic-pnl tests, updating imports. Create `tests/test_snapshot/__init__.py` (empty).

Create `tests/test_snapshot/test_enrichment.py`:

```python
import pandas as pd
from cockpit.engine.snapshot.enrichment import enrich_deals


def _sample_deals() -> pd.DataFrame:
    return pd.DataFrame({
        "Dealid": [1, 2, 3],
        "Product": ["IAM/LD", "BND", "HCD"],
        "Currency": ["CHF", "EUR", "USD"],
        "Direction": ["L", "B", "D"],
        "Amount": [10_000_000.0, 5_000_000.0, 8_000_000.0],
        "Counterparty": ["THCCBFIGE", "CLI-MT-CIB", "UNKNOWN-X"],
    })


def _sample_ref() -> pd.DataFrame:
    return pd.DataFrame({
        "counterparty": ["THCCBFIGE", "CLI-MT-CIB"],
        "rating": ["AA+", "BBB-"],
        "hqla_level": ["L1", "L2B"],
        "country": ["CH", "FR"],
    })


def test_enrich_deals_joins_reference_data():
    enriched = enrich_deals(_sample_deals(), _sample_ref())
    row0 = enriched[enriched["Dealid"] == 1].iloc[0]
    assert row0["rating"] == "AA+"
    assert row0["hqla_level"] == "L1"
    assert row0["country"] == "CH"


def test_enrich_deals_defaults_unmatched():
    enriched = enrich_deals(_sample_deals(), _sample_ref())
    row2 = enriched[enriched["Dealid"] == 3].iloc[0]
    assert row2["rating"] == "NR"
    assert row2["hqla_level"] == "Non-HQLA"
    assert row2["country"] == "XX"
```

- [ ] **Step 4: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_snapshot/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/engine/snapshot/ tests/test_snapshot/
git commit -m "feat(snapshot): port exposure, aggregation, counterparty modules from economic-pnl"
```

---

### Task 8: Port Scoring & Alerts

**Files:**
- Create: `src/cockpit/engine/scoring/scoring.py`
- Create: `src/cockpit/engine/alerts/alerts.py`
- Create: `src/cockpit/engine/comparison.py`
- Create: `tests/test_scoring.py`
- Create: `tests/test_alerts.py`

Source: `/mnt/Projects/Projects/macro-cbwatch/automation/`

- [ ] **Step 1: Copy scoring.py**

Copy from `automation/scoring.py`, updating imports:

```python
# Old:
from automation.config import ... (if any YAML loading)
# New:
from cockpit.config import SCORING_LABELS
```

Read the source to identify exact import changes. The scoring module uses `config.yaml` for label thresholds — these are now in `cockpit.config` as `SCORING_LABELS`.

- [ ] **Step 2: Copy alerts.py**

Copy from `automation/alerts.py`, updating:

```python
# Old: loads thresholds from config.yaml
# New: import from cockpit.config
from cockpit.config import (
    FX_ALERT_BANDS,
    ENERGY_THRESHOLDS,
    DEPOSIT_THRESHOLDS,
    DAILY_MOVE_THRESHOLDS,
)
```

Replace the `load_thresholds()` function that reads YAML with direct use of the config constants.

- [ ] **Step 3: Copy comparison.py**

Copy from `automation/comparison.py`, updating:

```python
# Old:
# Hardcoded data/ paths
# New:
from cockpit.config import DATA_DIR
```

- [ ] **Step 4: Write scoring test**

Create `tests/test_scoring.py`:

```python
from cockpit.engine.scoring.scoring import compute_scores, normalize


def test_normalize_within_range():
    breakpoints = [(0.0, 0.0), (100.0, 100.0)]
    assert normalize(50.0, breakpoints) == 50.0


def test_normalize_none_input():
    breakpoints = [(0.0, 0.0), (100.0, 100.0)]
    assert normalize(None, breakpoints) is None


def test_compute_scores_returns_four_currencies():
    # Minimal data dict with required keys
    data = {
        "fed_rates": {"mid": 3.625, "upper": 3.75, "lower": 3.50},
        "ecb_rates": {"deposit_facility": 2.00, "main_refinancing": 2.40},
        "snb_rate": 0.00,
        "daily_indicators": {
            "vix": {"value": 18.0},
            "us_2y": {"value": 4.20},
            "us_10y": {"value": 4.35},
            "breakeven_5y": {"value": 2.30},
            "breakeven_10y": {"value": 2.20},
        },
        "macro_indicators": {
            "pce": {"value": 2.5},
            "core_pce": {"value": 2.8},
            "unemployment": {"value": 4.1},
            "uk_unemployment": {"value": 4.3},
            "uk_10y_yield": {"value": 4.50},
        },
        "usd_chf_latest": {"value": 0.7950},
        "eur_chf_latest": {"value": 0.9040},
        "gbp_chf_latest": {"value": 1.1200},
        "energy": {"brent": {"value": 85.0}, "eu_gas": {"value": 35.0}},
        "sight_deposits": {"domestic": {"value": 450.0}},
        "saron": {"value": 0.0043},
    }
    scores = compute_scores(data)
    assert "USD" in scores
    assert "EUR" in scores
    assert "CHF" in scores
    assert "GBP" in scores
    for ccy, score in scores.items():
        assert 0 <= score.composite <= 100
        assert score.label in ("Calm", "Watch", "Action")
```

- [ ] **Step 5: Write alerts test**

Create `tests/test_alerts.py`:

```python
from cockpit.engine.alerts.alerts import check_alerts


def test_check_alerts_returns_list():
    current = {
        "usd_chf_latest": {"value": 0.90},  # above USD_CHF high of 0.85
        "eur_chf_latest": {"value": 0.93},
        "gbp_chf_latest": {"value": 1.12},
        "energy": {"brent": {"value": 85.0}, "eu_gas": {"value": 35.0}},
        "sight_deposits": {"domestic": {"value": 450.0}},
    }
    deltas = {
        "usd_chf": {"current": 0.90, "1d": {"pct": 0.5}},
        "eur_chf": {"current": 0.93, "1d": {"pct": 0.2}},
        "gbp_chf": {"current": 1.12, "1d": {"pct": 0.1}},
        "brent": {"current": 85.0, "1d": {"pct": 1.0}},
        "eu_gas": {"current": 35.0, "1d": {"pct": 0.5}},
        "vix": {"current": 18.0, "1d": {"pct": 2.0}},
    }
    alerts = check_alerts(current, deltas)
    assert isinstance(alerts, list)
    # USD/CHF at 0.90 is above the 0.85 high band — should trigger
    fx_alerts = [a for a in alerts if a.get("type") == "fx_breach"]
    assert len(fx_alerts) > 0
```

- [ ] **Step 6: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_scoring.py tests/test_alerts.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/engine/scoring/ src/cockpit/engine/alerts/ src/cockpit/engine/comparison.py tests/test_scoring.py tests/test_alerts.py
git commit -m "feat(engine): port scoring, alerts, and comparison from cbwatch"
```

---

### Task 9: Port LLM Agents

**Files:**
- Create: `src/cockpit/agents/models.py`
- Create: `src/cockpit/agents/tools.py`
- Create: `src/cockpit/agents/analyst.py`
- Create: `src/cockpit/agents/reviewer.py`
- Create: `src/cockpit/agents/reporter.py`

Source: `/mnt/Projects/Projects/macro-cbwatch/automation/agents/`

- [ ] **Step 1: Copy agent files**

Copy each file from `automation/agents/`, updating imports:

```python
# Old:
from automation.agents.models import ReviewResult, AnalystOutput, ChartSelection
from automation.agents.tools import create_reviewer_tools
from automation.scoring import compute_scores
from automation.alerts import check_alerts
from automation.comparison import compute_deltas, format_deltas_for_brief
from automation.charts import chart_fx_history, ...

# New:
from cockpit.agents.models import ReviewResult, AnalystOutput, ChartSelection
from cockpit.agents.tools import create_reviewer_tools
from cockpit.engine.scoring.scoring import compute_scores
from cockpit.engine.alerts.alerts import check_alerts
from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief
from cockpit.render.charts import chart_fx_history, ...
```

Also update model config references:

```python
# Old: reads from config.yaml
# New: import from cockpit.config
from cockpit.config import ANALYST_MODEL, REVIEWER_MODEL, OLLAMA_HOST, MAX_REVIEW_RETRIES
```

Read each source file to get exact code and adapt:
- `models.py` — Pydantic models, likely no internal imports
- `tools.py` — reviewer verification tools, update metric aliases
- `analyst.py` — template builder + agent creation
- `reviewer.py` — programmatic checks + agent creation
- `reporter.py` — HTML/markdown generation

- [ ] **Step 2: Write import smoke test**

Create `tests/test_agents.py`:

```python
def test_models_import():
    from cockpit.agents.models import ReviewResult, AnalystOutput, ChartSelection
    assert ReviewResult is not None
    assert AnalystOutput is not None
    assert ChartSelection is not None


def test_analyst_template_builder():
    from cockpit.agents.analyst import _build_template
    assert callable(_build_template)


def test_reviewer_programmatic_check():
    from cockpit.agents.reviewer import programmatic_check
    assert callable(programmatic_check)
```

- [ ] **Step 3: Run test**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_agents.py -v`
Expected: all PASS (may need `agents` optional dependency installed: `uv sync --extra agents`)

- [ ] **Step 4: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/agents/ tests/test_agents.py
git commit -m "feat(agents): port LLM analyst/reviewer/reporter from cbwatch"
```

---

### Task 10: Chart Data Builders

**Files:**
- Create: `src/cockpit/render/charts.py`
- Create: `tests/test_charts.py`

This module produces chart configuration dicts that Jinja2 templates embed as inline JSON for Chart.js.

- [ ] **Step 1: Write the failing test**

Create `tests/test_charts.py`:

```python
from cockpit.render.charts import (
    build_macro_charts,
    build_fx_energy_charts,
    build_pnl_charts,
    build_portfolio_charts,
)


def test_build_macro_charts_empty_data():
    result = build_macro_charts({})
    assert isinstance(result, dict)
    assert "score_cards" in result


def test_build_fx_energy_charts_empty_data():
    result = build_fx_energy_charts({})
    assert isinstance(result, dict)
    assert "fx_series" in result
    assert "energy_series" in result


def test_build_pnl_charts_empty_data():
    result = build_pnl_charts({})
    assert isinstance(result, dict)
    assert "monthly_pnl" in result


def test_build_portfolio_charts_empty_data():
    result = build_portfolio_charts({})
    assert isinstance(result, dict)
    assert "liquidity_ladder" in result


def test_build_fx_energy_charts_with_history():
    data = {
        "usd_chf_history": [
            {"date": "2026-03-01", "value": 0.79},
            {"date": "2026-03-02", "value": 0.80},
        ],
        "eur_chf_history": [
            {"date": "2026-03-01", "value": 0.90},
            {"date": "2026-03-02", "value": 0.91},
        ],
        "gbp_chf_history": [
            {"date": "2026-03-01", "value": 1.11},
            {"date": "2026-03-02", "value": 1.12},
        ],
        "energy": {
            "brent_history": [{"date": "2026-03-01", "value": 85.0}],
            "eu_gas_history": [{"date": "2026-03-01", "value": 35.0}],
        },
    }
    result = build_fx_energy_charts(data)
    assert len(result["fx_series"]["usd_chf"]["dates"]) == 2
    assert result["fx_series"]["usd_chf"]["values"] == [0.79, 0.80]


def test_build_pnl_charts_with_data():
    pnl_data = {
        "months": ["2026/04", "2026/05", "2026/06"],
        "by_currency": {
            "CHF": {"shock_0": [100, 200, 150], "shock_50": [80, 180, 130]},
            "EUR": {"shock_0": [50, 60, 70], "shock_50": [40, 50, 60]},
        },
    }
    result = build_pnl_charts(pnl_data)
    assert result["monthly_pnl"]["labels"] == ["2026/04", "2026/05", "2026/06"]
    assert "CHF" in result["monthly_pnl"]["datasets"]


def test_build_portfolio_charts_with_data():
    portfolio_data = {
        "exposure": {
            "buckets": [
                {"label": "O/N", "inflows": 1000, "outflows": 500, "net": 500, "cumulative": 500},
                {"label": "D+1", "inflows": 800, "outflows": 900, "net": -100, "cumulative": 400},
            ],
            "survival_days": 45,
        },
        "positions": {
            "currencies": {
                "CHF": {"assets": 5e9, "liabilities": 4e9, "net": 1e9},
            },
        },
        "counterparty": {
            "concentration": {
                "top_10": [{"counterparty": "A", "nominal": 500e6, "pct_total": 12.5}],
                "hhi": 850,
            },
            "rating": {
                "AAA-AA": {"nominal": 2e9, "pct": 50.0},
                "A": {"nominal": 1e9, "pct": 25.0},
            },
        },
    }
    result = build_portfolio_charts(portfolio_data)
    assert len(result["liquidity_ladder"]["labels"]) == 2
    assert result["liquidity_ladder"]["inflows"] == [1000, 800]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_charts.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/cockpit/render/charts.py`:

```python
"""Chart data builders for cockpit HTML templates.

Each function takes raw data dicts (from JSON intermediates) and returns
structured dicts that Jinja2 templates embed as inline JSON for Chart.js.
"""

from __future__ import annotations

from cockpit.config import FX_ALERT_BANDS, SCENARIOS


def build_macro_charts(data: dict) -> dict:
    """Build data for Tab 1: Macro Overview.

    Returns dict with keys: score_cards, alerts, cb_rates, key_dates.
    """
    scores = data.get("scores", {})
    alerts = data.get("alerts", [])

    score_cards = {}
    for ccy in ("USD", "EUR", "CHF", "GBP"):
        s = scores.get(ccy, {})
        score_cards[ccy] = {
            "composite": s.get("composite", 0),
            "label": s.get("label", "N/A"),
            "driver": s.get("driver", ""),
            "families": s.get("families", {}),
        }

    cb_rates = {}
    rates = data.get("rates", {})
    if "fed_rates" in rates:
        cb_rates["Fed"] = {"rate": rates["fed_rates"].get("mid"), "name": "Fed Funds"}
    if "ecb_rates" in rates:
        cb_rates["ECB"] = {"rate": rates["ecb_rates"].get("deposit_facility"), "name": "Deposit Facility"}
    snb = rates.get("snb_rate")
    if snb is not None:
        cb_rates["BNS"] = {"rate": snb, "name": "Policy Rate"}

    return {
        "score_cards": score_cards,
        "alerts": alerts,
        "cb_rates": cb_rates,
        "key_dates": data.get("key_dates", []),
    }


def build_fx_energy_charts(data: dict) -> dict:
    """Build data for Tab 2: FX & Energy.

    Returns dict with keys: fx_series, energy_series, deltas, scenario_bands.
    """
    fx_series = {}
    for pair in ("usd_chf", "eur_chf", "gbp_chf"):
        history = data.get(f"{pair}_history", [])
        fx_series[pair] = {
            "dates": [p["date"] for p in history],
            "values": [p["value"] for p in history],
        }

    energy = data.get("energy", {})
    energy_series = {}
    for fuel in ("brent", "eu_gas"):
        history = energy.get(f"{fuel}_history", [])
        energy_series[fuel] = {
            "dates": [p["date"] for p in history],
            "values": [p["value"] for p in history],
        }

    return {
        "fx_series": fx_series,
        "energy_series": energy_series,
        "deltas": data.get("deltas", {}),
        "scenario_bands": SCENARIOS,
        "fx_bands": FX_ALERT_BANDS,
    }


def build_pnl_charts(data: dict) -> dict:
    """Build data for Tab 3: P&L Projection.

    Returns dict with keys: monthly_pnl, shock_comparison, book2_mtm, strategy_decomposition.
    """
    months = data.get("months", [])
    by_currency = data.get("by_currency", {})

    datasets = {}
    for ccy, shocks in by_currency.items():
        datasets[ccy] = {
            "shock_0": shocks.get("shock_0", []),
            "shock_50": shocks.get("shock_50", []),
            "shock_wirp": shocks.get("shock_wirp", []),
        }

    return {
        "monthly_pnl": {
            "labels": months,
            "datasets": datasets,
        },
        "shock_comparison": data.get("shock_comparison", {}),
        "book2_mtm": data.get("book2_mtm", []),
        "strategy_decomposition": data.get("strategy_decomposition", {}),
    }


def build_portfolio_charts(data: dict) -> dict:
    """Build data for Tab 4: Portfolio Snapshot.

    Returns dict with keys: liquidity_ladder, positions, concentration, rating, hqla.
    """
    exposure = data.get("exposure", {})
    buckets = exposure.get("buckets", [])

    liquidity_ladder = {
        "labels": [b["label"] for b in buckets],
        "inflows": [b["inflows"] for b in buckets],
        "outflows": [b["outflows"] for b in buckets],
        "net": [b["net"] for b in buckets],
        "cumulative": [b["cumulative"] for b in buckets],
        "survival_days": exposure.get("survival_days"),
    }

    positions = data.get("positions", {}).get("currencies", {})

    cpty = data.get("counterparty", {})
    concentration = cpty.get("concentration", {})
    rating = cpty.get("rating", {})
    hqla = cpty.get("hqla", {})

    return {
        "liquidity_ladder": liquidity_ladder,
        "positions": positions,
        "concentration": concentration,
        "rating": rating,
        "hqla": hqla,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_charts.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/render/charts.py tests/test_charts.py
git commit -m "feat(render): chart data builders for all 5 cockpit tabs"
```

---

### Task 11: Jinja2 Renderer

**Files:**
- Create: `src/cockpit/render/renderer.py`
- Create: `tests/test_renderer.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_renderer.py`:

```python
import json
from pathlib import Path
from cockpit.render.renderer import render_cockpit


def test_render_cockpit_empty_context(tmp_path: Path):
    output = tmp_path / "test_cockpit.html"
    render_cockpit(
        macro_data=None,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    assert output.exists()
    html = output.read_text()
    assert "Swiss Treasury Cockpit" in html
    assert "2026-04-03" in html
    # All tabs should have placeholders
    assert "cockpit fetch" in html or "cockpit compute" in html


def test_render_cockpit_with_macro_data(tmp_path: Path):
    output = tmp_path / "test_cockpit.html"
    macro = {
        "rates": {"fed_rates": {"mid": 3.625}},
        "scores": {"USD": {"composite": 55, "label": "Watch", "driver": "policy", "families": {}}},
        "alerts": [],
    }
    render_cockpit(
        macro_data=macro,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    html = output.read_text()
    assert "Watch" in html
    assert "3.625" in html or "3.63" in html


def test_render_cockpit_self_contained(tmp_path: Path):
    """Verify no external CDN references."""
    output = tmp_path / "test_cockpit.html"
    render_cockpit(
        macro_data=None,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    html = output.read_text()
    assert "cdn." not in html.lower()
    assert "unpkg.com" not in html.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/cockpit/render/renderer.py`:

```python
"""Jinja2 renderer that assembles cockpit HTML from tab partials."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from cockpit.render.charts import (
    build_macro_charts,
    build_fx_energy_charts,
    build_pnl_charts,
    build_portfolio_charts,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _json_filter(value: object) -> str:
    """Jinja2 filter to safely embed Python objects as inline JSON."""
    return json.dumps(value, default=str)


def render_cockpit(
    *,
    macro_data: dict | None,
    pnl_data: dict | None,
    portfolio_data: dict | None,
    scores_data: dict | None,
    brief_data: dict | None,
    date: str,
    output_path: Path,
) -> Path:
    """Render the cockpit HTML file from available data.

    Any data argument can be None — the template renders a placeholder for
    missing tabs instead of failing.

    Returns the output path.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    env.filters["tojson_safe"] = _json_filter

    # Build chart data from whatever is available
    macro_charts = build_macro_charts(macro_data or {})
    if scores_data:
        macro_charts["score_cards"] = {
            ccy: {
                "composite": s.get("composite", 0),
                "label": s.get("label", "N/A"),
                "driver": s.get("driver", ""),
                "families": s.get("families", {}),
            }
            for ccy, s in scores_data.items()
        }

    fx_energy_charts = build_fx_energy_charts(macro_data or {})
    pnl_charts = build_pnl_charts(pnl_data or {})
    portfolio_charts = build_portfolio_charts(portfolio_data or {})

    context = {
        "date": date,
        "has_macro": macro_data is not None,
        "has_pnl": pnl_data is not None,
        "has_portfolio": portfolio_data is not None,
        "has_brief": brief_data is not None,
        "macro": macro_charts,
        "fx_energy": fx_energy_charts,
        "pnl": pnl_charts,
        "portfolio": portfolio_charts,
        "brief": brief_data or {},
    }

    template = env.get_template("cockpit.html")
    html = template.render(**context)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Create the cockpit.html template shell**

Create `src/cockpit/render/templates/cockpit.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Swiss Treasury Cockpit — {{ date }}</title>
<style>
:root {
  --bg-primary: #0d1117;
  --bg-secondary: #161b22;
  --bg-tertiary: #21262d;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --border: #30363d;
  --accent-blue: #58a6ff;
  --accent-green: #3fb950;
  --accent-yellow: #d29922;
  --accent-red: #f85149;
  --accent-orange: #e67e22;
  --fed-blue: #002868;
  --ecb-orange: #e67e22;
  --bns-red: #d62828;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.5;
}
.header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}
.header h1 { font-size: 1.25rem; font-weight: 600; }
.header .date { color: var(--text-secondary); font-size: 0.875rem; }
.tabs {
  display: flex; gap: 0;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
}
.tab-btn {
  padding: 12px 20px;
  background: none; border: none;
  color: var(--text-secondary);
  cursor: pointer; font-size: 0.875rem;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active {
  color: var(--accent-blue);
  border-bottom-color: var(--accent-blue);
}
.tab-content { display: none; padding: 24px; }
.tab-content.active { display: block; }
.placeholder {
  text-align: center; padding: 80px 24px;
  color: var(--text-secondary);
}
.placeholder code {
  background: var(--bg-tertiary); padding: 4px 8px;
  border-radius: 4px; font-size: 0.875rem;
}
.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px; padding: 16px;
}
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
table {
  width: 100%; border-collapse: collapse;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden;
}
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--bg-tertiary); color: var(--text-secondary); font-weight: 600; font-size: 0.8rem; text-transform: uppercase; }
.label-calm { color: var(--accent-green); }
.label-watch { color: var(--accent-yellow); }
.label-action { color: var(--accent-red); }
.alert-badge {
  display: inline-block; padding: 2px 8px;
  border-radius: 12px; font-size: 0.75rem; font-weight: 600;
}
.alert-critical { background: rgba(248,81,73,0.2); color: var(--accent-red); }
.alert-high { background: rgba(248,81,73,0.15); color: var(--accent-red); }
.alert-medium { background: rgba(210,153,34,0.2); color: var(--accent-yellow); }
.alert-low { background: rgba(63,185,80,0.2); color: var(--accent-green); }
canvas { max-width: 100%; }
.chart-container { position: relative; height: 300px; margin: 16px 0; }
.brief-content { max-width: 800px; line-height: 1.7; }
.brief-content h2 { margin-top: 24px; margin-bottom: 8px; font-size: 1.1rem; }
.brief-content h3 { margin-top: 16px; margin-bottom: 6px; font-size: 1rem; color: var(--text-secondary); }
.fact-checked { display: inline-block; padding: 4px 12px; border-radius: 12px; font-size: 0.8rem; }
.fact-checked.reviewed { background: rgba(63,185,80,0.2); color: var(--accent-green); }
.fact-checked.unverified { background: rgba(210,153,34,0.2); color: var(--accent-yellow); }
@media print {
  body { background: #fff; color: #000; }
  .tabs { display: none; }
  .tab-content { display: block !important; page-break-before: always; }
  .header { background: #fff; border-bottom: 2px solid #000; }
}
</style>
</head>
<body>

<div class="header">
  <h1>Swiss Treasury Cockpit</h1>
  <span class="date">{{ date }}</span>
</div>

<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('macro')">Macro Overview</button>
  <button class="tab-btn" onclick="switchTab('fx-energy')">FX &amp; Energy</button>
  <button class="tab-btn" onclick="switchTab('pnl')">P&amp;L Projection</button>
  <button class="tab-btn" onclick="switchTab('portfolio')">Portfolio Snapshot</button>
  <button class="tab-btn" onclick="switchTab('brief')">Daily Brief</button>
</div>

{% if has_macro %}
{% include '_macro.html' %}
{% else %}
<div id="tab-macro" class="tab-content active">
  <div class="placeholder">
    <p>Macro data not available.</p>
    <p>Run <code>cockpit fetch --date {{ date }}</code> first.</p>
  </div>
</div>
{% endif %}

{% if has_macro %}
{% include '_fx_energy.html' %}
{% else %}
<div id="tab-fx-energy" class="tab-content">
  <div class="placeholder">
    <p>FX &amp; Energy data not available.</p>
    <p>Run <code>cockpit fetch --date {{ date }}</code> first.</p>
  </div>
</div>
{% endif %}

{% if has_pnl %}
{% include '_pnl.html' %}
{% else %}
<div id="tab-pnl" class="tab-content">
  <div class="placeholder">
    <p>P&amp;L data not available.</p>
    <p>Run <code>cockpit compute --date {{ date }}</code> first.</p>
  </div>
</div>
{% endif %}

{% if has_portfolio %}
{% include '_portfolio.html' %}
{% else %}
<div id="tab-portfolio" class="tab-content">
  <div class="placeholder">
    <p>Portfolio data not available.</p>
    <p>Run <code>cockpit compute --date {{ date }}</code> first.</p>
  </div>
</div>
{% endif %}

{% if has_brief %}
{% include '_brief.html' %}
{% else %}
<div id="tab-brief" class="tab-content">
  <div class="placeholder">
    <p>Daily brief not available.</p>
    <p>Run <code>cockpit analyze --date {{ date }}</code> first.</p>
  </div>
</div>
{% endif %}

<script>
function switchTab(id) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + id).classList.add('active');
  event.target.classList.add('active');
}
</script>

</body>
</html>
```

- [ ] **Step 5: Create placeholder tab partials**

Create minimal partials so the template renders. Each will be fleshed out in later tasks.

Create `src/cockpit/render/templates/_macro.html`:

```html
<div id="tab-macro" class="tab-content active">
  <div class="grid-4" style="margin-bottom: 24px;">
    {% for ccy in ['USD', 'EUR', 'CHF', 'GBP'] %}
    <div class="card">
      <div style="font-size: 0.8rem; color: var(--text-secondary);">{{ ccy }}</div>
      <div style="font-size: 1.8rem; font-weight: 700;">{{ macro.score_cards[ccy].composite | int }}</div>
      {% set lbl = macro.score_cards[ccy].label %}
      <div class="label-{{ lbl | lower }}">{{ lbl }}</div>
      <div style="font-size: 0.75rem; color: var(--text-secondary); margin-top: 4px;">
        Driver: {{ macro.score_cards[ccy].driver }}
      </div>
    </div>
    {% endfor %}
  </div>

  {% if macro.alerts %}
  <div class="card" style="margin-bottom: 24px;">
    <h3 style="margin-bottom: 12px; font-size: 0.9rem;">Active Alerts</h3>
    {% for alert in macro.alerts %}
    <span class="alert-badge alert-{{ alert.severity }}">{{ alert.message }}</span>
    {% endfor %}
  </div>
  {% endif %}

  {% if macro.cb_rates %}
  <div class="card">
    <h3 style="margin-bottom: 12px; font-size: 0.9rem;">Central Bank Rates</h3>
    <table>
      <thead><tr><th>Bank</th><th>Instrument</th><th>Rate</th></tr></thead>
      <tbody>
      {% for bank, info in macro.cb_rates.items() %}
        <tr><td>{{ bank }}</td><td>{{ info.name }}</td><td>{{ "%.3f" | format(info.rate) }}%</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>
```

Create `src/cockpit/render/templates/_fx_energy.html`:

```html
<div id="tab-fx-energy" class="tab-content">
  <div class="grid-2" style="margin-bottom: 24px;">
    {% for pair, label in [('usd_chf', 'USD/CHF'), ('eur_chf', 'EUR/CHF'), ('gbp_chf', 'GBP/CHF')] %}
    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 8px;">{{ label }}</h3>
      <div class="chart-container">
        <canvas id="chart-{{ pair }}"></canvas>
      </div>
    </div>
    {% endfor %}
  </div>
  <div class="grid-2">
    {% for fuel, label in [('brent', 'Brent Crude ($/bbl)'), ('eu_gas', 'EU Gas TTF (EUR/MWh)')] %}
    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 8px;">{{ label }}</h3>
      <div class="chart-container">
        <canvas id="chart-{{ fuel }}"></canvas>
      </div>
    </div>
    {% endfor %}
  </div>

  {% if fx_energy.deltas %}
  <div class="card" style="margin-top: 24px;">
    <h3 style="font-size: 0.9rem; margin-bottom: 12px;">Historical Deltas</h3>
    <table>
      <thead><tr><th>Metric</th><th>Current</th><th>1D</th><th>1W</th><th>1M</th></tr></thead>
      <tbody>
      {% for key, d in fx_energy.deltas.items() %}
        <tr>
          <td>{{ key }}</td>
          <td>{{ "%.4f" | format(d.current) if d.current else "—" }}</td>
          <td>{{ "%.2f%%" | format(d['1d'].pct) if d.get('1d') else "—" }}</td>
          <td>{{ "%.2f%%" | format(d['1w'].pct) if d.get('1w') else "—" }}</td>
          <td>{{ "%.2f%%" | format(d['1m'].pct) if d.get('1m') else "—" }}</td>
        </tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <script>
  (function() {
    const fxData = {{ fx_energy.fx_series | tojson_safe }};
    const bands = {{ fx_energy.fx_bands | tojson_safe }};
    {% for pair in ['usd_chf', 'eur_chf', 'gbp_chf'] %}
    if (fxData['{{ pair }}'] && fxData['{{ pair }}'].dates.length > 0) {
      const ctx = document.getElementById('chart-{{ pair }}');
      if (ctx && typeof Chart !== 'undefined') {
        new Chart(ctx, {
          type: 'line',
          data: {
            labels: fxData['{{ pair }}'].dates,
            datasets: [{
              data: fxData['{{ pair }}'].values,
              borderColor: 'rgb(88,166,255)',
              borderWidth: 1.5,
              pointRadius: 0,
              fill: false,
            }]
          },
          options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: { x: { ticks: { color: '#8b949e' } }, y: { ticks: { color: '#8b949e' } } }
          }
        });
      }
    }
    {% endfor %}
  })();
  </script>
</div>
```

Create `src/cockpit/render/templates/_pnl.html`:

```html
<div id="tab-pnl" class="tab-content">
  <div class="card" style="margin-bottom: 24px;">
    <h3 style="font-size: 0.9rem; margin-bottom: 8px;">Monthly P&amp;L by Currency (BOOK1)</h3>
    <div class="chart-container" style="height: 400px;">
      <canvas id="chart-monthly-pnl"></canvas>
    </div>
    <div style="margin-top: 8px; text-align: right;">
      <button onclick="togglePnlView()" style="background: var(--bg-tertiary); border: 1px solid var(--border); color: var(--text-primary); padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.8rem;">
        Toggle Stacked / Side-by-Side
      </button>
    </div>
  </div>

  {% if pnl.book2_mtm %}
  <div class="card" style="margin-bottom: 24px;">
    <h3 style="font-size: 0.9rem; margin-bottom: 12px;">BOOK2 MTM — IRS Positions</h3>
    <table>
      <thead><tr><th>Deal</th><th>Currency</th><th>MTM</th></tr></thead>
      <tbody>
      {% for row in pnl.book2_mtm %}
        <tr><td>{{ row.deal }}</td><td>{{ row.currency }}</td><td>{{ "{:,.0f}".format(row.mtm) }}</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  <script>
  let pnlStacked = true;
  const pnlData = {{ pnl.monthly_pnl | tojson_safe }};
  const colors = { CHF: '#d62828', EUR: '#e67e22', USD: '#002868', GBP: '#6f42c1' };
  let pnlChart = null;

  function renderPnlChart() {
    const ctx = document.getElementById('chart-monthly-pnl');
    if (!ctx || typeof Chart === 'undefined' || !pnlData.labels.length) return;
    if (pnlChart) pnlChart.destroy();
    const datasets = [];
    for (const [ccy, shocks] of Object.entries(pnlData.datasets)) {
      datasets.push({
        label: ccy + ' (base)',
        data: shocks.shock_0 || [],
        backgroundColor: colors[ccy] || '#58a6ff',
        stack: pnlStacked ? 'base' : ccy,
      });
    }
    pnlChart = new Chart(ctx, {
      type: 'bar',
      data: { labels: pnlData.labels, datasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#e6edf3' } } },
        scales: {
          x: { stacked: pnlStacked, ticks: { color: '#8b949e' } },
          y: { stacked: pnlStacked, ticks: { color: '#8b949e' } }
        }
      }
    });
  }
  function togglePnlView() { pnlStacked = !pnlStacked; renderPnlChart(); }
  renderPnlChart();
  </script>
</div>
```

Create `src/cockpit/render/templates/_portfolio.html`:

```html
<div id="tab-portfolio" class="tab-content">
  <div class="card" style="margin-bottom: 24px;">
    <h3 style="font-size: 0.9rem; margin-bottom: 8px;">Liquidity Ladder</h3>
    <div class="chart-container" style="height: 400px;">
      <canvas id="chart-liquidity"></canvas>
    </div>
    {% if portfolio.liquidity_ladder.survival_days %}
    <div style="margin-top: 8px; font-size: 0.85rem; color: var(--accent-yellow);">
      Survival horizon: {{ portfolio.liquidity_ladder.survival_days }} days
    </div>
    {% endif %}
  </div>

  <div class="grid-2" style="margin-bottom: 24px;">
    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 12px;">Positions by Currency</h3>
      <table>
        <thead><tr><th>Currency</th><th>Assets</th><th>Liabilities</th><th>Net</th></tr></thead>
        <tbody>
        {% for ccy, pos in portfolio.positions.items() %}
          <tr>
            <td>{{ ccy }}</td>
            <td>{{ "{:,.0f}".format(pos.assets) if pos.assets else "—" }}</td>
            <td>{{ "{:,.0f}".format(pos.liabilities) if pos.liabilities else "—" }}</td>
            <td>{{ "{:,.0f}".format(pos.net) if pos.net else "—" }}</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 8px;">Counterparty Concentration</h3>
      <div class="chart-container">
        <canvas id="chart-concentration"></canvas>
      </div>
      {% if portfolio.concentration.hhi %}
      <div style="margin-top: 4px; font-size: 0.8rem; color: var(--text-secondary);">
        HHI: {{ portfolio.concentration.hhi }}
      </div>
      {% endif %}
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 12px;">Rating Distribution</h3>
      <table>
        <thead><tr><th>Rating</th><th>Nominal</th><th>%</th></tr></thead>
        <tbody>
        {% for bucket, info in portfolio.rating.items() %}
          <tr>
            <td>{{ bucket }}</td>
            <td>{{ "{:,.0f}".format(info.nominal) if info.nominal else "—" }}</td>
            <td>{{ "%.1f" | format(info.pct) if info.pct else "—" }}%</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h3 style="font-size: 0.9rem; margin-bottom: 12px;">HQLA Composition</h3>
      <table>
        <thead><tr><th>Level</th><th>Nominal</th><th>%</th></tr></thead>
        <tbody>
        {% for level, info in portfolio.hqla.items() if level != 'total_hqla' %}
          <tr>
            <td>{{ level }}</td>
            <td>{{ "{:,.0f}".format(info.nominal) if info.nominal else "—" }}</td>
            <td>{{ "%.1f" | format(info.pct) if info.pct else "—" }}%</td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

  <script>
  (function() {
    const ladder = {{ portfolio.liquidity_ladder | tojson_safe }};
    const ctx = document.getElementById('chart-liquidity');
    if (ctx && typeof Chart !== 'undefined' && ladder.labels.length > 0) {
      new Chart(ctx, {
        type: 'bar',
        data: {
          labels: ladder.labels,
          datasets: [
            { label: 'Inflows', data: ladder.inflows, backgroundColor: 'rgba(63,185,80,0.7)' },
            { label: 'Outflows', data: ladder.outflows.map(v => -v), backgroundColor: 'rgba(248,81,73,0.7)' },
            { label: 'Cumulative', data: ladder.cumulative, type: 'line', borderColor: '#58a6ff', borderWidth: 2, pointRadius: 0, fill: false, yAxisID: 'y1' },
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { labels: { color: '#e6edf3' } } },
          scales: {
            x: { ticks: { color: '#8b949e', maxRotation: 45 } },
            y: { ticks: { color: '#8b949e' } },
            y1: { position: 'right', grid: { drawOnChartArea: false }, ticks: { color: '#58a6ff' } }
          }
        }
      });
    }

    const concData = {{ portfolio.concentration | tojson_safe }};
    const concCtx = document.getElementById('chart-concentration');
    if (concCtx && typeof Chart !== 'undefined' && concData.top_10 && concData.top_10.length > 0) {
      new Chart(concCtx, {
        type: 'doughnut',
        data: {
          labels: concData.top_10.map(c => c.counterparty),
          datasets: [{ data: concData.top_10.map(c => c.nominal), backgroundColor: ['#d62828','#e67e22','#002868','#6f42c1','#58a6ff','#3fb950','#d29922','#8b949e','#f0883e','#a5d6ff'] }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'right', labels: { color: '#e6edf3', font: { size: 10 } } } }
        }
      });
    }
  })();
  </script>
</div>
```

Create `src/cockpit/render/templates/_brief.html`:

```html
<div id="tab-brief" class="tab-content">
  <div class="card">
    {% if brief.reviewed is defined %}
    <span class="fact-checked {{ 'reviewed' if brief.reviewed else 'unverified' }}">
      {{ 'Fact-Checked' if brief.reviewed else 'Unverified' }}
    </span>
    {% endif %}
    <div class="brief-content" style="margin-top: 16px;">
      {{ brief.html | default("No brief content available.") }}
    </div>
  </div>
</div>
```

- [ ] **Step 6: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_renderer.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/render/ tests/test_renderer.py
git commit -m "feat(render): Jinja2 renderer with cockpit shell and 5 tab templates"
```

---

### Task 12: CLI Entry Points

**Files:**
- Create: `src/cockpit/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock
from cockpit.cli import cmd_render


def test_cmd_render_creates_html(tmp_path: Path):
    """render command should produce HTML even with no input data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    cmd_render(date="2026-04-03", data_dir=data_dir, output_dir=output_dir)

    html_files = list(output_dir.glob("*.html"))
    assert len(html_files) == 1
    assert "2026-04-03" in html_files[0].name
    html = html_files[0].read_text()
    assert "Swiss Treasury Cockpit" in html


def test_cmd_render_with_macro_data(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    macro = {"rates": {"fed_rates": {"mid": 3.625}}, "alerts": []}
    (data_dir / "2026-04-03_macro_snapshot.json").write_text(json.dumps(macro))

    cmd_render(date="2026-04-03", data_dir=data_dir, output_dir=output_dir)

    html = (output_dir / "2026-04-03_cockpit.html").read_text()
    assert "3.625" in html or "cockpit fetch" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `src/cockpit/cli.py`:

```python
"""CLI entry points for Swiss Treasury Cockpit.

Commands:
    cockpit fetch     — Fetch macro data (FRED, ECB, SNB, yfinance)
    cockpit compute   — Run P&L engine + scoring + alerts + portfolio snapshot
    cockpit analyze   — Generate LLM daily brief (requires Ollama)
    cockpit render    — Render HTML cockpit from available data
    cockpit run-all   — Execute all steps in sequence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_json(data: dict, path: Path) -> None:
    """Write a dict as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def cmd_fetch(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Fetch macro data from FRED, ECB, SNB, yfinance."""
    from cockpit.data.manager import DataManager

    print(f"[fetch] Fetching macro data for {date}...")
    dm = DataManager()
    results = asyncio.run(dm.refresh_all_data())

    if not dry_run:
        output_path = data_dir / f"{date}_macro_snapshot.json"
        _save_json(results, output_path)
        print(f"[fetch] Saved to {output_path}")

        stale = results.get("stale", [])
        if stale:
            print(f"[fetch] Warning: stale sources: {', '.join(stale)}")
    else:
        print("[fetch] Dry run — data not saved.")


def cmd_compute(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
) -> None:
    """Run P&L engine, scoring, alerts, and portfolio snapshot."""
    from cockpit.engine.pnl.forecast import ForecastRatePnL
    from cockpit.engine.snapshot import build_portfolio_snapshot
    from cockpit.data.parsers import parse_mtd, parse_echeancier, parse_reference_table

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    # --- P&L ---
    print(f"[compute] Running P&L engine for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt,
        dateRates=date_dt,
        export=False,
        input_dir=input_dir,
        output_dir=str(output_dir),
    )
    pnl.run()

    # Serialize P&L results to JSON
    pnl_result = {}
    if pnl.pnlAllS is not None:
        months = sorted(pnl.pnlAllS.index.get_level_values("Month").unique().tolist())
        pnl_result["months"] = [str(m) for m in months]
        pnl_result["by_currency"] = {}
        for ccy in pnl.pnlAllS.index.get_level_values("Deal currency").unique():
            ccy_data = pnl.pnlAllS.xs(ccy, level="Deal currency")
            pnl_result["by_currency"][ccy] = {}
            for shock in ccy_data.index.get_level_values("Shock").unique():
                shock_data = ccy_data.xs(shock, level="Shock")
                pnl_result["by_currency"][ccy][f"shock_{shock}"] = shock_data.groupby("Month")["PnL"].sum().tolist()

    # --- Portfolio Snapshot ---
    print("[compute] Building portfolio snapshot...")
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
    fx_rates = {}
    if macro_data:
        for pair, key in [("USD", "usd_chf_latest"), ("EUR", "eur_chf_latest"), ("GBP", "gbp_chf_latest")]:
            latest = macro_data.get(key, {})
            if isinstance(latest, dict) and "value" in latest:
                fx_rates[pair] = latest["value"]

    ref_table_path = Path(input_dir) / "reference_table.xlsx" if input_dir else None
    portfolio_result = {}
    if pnl.pnlData is not None and pnl.scheduleData is not None:
        import pandas as pd
        ref_table = parse_reference_table(ref_table_path) if ref_table_path and ref_table_path.exists() else pd.DataFrame(columns=["counterparty", "rating", "hqla_level", "country"])
        portfolio_result = build_portfolio_snapshot(
            echeancier=pnl.scheduleData,
            deals=pnl.pnlData,
            ref_table=ref_table,
            fx_rates=fx_rates,
            ref_date=date_dt.date(),
        )

    # --- Scoring & Alerts ---
    scores_result = {}
    if macro_data:
        print("[compute] Computing scores and alerts...")
        from cockpit.engine.scoring.scoring import compute_scores
        from cockpit.engine.alerts.alerts import check_alerts
        from cockpit.engine.comparison import compute_deltas

        scores = compute_scores(macro_data)
        scores_result = {
            ccy: {
                "composite": s.composite,
                "label": s.label,
                "driver": s.driver,
                "families": {
                    fname: {"score": f.score, "label": f.label, "confidence": f.confidence}
                    for fname, f in s.families.items()
                },
            }
            for ccy, s in scores.items()
        }

        deltas = compute_deltas(macro_data)
        alerts = check_alerts(macro_data, deltas)
        scores_result["_alerts"] = alerts
        scores_result["_deltas"] = deltas

    if not dry_run:
        if pnl_result:
            _save_json(pnl_result, data_dir / f"{date}_pnl.json")
            print(f"[compute] Saved P&L to {data_dir / f'{date}_pnl.json'}")
        if portfolio_result:
            _save_json(portfolio_result, data_dir / f"{date}_portfolio.json")
            print(f"[compute] Saved portfolio to {data_dir / f'{date}_portfolio.json'}")
        if scores_result:
            _save_json(scores_result, data_dir / f"{date}_scores.json")
            print(f"[compute] Saved scores to {data_dir / f'{date}_scores.json'}")
    else:
        print("[compute] Dry run — data not saved.")


def cmd_analyze(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Generate LLM daily brief using Ollama agents."""
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
    if macro_data is None:
        print(f"[analyze] Error: {macro_path} not found. Run 'cockpit fetch' first.")
        sys.exit(1)

    scores_path = data_dir / f"{date}_scores.json"
    scores_data = _load_json(scores_path) or {}

    from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief
    from cockpit.engine.alerts.alerts import check_alerts
    from cockpit.agents.analyst import _build_template, create_analyst_agent
    from cockpit.agents.reviewer import programmatic_check, create_reviewer_agent
    from cockpit.agents.reporter import generate_html_brief
    from cockpit.config import MAX_REVIEW_RETRIES

    deltas = scores_data.get("_deltas", compute_deltas(macro_data))
    alerts = scores_data.get("_alerts", check_alerts(macro_data, deltas))
    delta_table = format_deltas_for_brief(deltas)

    print(f"[analyze] Building analyst template for {date}...")
    template = _build_template(macro_data, deltas, delta_table, alerts)

    print("[analyze] Running analyst agent...")
    analyst = create_analyst_agent()
    brief_text = asyncio.run(analyst.run(template))

    print("[analyze] Running reviewer agent...")
    reviewer = create_reviewer_agent()
    reviewed = False
    for attempt in range(MAX_REVIEW_RETRIES):
        errors = programmatic_check(brief_text, macro_data)
        if not errors:
            reviewed = True
            break
        print(f"[analyze] Review attempt {attempt + 1}: {len(errors)} issues found, retrying...")
        brief_text = asyncio.run(analyst.run(template))

    brief_html = generate_html_brief(brief_text, macro_data, deltas)

    result = {
        "date": date,
        "reviewed": reviewed,
        "html": brief_html,
        "text": brief_text,
    }

    if not dry_run:
        output_path = data_dir / f"{date}_brief.json"
        _save_json(result, output_path)
        print(f"[analyze] Saved brief to {output_path}")
    else:
        print("[analyze] Dry run — brief not saved.")


def cmd_render(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Render HTML cockpit from available JSON intermediates."""
    from cockpit.render.renderer import render_cockpit

    macro_data = _load_json(data_dir / f"{date}_macro_snapshot.json")
    pnl_data = _load_json(data_dir / f"{date}_pnl.json")
    portfolio_data = _load_json(data_dir / f"{date}_portfolio.json")
    scores_data = _load_json(data_dir / f"{date}_scores.json")
    brief_data = _load_json(data_dir / f"{date}_brief.json")

    output_path = output_dir / f"{date}_cockpit.html"

    print(f"[render] Rendering cockpit for {date}...")
    available = []
    if macro_data:
        available.append("macro")
    if pnl_data:
        available.append("pnl")
    if portfolio_data:
        available.append("portfolio")
    if scores_data:
        available.append("scores")
    if brief_data:
        available.append("brief")
    print(f"[render] Available data: {', '.join(available) or 'none'}")

    render_cockpit(
        macro_data=macro_data,
        pnl_data=pnl_data,
        portfolio_data=portfolio_data,
        scores_data=scores_data,
        brief_data=brief_data,
        date=date,
        output_path=output_path,
    )
    print(f"[render] Output: {output_path}")


def cmd_run_all(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
) -> None:
    """Execute all pipeline steps in sequence."""
    cmd_fetch(date=date, data_dir=data_dir, dry_run=dry_run)
    cmd_compute(date=date, input_dir=input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=dry_run)
    try:
        cmd_analyze(date=date, data_dir=data_dir, dry_run=dry_run)
    except Exception as e:
        print(f"[run-all] Analyze step failed (Ollama may be unavailable): {e}")
        print("[run-all] Continuing without daily brief...")
    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cockpit",
        description="Swiss Treasury Cockpit — unified dashboard pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch macro data")
    p_fetch.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_fetch.add_argument("--dry-run", action="store_true")

    # compute
    p_compute = sub.add_parser("compute", help="Run P&L + scoring + alerts + portfolio")
    p_compute.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_compute.add_argument("--input-dir", help="Path to Excel input files")
    p_compute.add_argument("--dry-run", action="store_true")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Generate LLM daily brief")
    p_analyze.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_analyze.add_argument("--dry-run", action="store_true")

    # render
    p_render = sub.add_parser("render", help="Render HTML cockpit")
    p_render.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")

    # run-all
    p_all = sub.add_parser("run-all", help="Execute all steps")
    p_all.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_all.add_argument("--input-dir", help="Path to Excel input files")
    p_all.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    data_dir = DATA_DIR
    output_dir = OUTPUT_DIR

    if args.command == "fetch":
        cmd_fetch(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "compute":
        cmd_compute(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run)
    elif args.command == "analyze":
        cmd_analyze(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "render":
        cmd_render(date=args.date, data_dir=data_dir, output_dir=output_dir)
    elif args.command == "run-all":
        cmd_run_all(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run)
```

- [ ] **Step 4: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_cli.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add src/cockpit/cli.py tests/test_cli.py
git commit -m "feat(cli): composable CLI with fetch/compute/analyze/render/run-all commands"
```

---

### Task 13: CLAUDE.md

**Files:**
- Create: `CLAUDE.md`

- [ ] **Step 1: Write CLAUDE.md**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with project guidance"
```

---

### Task 14: Integration Smoke Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_integration.py`:

```python
"""End-to-end smoke test: render cockpit with fixture data."""

import json
from pathlib import Path
from cockpit.cli import cmd_render


def test_full_render_with_all_data(tmp_path: Path):
    """Render cockpit with all 4 data files present."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    date = "2026-04-03"

    # Macro snapshot
    macro = {
        "rates": {
            "fed_rates": {"mid": 3.625, "upper": 3.75, "lower": 3.50},
            "ecb_rates": {"deposit_facility": 2.00},
        },
        "snb_rate": 0.00,
        "usd_chf_history": [{"date": "2026-04-01", "value": 0.795}, {"date": "2026-04-02", "value": 0.800}],
        "eur_chf_history": [{"date": "2026-04-01", "value": 0.904}],
        "gbp_chf_history": [{"date": "2026-04-01", "value": 1.120}],
        "energy": {
            "brent_history": [{"date": "2026-04-01", "value": 85.0}],
            "eu_gas_history": [{"date": "2026-04-01", "value": 35.0}],
        },
        "alerts": [],
    }
    (data_dir / f"{date}_macro_snapshot.json").write_text(json.dumps(macro))

    # P&L
    pnl = {
        "months": ["2026/04", "2026/05", "2026/06"],
        "by_currency": {
            "CHF": {"shock_0": [100000, 200000, 150000], "shock_50": [80000, 180000, 130000]},
            "EUR": {"shock_0": [50000, 60000, 70000], "shock_50": [40000, 50000, 60000]},
        },
    }
    (data_dir / f"{date}_pnl.json").write_text(json.dumps(pnl))

    # Portfolio
    portfolio = {
        "exposure": {
            "buckets": [
                {"label": "O/N", "inflows": 1200000, "outflows": 800000, "net": 400000, "cumulative": 400000},
                {"label": "D+1", "inflows": 900000, "outflows": 1000000, "net": -100000, "cumulative": 300000},
            ],
            "survival_days": 45,
        },
        "positions": {
            "currencies": {
                "CHF": {"assets": 5e9, "liabilities": 4e9, "net": 1e9},
                "EUR": {"assets": 2e9, "liabilities": 1.8e9, "net": 0.2e9},
            },
        },
        "counterparty": {
            "concentration": {
                "top_10": [{"counterparty": "THCCBFIGE", "nominal": 500e6, "pct_total": 12.5}],
                "hhi": 850,
            },
            "rating": {
                "AAA-AA": {"nominal": 2e9, "pct": 50.0},
                "A": {"nominal": 1e9, "pct": 25.0},
            },
            "hqla": {
                "L1": {"nominal": 1.8e9, "pct": 45.0},
                "L2A": {"nominal": 0.8e9, "pct": 20.0},
            },
        },
    }
    (data_dir / f"{date}_portfolio.json").write_text(json.dumps(portfolio))

    # Scores
    scores = {
        "USD": {"composite": 55, "label": "Watch", "driver": "policy", "families": {}},
        "EUR": {"composite": 40, "label": "Calm", "driver": "inflation", "families": {}},
        "CHF": {"composite": 30, "label": "Calm", "driver": "liquidity", "families": {}},
        "GBP": {"composite": 65, "label": "Watch", "driver": "growth", "families": {}},
    }
    (data_dir / f"{date}_scores.json").write_text(json.dumps(scores))

    # Brief
    brief = {
        "date": date,
        "reviewed": True,
        "html": "<h2>Executive Summary</h2><p>Markets remain stable with modest CHF strength.</p>",
    }
    (data_dir / f"{date}_brief.json").write_text(json.dumps(brief))

    # Render
    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    html_path = output_dir / f"{date}_cockpit.html"
    assert html_path.exists()

    html = html_path.read_text()

    # Verify all tabs rendered (not placeholder)
    assert "cockpit fetch" not in html  # no fetch placeholder
    assert "cockpit compute" not in html  # no compute placeholder
    assert "cockpit analyze" not in html  # no analyze placeholder

    # Verify key content
    assert "Swiss Treasury Cockpit" in html
    assert "2026-04-03" in html
    assert "Watch" in html  # USD score label
    assert "Calm" in html  # EUR score label
    assert "3.625" in html or "3.63" in html  # Fed rate
    assert "Fact-Checked" in html  # Brief reviewed badge
    assert "Executive Summary" in html  # Brief content


def test_partial_render_missing_pnl(tmp_path: Path):
    """Render with only macro data — P&L/portfolio tabs show placeholders."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    date = "2026-04-03"
    macro = {"rates": {"fed_rates": {"mid": 3.625}}, "alerts": []}
    (data_dir / f"{date}_macro_snapshot.json").write_text(json.dumps(macro))

    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    html = (output_dir / f"{date}_cockpit.html").read_text()
    assert "cockpit compute" in html  # P&L placeholder
    assert "cockpit analyze" in html  # Brief placeholder
```

- [ ] **Step 2: Run tests**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/test_integration.py -v`
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add tests/test_integration.py
git commit -m "test: end-to-end integration smoke tests for cockpit rendering"
```

- [ ] **Step 4: Run full test suite**

Run: `cd "/mnt/Projects/Projects/Swiss Treasury Cockpit" && uv run pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Final commit with all tests green**

```bash
cd "/mnt/Projects/Projects/Swiss Treasury Cockpit"
git add -A
git commit -m "feat: Swiss Treasury Cockpit v0.1.0 — unified dashboard pipeline"
```
