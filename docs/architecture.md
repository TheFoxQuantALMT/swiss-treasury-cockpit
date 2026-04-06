# Architecture

## System Design

The cockpit is a three-layer system -- data, engine, render -- orchestrated by a composable CLI.

```
+-------------------------------------------------------------+
|                         CLI (cli.py)                         |
|         fetch  |  compute  |  analyze  |  render             |
+--------+-------+-----+-----+-----+-----+------+-------------+
         |             |           |             |
         v             v           v             v
     data/          engine/     agents/       render/
     fetchers/      pnl/        analyst.py    renderer.py
     parsers/       scoring/    reviewer.py   charts.py
     manager.py     alerts/     reporter.py   templates/
                    snapshot/
                    models.py
```

## Data Flow

```
Excel Files (MTD, Echeancier, WIRP, IRS)     FRED / ECB / SNB / yfinance
         |                                              |
         v                                              v
    parsers/                                       fetchers/
    (parse_mtd, parse_echeancier,                  (FREDFetcher, ECBFetcher,
     parse_wirp, parse_irs_stock)                   fetch_saron, YFinanceFetcher)
         |                                              |
         v                                              v
    ForecastRatePnL                              DataManager.refresh_all_data()
    build_portfolio_snapshot()                          |
         |                                              v
         v                                    {date}_macro_snapshot.json
    {date}_pnl.json                                     |
    {date}_portfolio.json                               v
         |                                    compute_scores()
         |                                    check_alerts()
         |                                    compute_deltas()
         |                                              |
         v                                              v
    {date}_scores.json  <-------------------------------+
         |
         v
    LLM agents (optional) --> {date}_brief.json
         |
         v
    render_cockpit() --> output/{date}_cockpit.html
```

## Module Structure

### `src/cockpit/`

```
src/cockpit/
  __init__.py
  cli.py                    CLI entry point (cockpit command)
  config.py                 All constants, thresholds, mappings

  data/
    manager.py              Concurrent data fetching orchestrator
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
    renderer.py             Jinja2 HTML assembly for 21-tab P&L dashboard
    charts.py               Chart.js data builders (all tab data)
    templates/
      pnl_dashboard.html    Main container with 21 tabs + navbar
      _alco.html            ALCO Risk Summary (limit breach log)
      _summary.html         Summary (KPIs, DoD bridge, CoC YTD)
      _coc.html             CoC decomposition detail
      _pnl_series.html      P&L time series
      _sensitivity.html     Shock sensitivity matrix
      _eve.html             EVE (IRRBB outlier, tenor ladder, convexity)
      _nii_at_risk.html     NII-at-Risk (tornado, parametric EaR)
      _repricing_gap.html   Repricing gap analysis
      _currency_mismatch.html  FX mismatch
      _nmd_audit.html       NMD behavioral model audit trail
      _budget.html          Budget vs actual
      _attribution.html     P&L attribution / explain waterfall
      _forecast_tracking.html  Forecast tracking
      _strategy.html        Strategy IAS decomposition
      _counterparty.html    Counterparty P&L concentration
      _hedge.html           Hedge effectiveness (scenario cross-ref)
      _ftp.html             FTP & business unit margins
      _liquidity.html       Liquidity forecast
      _book2.html           BOOK2 MTM
      _curves.html          Rate curves
      _pnl_alerts.html      Alerts

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

```
src/pnl_engine/
  __init__.py               PnlEngine orchestrator exports
  orchestrator.py           Stateful engine: load, build matrices, run shocks
  engine.py                 Core: compute_daily_pnl, aggregate_to_monthly
  matrices.py               Numpy array builders (nominal, alive, rate, funding)
  curves.py                 OIS curve loading, WIRP mock fallback
  scenarios.py              BCBS 368 scenario interpolation
  eve.py                    EVE computation (PV, ΔEVE, KRD)
  nmd.py                    NMD behavioral model (decay, beta, maturity)
```

## Design Principles

1. **Pipeline independence** -- Each CLI stage reads JSON intermediates from `data/` and writes its own. Stages can be re-run independently.

2. **Graceful degradation** -- If WASP is unavailable, the engine builds mock curves from WIRP data. If a fetcher fails, the DataManager falls back to the most recent archive.

3. **Canonical data model** -- The project defines the ideal data model (`engine/models.py`). Input parsers adapt external data to fit this model -- never the reverse.

4. **Vectorized computation** -- The P&L engine operates on `(n_deals x n_days)` numpy arrays for all 60 months simultaneously. No per-deal loops.

5. **Configuration-driven** -- All thresholds, mappings, and constants live in `config.py`. No magic numbers in computation code.
