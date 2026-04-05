"""Jinja2 renderer for the dedicated P&L dashboard."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from cockpit.pnl_dashboard.charts import build_pnl_dashboard_data

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _json_filter(value: object) -> str:
    """Jinja2 filter to safely embed Python objects as inline JSON."""
    return json.dumps(value, default=str)


def render_pnl_dashboard(
    *,
    pnl_all: pd.DataFrame,
    pnl_all_s: pd.DataFrame,
    ois_curves: Optional[pd.DataFrame] = None,
    wirp_curves: Optional[pd.DataFrame] = None,
    irs_stock: Optional[pd.DataFrame] = None,
    date_run: datetime,
    date_rates: datetime,
    output_path: Path,
) -> Path:
    """Render the P&L dashboard HTML from engine output.

    Args:
        pnl_all: Wide format DataFrame (ForecastRatePnL.pnlAll).
        pnl_all_s: Stacked long format (ForecastRatePnL.pnlAllS).
        ois_curves: OIS forward curves (fwdOIS0).
        wirp_curves: WIRP-overlaid curves (fwdWIRP).
        irs_stock: IRS stock for BOOK2 detail.
        date_run: Stock/run reference date.
        date_rates: Market date (realized/forecast boundary).
        output_path: Where to write the HTML file.

    Returns:
        The output path.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    env.filters["tojson_safe"] = _json_filter

    # Build chart data
    data = build_pnl_dashboard_data(
        pnl_all=pnl_all,
        pnl_all_s=pnl_all_s,
        ois_curves=ois_curves,
        wirp_curves=wirp_curves,
        irs_stock=irs_stock,
        date_run=date_run,
        date_rates=date_rates,
    )

    context = {
        "date_run": date_run.strftime("%Y-%m-%d"),
        "date_rates": date_rates.strftime("%Y-%m-%d"),
        "summary": data["summary"],
        "coc": data["coc"],
        "pnl_series": data["pnl_series"],
        "sensitivity": data["sensitivity"],
        "strategy": data["strategy"],
        "book2": data["book2"],
        "curves": data["curves"],
        "has_coc": bool(data["coc"].get("months")),
        "has_strategy": data["strategy"].get("has_data", False),
        "has_book2": data["book2"].get("has_data", False),
        "has_curves": data["curves"].get("has_data", False),
    }

    template = env.get_template("pnl_dashboard.html")
    html = template.render(**context)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
