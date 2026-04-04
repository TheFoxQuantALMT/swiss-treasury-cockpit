# Testing

## Running Tests

```bash
# All tests
uv run pytest

# Single file
uv run pytest tests/test_cli.py

# Single test by name
uv run pytest -k test_coc_simple_equals_gross_minus_funding

# Verbose output
uv run pytest -v

# With coverage
uv run pytest --cov=cockpit
```

## Test Structure

```
tests/
  test_agents.py                    Agent instantiation, LLM integration
  test_alerts.py                    Threshold alert system
  test_charts.py                    Chart data builders
  test_cli.py                       CLI command parsing and execution
  test_config.py                    Configuration constants
  test_data_manager.py              DataManager initialization
  test_integration.py               End-to-end pipeline integration
  test_renderer.py                  HTML cockpit rendering
  test_scoring.py                   Risk scoring (normalize, compute_scores)

  test_engine/
    conftest.py                     Shared fixtures (sample data paths)
    test_engine.py                  Core P&L functions
    test_matrices.py                Matrix builders
    test_decomposition.py           CoC decomposition tests

  test_fetchers/
    test_imports.py                 Module import checks

  test_parsers/
    test_reference_table.py         Reference table parser

  test_snapshot/
    test_enrichment.py              Deal enrichment
```

## Key Test Areas

### P&L Engine (`test_engine/test_engine.py`)

- `compute_daily_pnl` -- vectorized formula correctness
- `aggregate_to_monthly` -- daily to monthly aggregation
- `weighted_average` -- nominal-weighted rate computation
- `compute_strategy_pnl` -- IAS hedge decomposition into 4 legs

### Matrix Builders (`test_engine/test_matrices.py`)

- `build_date_grid` -- correct date range and length
- `expand_nominal_to_daily` -- month-to-day expansion
- `build_alive_mask` -- mid-month maturity handling
- `build_mm_vector` -- currency/product day count
- `build_rate_matrix` -- fixed rate broadcasting

### CoC Decomposition (`test_engine/test_decomposition.py`)

| Test | Verifies |
|------|----------|
| `test_coc_simple_equals_gross_minus_funding` | `CoC_Simple == GrossCarry - FundingCost` exactly |
| `test_coc_compound_diverges_from_simple` | Compounded differs from simple (geometric vs linear) |
| `test_accrual_days_friday_weekend` | Friday d_i=3 (Fri->Mon = 3 calendar days) |
| `test_accrual_days_empty` | Empty grid returns empty array |
| `test_day_count_bond_vs_money_market` | BND->30/360, IAM/LD->Act/360, GBP->Act/365 |
| `test_build_mm_vector_product_aware` | Product column triggers product-aware day count |
| `test_funding_matrix_ois_mode` | OIS mode returns OIS matrix |
| `test_funding_matrix_coc_mode` | CocRate mode broadcasts per-deal rate |
| `test_wasp_carry_comparison` | WASP vs internal (skipped if WASP unavailable) |
| `test_no_coc_without_funding` | Backward compatibility: no CoC columns without funding_daily |
| `test_gross_carry_manual` | Manual GrossCarry calculation matches engine |

### Scoring (`test_scoring.py`)

- `normalize` -- piecewise linear interpolation
- `compute_scores` -- per-currency composite scoring
- Label assignment: Calm/Watch/Action boundaries

### Alerts (`test_alerts.py`)

- FX breach detection (above/below bands)
- Energy threshold crossing
- Deposit movement alerts
- Daily percentage move alerts

### Integration (`test_integration.py`)

End-to-end smoke tests that verify the full pipeline renders correctly with synthetic data.

## Fixtures

### Sample Data (`test_engine/conftest.py`)

```python
@pytest.fixture
def sample_dir():
    """Path to sample Excel files (if available)."""
    return Path("path/to/economic-pnl-v2/sample/data")

@pytest.fixture
def mtd_path(sample_dir):
    return sample_dir / "20260326_MTD Standard Liquidity PnL Report v1.2.xlsx"
```

### Skipped Tests

Tests that require external dependencies skip gracefully:
- WASP carry comparison: skipped if waspTools unavailable
- LLM agent tests: skipped if Ollama unavailable
- Tests requiring sample Excel files: skipped if path doesn't exist

## Verification Checklist

After code changes, verify:

1. `uv run pytest` -- all tests pass
2. `CoC_Simple == GrossCarry - FundingCost` exactly (per month)
3. `CoC_Compound` diverges from `CoC_Simple` over longer periods
4. `--funding-source ois` vs `--funding-source coc` produce different FundingCost
5. Existing callers of `aggregate_to_monthly` (without `funding_daily`) unchanged
6. Friday->Monday compounding weights `d_i=3`
7. BND products use 30/360 day count; money market uses Act/360 (Act/365 for GBP)
8. SARON lookback: rate on day T uses fixing from T-2 BD
