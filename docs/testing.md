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
    test_validation.py              Tier 1: Known-answer regulatory validation
    test_invariants.py              Tier 2: Property invariant tests
    test_reconciliation.py          Tier 3: Cross-system reconciliation

  test_fetchers/
    test_imports.py                 Module import checks

  test_parsers/
    test_reference_table.py         Reference table parser
    test_ideal_format.py            Ideal-format parser validation (all 4 files)

  test_snapshot/
    test_enrichment.py              Deal enrichment

  fixtures/
    generate_mock_inputs.py         Generator for ideal-format mock Excel files
    ideal_input/                    Generated mock files (deals, schedule, wirp, reference_table)
```

## Key Test Areas

### Regulatory Validation (Tier 1: `test_engine/test_validation.py`)

Hand-calculated known-answer tests — the regulatory audit trail proving formulas match standards.

| Test Class | Regulatory Basis | Tests |
|---|---|---|
| `TestFixedDepositCHF` | IFRS 9 §5.4.1 | `PnL = Nom * (OIS-Rate) / 360 * days`, negative spread, 31-day months |
| `TestGBPDayCount` | ISDA 2006 §4.16(b) | GBP Act/365 vs CHF Act/360, ratio = 365/360 |
| `TestBondDayCount` | ISDA 2006 §4.16(e) | BND uses YTM as RateRef, 30/360 divisor |
| `TestMidMonthMaturity` | Engine §7.1 | Alive mask prorates, zero after maturity |
| `TestCoCSimple` | IFRS 9 B5.4.5 | CoC = Gross - Funding, OIS vs CocRate funding sources |
| `TestCoCCompound` | ISDA 2021 §6.9 | `∏(1+r*d_i/MM) - ∏(1+f*d_i/MM)`, ≈ simple for low rates |
| `TestRealizedForecastSplit` | Internal | 10R + 20F = 30T, past→Realized, future→Forecast |
| `TestShockSensitivity` | BCBS 368 | +50bp exact delta, loans opposite sign |
| `TestProductRateRefMapping` | Config | IAM/LD→EqOisRate, BND→YTM, IRS→Clientrate, FXS, HCD |
| `TestAccrualDays` | ISDA 2021 §6.9 | Weekday=1, Friday=3, sum = calendar span |

### Invariant Properties (Tier 2: `test_engine/test_invariants.py`)

Properties that must hold regardless of input data. Uses mock ideal-format files.

| Invariant | Regulatory Basis |
|---|---|
| `Total = Realized + Forecast` for PnL and CoC_Simple | Internal consistency |
| Past months → Realized, future months → Forecast | dateRates boundary |
| `CoC_Simple ≈ CoC_Compound` within 5% for low rates | Sanity check |
| Strategy legs produce valid product names only | IFRS 9 §6.5.16 |
| BND legs exclude L/D directions | Strategy decomposition |
| `Nominal = nominal_days / calendar_days` | Averaging correctness |
| Zero nominal → zero PnL | Dead deal correctness |
| Deposit + positive spread → positive PnL | Sign convention |
| `date_rates=None` → all "Total" (backward compat) | API stability |
| Split-mode totals match no-split-mode totals | Implementation consistency |

### Reconciliation (Tier 3: `test_engine/test_reconciliation.py`)

Cross-validates engine output against independent sources. WASP-dependent tests are auto-skipped.

| Test Class | What it validates |
|---|---|
| `TestMockCurvesFromWirp` (5) | All indices present, date coverage, step-function shape, +50bp shift uniform, rates in [-5%, 15%] |
| `TestWaspCurves` (2, WASP-only) | WASP curves load, same shape as mock curves |
| `TestBook2Mtm` (2, 1 WASP-only) | Mock returns zero MTM, WASP returns MTM column |
| `TestCrossCheckManual` (2) | Independent Python loop matches engine output (single and multi-month) |
| `TestCurrencyOisMapping` (5) | CHF→CHFSON, EUR→EUREST, USD→USSOFR, GBP→GBPOIS, FLOAT_NAME consistent |

### P&L Engine (`test_engine/test_engine.py`)

- `compute_daily_pnl` -- vectorized formula correctness
- `aggregate_to_monthly` -- daily to monthly aggregation, Realized/Forecast split
- `weighted_average` -- nominal-weighted rate computation
- `compute_strategy_pnl` -- IAS hedge decomposition into 4 legs
- Direction S (Sold bond) filtering through strategy path

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

### Ideal-Format Parsers (`test_parsers/test_ideal_format.py`)

Validates all 4 ideal-format input file parsers using generated mock Excel files.

| Test Class | Tests | Validates |
|---|---|---|
| `TestParseDeals` | 17 | Column renaming, types, validation, BOOK1/BOOK2 split, rates decimal, strategy, floating, sold bonds, fixing dates |
| `TestParseMtdAutoDetect` | 1 | Legacy parser auto-detects ideal format |
| `TestParseSchedule` | 7 | Column renaming, month columns, maturity zeroing, nominal signs |
| `TestParseEcheancierAutoDetect` | 1 | Legacy parser auto-detects ideal format |
| `TestParseWirpIdeal` | 7 | Columns, valid indices, dates parsed, rates decimal, sorted |
| `TestParseWirpAutoDetect` | 1 | Legacy parser auto-detects ideal format |
| `TestParseReferenceTable` | 4 | Columns, ratings, HQLA levels |
| `TestCrossFileConsistency` | 2 | Every BOOK1 deal has schedule row, every schedule deal in deals |

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

### Mock Ideal-Format Files (`tests/fixtures/ideal_input/`)

Generated by `tests/fixtures/generate_mock_inputs.py`. Regenerate after schema changes:

```bash
uv run python -m tests.fixtures.generate_mock_inputs
```

| File | Content |
|------|---------|
| `deals.xlsx` | 13 deals: 10 BOOK1 (deposits, loans, bonds, FX swap, floating SARON, strategy IAS, WM perimeter) + 3 BOOK2 IRS |
| `schedule.xlsx` | 10 rows, 60 monthly balance columns (2026/04-2031/03), zeroed after maturity |
| `wirp.xlsx` | 19 rate expectations across 4 indices (CHFSON, EUREST, USSOFR, GBPOIS) |
| `reference_table.xlsx` | 8 counterparties with ratings, HQLA levels, countries |

### Sample Data (`test_engine/conftest.py`)

```python
@pytest.fixture
def sample_dir():
    """Path to sample Excel files (if available)."""
    return Path("path/to/economic-pnl-v2/sample/data")
```

### Skipped Tests

Tests that require external dependencies skip gracefully:
- WASP curve loading and reconciliation: skipped if waspTools unavailable
- WASP `stockSwapMTM` validation: skipped if waspTools unavailable
- LLM agent tests: skipped if Ollama unavailable
- Tests requiring sample Excel files: skipped if path doesn't exist

## Verification Checklist

After code changes, verify:

1. `uv run pytest` -- all tests pass (175+ tests)
2. **Tier 1 (known-answer):** hand-calculated P&L matches engine output to 0.01 tolerance
3. **Tier 2 (invariants):** `Total = Realized + Forecast` holds for all deals and months
4. `CoC_Simple == GrossCarry - FundingCost` exactly (per month)
5. `CoC_Compound` diverges from `CoC_Simple` over longer periods
6. `--funding-source ois` vs `--funding-source coc` produce different FundingCost
7. Existing callers of `aggregate_to_monthly` (without `funding_daily`) unchanged
8. Friday->Monday compounding weights `d_i=3`
9. BND products use 30/360 day count; money market uses Act/360 (Act/365 for GBP)
10. SARON lookback: rate on day T uses fixing from T-2 BD
11. Direction S (Sold bond): excluded from IAM/LD strategy legs, included in BND legs
12. Ideal-format parsers auto-detected by legacy parser functions
13. BOOK1/BOOK2 split from unified deals file produces correct shapes
