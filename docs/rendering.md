# Rendering

## Overview

The renderer assembles a self-contained HTML dashboard from JSON intermediates using Jinja2 templates and Plotly charts.

```python
from cockpit.render.renderer import render_cockpit

render_cockpit(
    macro_data=macro_data,
    pnl_data=pnl_data,
    portfolio_data=portfolio_data,
    scores_data=scores_data,
    brief_data=brief_data,
    date="2026-04-04",
    output_path=Path("output/2026-04-04_cockpit.html"),
)
```

Any data argument can be `None` -- the template renders a placeholder for missing tabs.

## Dashboard Tabs

### Tab 1: Macro Overview (`_macro.html`)

- Currency risk scorecards (Calm / Watch / Action per currency)
- Central bank rate summary (Fed, ECB, SNB, BoE)
- Triggered alerts list with severity badges
- Score driver identification

### Tab 2: FX & Energy (`_fx_energy.html`)

- FX spot price history with alert band overlays (EUR/CHF, USD/CHF, GBP/CHF)
- Brent crude price chart
- EU natural gas (TTF) price chart
- Geopolitical scenario overlays (ceasefire, contained, escalation)

### Tab 3: P&L (`_pnl.html`)

- Interest rate P&L by currency (CHF, EUR, USD, GBP)
- Shock scenario comparison (0bp, +50bp, WIRP)
- Monthly P&L time series
- CoC decomposition: GrossCarry, FundingCost, CoC_Simple, CoC_Compound

### Tab 4: Portfolio (`_portfolio.html`)

- Liquidity ladder (exposure by time bucket)
- Position aggregation by currency class
- Position aggregation by credit rating
- HQLA classification
- Top counterparty exposures

### Tab 5: Daily Brief (`_brief.html`)

- LLM-generated market commentary (when available)
- Placeholder when `brief_data` is None

## Chart Builders (`charts.py`)

Four builder functions prepare Plotly chart data:

```python
from cockpit.render.charts import (
    build_macro_charts,
    build_fx_energy_charts,
    build_pnl_charts,
    build_portfolio_charts,
)
```

Each returns a dict of chart configurations consumed by the Jinja2 templates. Charts are rendered inline as Plotly JSON -- no external CDN dependency.

## Templates

```
render/templates/
  cockpit.html       Main container: HTML shell, navbar, tab switching JS
  _macro.html        Macro overview tab partial
  _fx_energy.html    FX & energy tab partial
  _pnl.html          P&L tab partial
  _portfolio.html    Portfolio tab partial
  _brief.html        Daily brief tab partial
```

### Custom Jinja2 Filter

```python
{{ data | tojson_safe }}
```

Safely embeds Python objects as inline JSON, handling datetime serialization via `default=str`.

## Output

The rendered HTML file is self-contained:
- All CSS inline
- All JavaScript inline
- Plotly library bundled (cockpit) or Chart.js CDN (P&L dashboard)
- No external dependencies
- Can be opened directly in any browser
- Can be shared via email or file share

---

## P&L Dashboard (21-Tab ALM Dashboard)

A dedicated P&L dashboard is rendered via `cockpit render-pnl`, separate from the macro cockpit. It targets treasury/ALM teams and ALCO meetings.

```python
from cockpit.pnl_dashboard.renderer import render_pnl_dashboard

render_pnl_dashboard(
    pnl_all=pnl.pnlAll,
    pnl_all_s=pnl.pnlAllS,
    ois_curves=pnl.fwdOIS0,
    wirp_curves=pnl.fwdWIRP,
    irs_stock=pnl.irsStock,
    date_run=date_dt,
    date_rates=date_dt,
    output_path=Path("output/2026-04-05_pnl_dashboard.html"),
    # Optional ALM inputs (all auto-discovered from input dir)
    deals=pnl.pnlData,
    pnl_by_deal=pnl.pnl_by_deal,
    budget=budget,
    hedge_pairs=hedge_pairs,
    prev_pnl_all_s=prev_pnl_all_s,
    forecast_history=forecast_history,
    scenarios_data=scenarios_data,
    alert_thresholds=alert_thresholds,
    eve_results=eve_results,
    eve_scenarios=eve_scenarios,
    eve_krd=eve_krd,
    limits=limits,
    pnl_explain=pnl_explain,
    liquidity_schedule=liquidity_schedule,
    nmd_profiles=nmd_profiles,
)
```

All optional inputs default to `None` -- tabs render placeholders when data is absent.

### Dashboard Tabs (21)

| # | Tab | Key Content |
|---|-----|-------------|
| 1 | **ALCO Risk Summary** | Consolidated metrics table, limit utilization bars, breach log |
| 2 | **Summary** | NII KPIs by currency, DoD bridge, CoC YTD, liquidity snapshot |
| 3 | **CoC Decomposition** | GrossCarry, FundingCost, CoC Simple/Compound monthly |
| 4 | **P&L Series** | Monthly NII time series by currency and shock |
| 5 | **Shock Sensitivity** | NII delta matrix (shock × currency) |
| 6 | **EVE** | Economic Value of Equity, IRRBB outlier test, tenor ladder, convexity/gamma, KRD |
| 7 | **NII-at-Risk** | BCBS scenario heatmap, tornado chart, parametric EaR (95%/99%) |
| 8 | **Repricing Gap** | Time-bucket repricing exposure by currency |
| 9 | **FX Mismatch** | Cross-currency NII exposure |
| 10 | **NMD Audit Trail** | Deal-level NMD profile matching (tier, decay, beta), coverage stats |
| 11 | **Budget vs Actual** | NII vs budget comparison by currency |
| 12 | **P&L Attribution** | Waterfall: time, new deals, matured, rate effect, spread effect |
| 13 | **Forecast Tracking** | Historical NII forecast evolution over time |
| 14 | **Strategy IAS** | IAS hedge decomposition into 4 synthetic legs |
| 15 | **Counterparty** | P&L concentration by counterparty |
| 16 | **Hedge Effectiveness** | IAS 39 dollar-offset / IFRS 9 R², scenario cross-reference |
| 17 | **FTP & Business Unit** | 3-way margin split (client/ALM/total) by perimeter and currency |
| 18 | **Liquidity Forecast** | Daily (90d) + monthly cash flows, survival horizon, top maturities |
| 19 | **BOOK2 MTM** | IRS mark-to-market P&L |
| 20 | **Rate Curves** | OIS forward curves and WIRP overlay |
| 21 | **Alerts** | Threshold-based P&L, liquidity, and FTP alerts |

### Chart Library

Uses [Chart.js 4.x](https://www.chartjs.org/) loaded via CDN. Chart data is built by `pnl_dashboard/charts.py` and embedded as inline JSON via the `tojson_safe` Jinja2 filter.

### Optional ALM Input Files

All auto-discovered via glob patterns from the input directory:

| File Pattern | Parser | Description |
|------|--------|-------------|
| `*budget*` | `parse_budget()` | Monthly NII budget per currency |
| `*scenario*` | `parse_scenarios()` | BCBS 368 tenor-dependent rate shocks |
| `*hedge*` | `parse_hedge_pairs()` | Hedge relationship designations |
| `*nmd*` | `parse_nmd_profiles()` | NMD behavioral decay profiles |
| `*limit*` | `parse_limits()` | Board-approved NII/EVE limits |
| `*alert*threshold*` | `parse_alert_thresholds()` | Per-currency alert threshold overrides |
| `*liquidity*` | `parse_liquidity_schedule()` | Daily/monthly cash flow projections |

FTP is a column (`FTP`) in `deals.xlsx`, not a separate file.
