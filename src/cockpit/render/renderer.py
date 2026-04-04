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
