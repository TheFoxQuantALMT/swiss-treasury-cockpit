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
- Plotly library bundled
- No external dependencies
- Can be opened directly in any browser
- Can be shared via email or file share
