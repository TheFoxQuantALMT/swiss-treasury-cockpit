# Architecture

## System Design

The cockpit is a three-layer system -- data, engine, render -- orchestrated by a composable CLI.

```
+---------------------------------------------------------------------+
|                           CLI (cli.py)                               |
| fetch | compute | analyze | render | render-pnl | backfill          |
| validate | what-if | decision | export-notion                       |
+---+-------+-----+-----+-----+-----+------+-----+------+-----+-----+
    |             |           |             |             |
    v             v           v             v             v
data/          engine/     agents/       render/       pnl_dashboard/
fetchers/      pnl/        analyst.py    renderer.py   renderer.py
parsers/       scoring/    reviewer.py   charts.py     charts/
manager.py     alerts/     reporter.py   templates/    templates/
quality.py     snapshot/
               models.py
    |                                                    |
    v                                                    v
export/        integrations/    calendar.py     config_loader.py
excel_export   notion_export    decisions.py
pdf_export     peer_benchmark
```

## Data Flow

```
Excel Files (MTD, Echeancier, WIRP, IRS,     FRED / ECB / SNB / yfinance
 budget, scenarios, hedge_pairs, nmd_profiles,
 limits, alert_thresholds, liquidity_schedule,
 custom_scenarios)
         |                                              |
         v                                              v
    parsers/                                       fetchers/
    (parse_mtd, parse_echeancier,                  (FREDFetcher, ECBFetcher,
     parse_wirp, parse_irs_stock,                   fetch_saron, YFinanceFetcher)
     parse_budget, parse_scenarios,                     |
     parse_hedge_pairs, parse_nmd_profiles,             |
     parse_limits, parse_alert_thresholds,              |
     parse_liquidity_schedule,                          |
     parse_custom_scenarios)                            |
         |                                              |
         v                                              v
    quality.py (data quality checks)           DataManager.refresh_all_data()
         |                                              |
         v                                              v
    PnlEngine (orchestrator.py)                {date}_macro_snapshot.json
    + pnl_engine modules:                               |
      eve, nmd, basis_risk,                             v
      prepayment, replication,                compute_scores()
      saron, snb_reserves,                    check_alerts()
      hedge_optimizer, locked_in_nii,         compute_deltas()
      sensitivity_explain, what_if,                     |
      nmd_backtest, reverse_stress                      |
         |                                              |
         v                                              v
    {date}_pnl.json                           {date}_scores.json
    {date}_portfolio.json                               |
         |                                              |
         +----------------------------------------------+
         |
         v
    LLM agents (optional) --> {date}_brief.json
         |
         +---> render_cockpit()     --> output/{date}_cockpit.html
         +---> render_pnl()         --> output/{date}_pnl_dashboard.html
         +---> excel_export()       --> output/{date}_pnl_dashboard.xlsx
         +---> pdf_export()         --> output/{date}_pnl_dashboard.pdf
         +---> notion_export()      --> Notion ALCO Decision Pack
```

## Module Structure

### `src/cockpit/`

```
src/cockpit/
  __init__.py
  cli.py                    CLI entry point (10 commands: fetch, compute, analyze,
                             render, render-pnl, backfill, validate, what-if,
                             decision, export-notion)
  config.py                 All constants, thresholds, mappings
  config_loader.py          YAML-based runtime config with caching (load_config(),
                             reset_cache()), reads config/cockpit.config.yaml
  calendar.py               Swiss business day calendar (10 holidays, Easter algorithm)
  decisions.py              ALCO decision audit trail (JSONL append-only store)

  data/
    manager.py              Concurrent data fetching orchestrator
    quality.py              Data quality checks (match rates, orphan deals,
                             field coverage, rate staleness)
    fetchers/
      __init__.py            Exports: CircuitBreaker, FREDFetcher, ECBFetcher, etc.
      circuit_breaker.py     Resilient API call wrapper
      fred_fetcher.py        FRED API (Fed funds, CPI, GDP, unemployment)
      ecb_fetcher.py         ECB SDMX (policy rate, EUR/CHF)
      snb_fetcher.py         SNB SDMX (sight deposits, policy rate, SARON)
      yfinance_fetcher.py    Yahoo Finance (FX, Brent, EU gas, VIX)
    parsers/
      __init__.py            Exports: parse_mtd, parse_echeancier, etc.
      mtd.py                 MTD Standard Liquidity PnL Report (BOOK1 deals)
      echeancier.py          Echeancier (nominal schedule by month)
      wirp.py                WIRP rate expectations
      irs_stock.py           IRS stock (derivatives portfolio)
      reference_table.py     Reference table (counterparty, rating, HQLA, country)
      budget.py              Monthly NII budget per currency
      scenarios.py           BCBS 368 tenor-dependent rate shock definitions
      custom_scenarios.py    User-defined stress tests (tenor x scenario grid)
      hedge_pairs.py         Hedge relationship designations
      nmd_profiles.py        NMD behavioral decay profiles
      limits.py              Board-approved NII/EVE limits
      alert_thresholds.py    Per-currency alert threshold overrides
      liquidity_schedule.py  Daily (90d) + monthly cash flow projections

  engine/
    models.py               Canonical data models: Deal, RFRIndex, MarketData
    comparison.py            Day-over-day delta computation (1d/1w/1m)
    pnl/
      __init__.py            Exports: ForecastRatePnL, save_pnl, load_pnl, compare_pnl
      forecast.py            ForecastRatePnL -- stateful wrapper, run(), update_pnl()
      engine.py              Core: compute_daily_pnl, aggregate_to_monthly, strategy pivot
      matrices.py            Numpy builders: date grid, nominals, alive mask, rates, funding
      curves.py              OIS curve loading, WIRP overlay, WASP carry comparison
      pnl_explain.py         P&L waterfall decomposition (ΔNII drivers)
      forecast_tracking.py   Historical NII forecast snapshots
      report.py              Excel export
    scoring/
      scoring.py             Deterministic 0-100 scoring (4 families x 4 currencies)
    alerts/
      alerts.py              Threshold alerts (FX, energy, deposits, rate changes)
    snapshot/
      __init__.py            Exports: build_portfolio_snapshot, write_snapshot
      snapshot.py            Orchestrator: enrich -> ladder -> positions -> counterparty
      enrichment.py          Join reference data onto deals
      exposure.py            Liquidity ladder by time bucket
      aggregation.py         Position aggregation by currency/rating/HQLA
      counterparty.py        Counterparty concentration analysis

  agents/
    analyst.py              LLM analyst (DeepSeek-R1, template-fill approach)
    reviewer.py             Fact-checker + LLM reviewer (Qwen3.5)
    reporter.py             Converts brief text to styled HTML
    models.py               Agent request/response models
    tools.py                Verification tools for reviewer

  pnl_dashboard/
    renderer.py             Jinja2 HTML assembly for 36-tab P&L dashboard
    charts/                 Chart.js data builders (split into 8 submodules)
      __init__.py            Package exports
      constants.py           Shared color palettes, formatting constants
      helpers.py             Common chart-building utilities
      orchestrator.py        Main entry point + enrichment wiring
      core.py                Summary, CoC, P&L Series, Sensitivity, Strategy,
                              Book2, Curves
      risk.py                FX Mismatch, Repricing Gap, Counterparty, Alerts,
                              EVE, Limits
      attribution.py         FTP, Liquidity, NMD Audit, ALCO, Budget,
                              Attribution, Forecast Tracking
      profitability.py       Hedge Effectiveness, NII-at-Risk, Deal Explorer,
                              Fixed/Float, NIM
      structure.py           Maturity Wall, Trends, Regulatory
      scenarios.py           Risk Cube, Deposit Behavior, Scenario Studio,
                              Hedge Strategy
      monitoring.py          ALCO Decision Pack, Data Quality, Basis Risk,
                              SNB Reserves, Peer Benchmark, NMD Backtest
    templates/
      pnl_dashboard.html    Main container with 36 tabs + navbar
      _macros.html           Shared Jinja2 macros (kpi_card, chart_container,
                              data_table, metric_badge, empty_state)
      _alco.html             ALCO Risk Summary (decision pack, exec summary)
      _summary.html          Summary (KPIs, DoD bridge, CoC YTD, Locked-in NII)
      _coc.html              CoC decomposition detail
      _pnl_series.html       P&L time series
      _sensitivity.html      Shock sensitivity matrix (with sensitivity explain)
      _eve.html              EVE (IRRBB outlier, tenor ladder, convexity/gamma)
      _nii_at_risk.html      NII-at-Risk (tornado, parametric EaR)
      _repricing_gap.html    Repricing gap analysis
      _currency_mismatch.html  FX mismatch
      _nmd_audit.html        NMD behavioral model audit trail (with replication)
      _deposit_behavior.html Deposit behavior intelligence (beta validation)
      _risk_cube.html        Risk cube (heatmaps)
      _budget.html           Budget vs actual
      _attribution.html      P&L attribution / explain waterfall
      _forecast_tracking.html  Forecast tracking
      _strategy.html         Strategy IAS decomposition
      _counterparty.html     Counterparty P&L concentration
      _hedge.html            Hedge effectiveness (scenario cross-ref)
      _hedge_strategy.html   Hedge Strategy Optimizer (DV01-based recommendations)
      _nim.html              NIM & Profitability (Jaws)
      _fixed_float.html      Fixed/Float mix
      _deal_explorer.html    Deal explorer
      _maturity_wall.html    Maturity wall
      _scenario_studio.html  Scenario Studio (NII+ΔEVE ranking, reverse stress)
      _ftp.html              FTP & business unit margins
      _liquidity.html        Liquidity forecast
      _basis_risk.html       Basis risk (spread compression sensitivity)
      _snb_reserves.html     SNB reserves (2.5% compliance)
      _peer_benchmark.html   Peer benchmark (FINMA aggregates)
      _nmd_backtest.html     NMD backtest (modeled vs actual runoff)
      _book2.html            BOOK2 MTM
      _curves.html           Rate curves
      _trends.html           Historical trends
      _regulatory.html       Regulatory scorecard
      _data_quality.html     Data quality
      _pnl_alerts.html       Alerts

  export/
    __init__.py
    excel_export.py         Multi-sheet Excel workbook (openpyxl)
    pdf_export.py           PDF via weasyprint/pdfkit

  integrations/
    __init__.py
    notion_export.py        Push ALCO Decision Pack to Notion via MCP
    peer_benchmark.py       FINMA aggregate IRRBB statistics comparison

  render/
    renderer.py             Jinja2 HTML assembly for 5-tab macro cockpit
    charts.py               Plotly chart data builders
    templates/
      cockpit.html          Main container with 5 tabs + navbar
      _macro.html           Macro overview (scorecards, CB rates, alerts)
      _fx_energy.html       FX & energy charts with alert bands
      _pnl.html             P&L by currency and shock scenario
      _portfolio.html       Liquidity ladder, positions, counterparty
      _brief.html           LLM daily brief
```

### `src/pnl_engine/`

```
src/pnl_engine/
  __init__.py               PnlEngine orchestrator exports
  config.py                 Engine configuration constants
  orchestrator.py           Stateful engine: load, build matrices, run shocks
  engine.py                 Core: compute_daily_pnl, aggregate_to_monthly
  matrices.py               Numpy array builders (nominal, alive, rate, funding)
  curves.py                 OIS curve loading, WIRP mock fallback
  models.py                 Engine data models
  report.py                 Report generation
  repricing.py              Repricing gap analysis
  scenarios.py              BCBS 368 scenario interpolation
  eve.py                    EVE computation (PV, ΔEVE, KRD, convexity/gamma)
  nmd.py                    NMD behavioral model (decay, beta, maturity)
  basis_risk.py             NII sensitivity to spread compression per product/currency
  prepayment.py             CPR model for fixed-rate mortgages (monthly survival factor)
  reverse_stress.py         Bisection search for breach shock level (NII/ΔEVE)
  replication.py            Least-squares bullet bond replication of NMD cashflows
  saron.py                  ISDA 2021 SARON compounding with lookback shift
  snb_reserves.py           SNB minimum reserve (2.5% sight liabilities, HQLA)
  hedge_optimizer.py        DV01-based IRS notional recommendation per currency
  locked_in_nii.py          Fixed-rate NII certainty metric
  sensitivity_explain.py    Sensitivity change waterfall decomposition
  what_if.py                Incremental deal impact simulator
  nmd_backtest.py           Modeled vs actual runoff comparison (R²/RMSE/MAE)
```

## Design Principles

1. **Pipeline independence** -- Each CLI stage reads JSON intermediates from `data/` and writes its own. Stages can be re-run independently. The `backfill` command automates multi-date reruns.

2. **Graceful degradation** -- If WASP is unavailable, the engine builds mock curves from WIRP data. If a fetcher fails, the DataManager falls back to the most recent archive. Optional input files (budget, scenarios, hedge_pairs, etc.) are auto-discovered and silently skipped when absent.

3. **Canonical data model** -- The project defines the ideal data model (`engine/models.py`). Input parsers adapt external data to fit this model -- never the reverse.

4. **Vectorized computation** -- The P&L engine operates on `(n_deals x n_days)` numpy arrays for all 60 months simultaneously. No per-deal loops.

5. **Configuration-driven** -- Runtime config loaded from `config/cockpit.config.yaml` via `config_loader.py` with deep-merge over defaults. All thresholds, mappings, and constants in `config.py`. No magic numbers in computation code.

6. **Multi-format output** -- The P&L dashboard renders to HTML (Jinja2 + Chart.js), Excel (openpyxl multi-sheet), and PDF (weasyprint/pdfkit). The `--format all` flag generates all three.

7. **Modular analytics** -- The `pnl_engine` package separates each analytical concern (EVE, NMD, basis risk, prepayment, replication, etc.) into standalone modules wired together by the orchestrator. Each module can be tested and used independently.

8. **Audit trail** -- ALCO decisions tracked in an append-only JSONL store (`decisions.py`). NMD model parameters logged in the audit trail. Data quality checks validate input completeness before computation.

9. **External integration** -- Notion export pushes ALCO Decision Packs externally. Peer benchmark compares against FINMA aggregates. These are optional and isolated in `integrations/`.
