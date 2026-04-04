"""Reporter agent — formats validated analysis into HTML and Notion content.

Takes the reviewed brief and source data, produces:
1. Plotly HTML dashboard (via Jinja2 template)
2. Notion-formatted markdown for database entry
"""

from __future__ import annotations

import json
import re
import yaml
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from agent_framework import Agent
    from agent_framework_ollama import OllamaChatClient
    _AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    _AGENT_FRAMEWORK_AVAILABLE = False
    Agent = None  # type: ignore[assignment,misc]
    OllamaChatClient = None  # type: ignore[assignment,misc]

from jinja2 import Environment, FileSystemLoader
from loguru import logger

try:
    from cockpit.render.charts import CHART_REGISTRY, render_chart, render_chart_dark
    _CHARTS_AVAILABLE = True
except ImportError:
    _CHARTS_AVAILABLE = False
    CHART_REGISTRY: dict[str, Any] = {}  # type: ignore[assignment]

    def render_chart(fig: Any, fmt: str = "html") -> str:  # type: ignore[misc]
        return "<p>Charts not available — cockpit.render.charts not installed.</p>"

    def render_chart_dark(fig: Any) -> str:  # type: ignore[misc]
        return "<p>Charts not available — cockpit.render.charts not installed.</p>"

from cockpit.config import OLLAMA_HOST

# Resolve templates directory: src/cockpit/../../../templates → project root / templates
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = _PACKAGE_DIR.parent.parent / "templates"

REPORTER_SYSTEM_PROMPT = """\
You are a financial report formatter. Your job is to take a validated market \
analysis and format it into a clean, professional morning brief.

RULES:
1. Preserve all data and analysis from the input — do not modify content.
2. Add clear section headers and formatting.
3. Use markdown tables for comparisons.
4. Highlight alerts and warnings prominently.
5. Add a metadata header with date, data freshness, and stale source warnings.
6. Keep it concise — one sentence per idea.
"""


def _sanitize_brief(text: str) -> str:
    """Clean up LLM output artifacts before rendering.

    Strips unreplaced [INTERPRET:...] markers, non-Latin characters
    (e.g. Chinese from DeepSeek code-switching), and fixes formatting.
    """
    # Remove [INTERPRET: ...] blocks (unreplaced markers)
    text = re.sub(r'\[INTERPRET:?\s*[^\]]*\]', '', text)

    # Remove non-Latin/non-ASCII prose characters (Chinese, Arabic, etc.)
    # Replace with a space to avoid word-merging, then collapse later.
    text = re.sub(r'[\u4e00-\u9fff\u3400-\u4dbf\u0600-\u06ff]+', ' ', text)

    # Fix missing spaces after removal (e.g. "its鹰派立场hawkish" → "itshawkish" → "its hawkish")
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)

    # Collapse multiple spaces/blank lines
    text = re.sub(r'  +', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove empty paragraphs that result from stripping
    text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)

    return text.strip()


def _inline_format(text: str) -> str:
    """Apply inline markdown formatting (bold, italic)."""
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    return text


def _markdown_to_html(text: str) -> str:
    """Convert markdown to HTML (headers, bold, italic, lists, blockquotes, tables)."""
    lines = text.split("\n")
    html_lines = []
    in_list = False
    in_table = False
    table_has_header = False

    def _close_list() -> None:
        nonlocal in_list
        if in_list:
            html_lines.append("</ul>")
            in_list = False

    def _close_table() -> None:
        nonlocal in_table, table_has_header
        if in_table:
            html_lines.append("</tbody></table>")
            in_table = False
            table_has_header = False

    for line in lines:
        stripped = line.strip()

        # Headers (h2–h5)
        header_match = re.match(r'^(#{2,5})\s+(.+)$', stripped)
        if header_match:
            _close_list()
            _close_table()
            level = len(header_match.group(1))
            html_lines.append(f"<h{level}>{_inline_format(header_match.group(2))}</h{level}>")
            continue

        # Table rows (lines with | delimiters)
        if stripped.startswith("|") and stripped.endswith("|"):
            _close_list()
            cells = [c.strip() for c in stripped.strip("|").split("|")]

            # Skip separator rows (|---|---|)
            if all(re.match(r'^[-:]+$', c) for c in cells):
                table_has_header = True
                continue

            if not in_table:
                html_lines.append('<table class="brief-table"><thead>')
                html_lines.append("<tr>" + "".join(f"<th>{_inline_format(c)}</th>" for c in cells) + "</tr>")
                html_lines.append("</thead><tbody>")
                in_table = True
            else:
                html_lines.append("<tr>" + "".join(f"<td>{_inline_format(c)}</td>" for c in cells) + "</tr>")
            continue

        # Non-table line closes any open table
        _close_table()

        # Blockquotes
        if stripped.startswith("> "):
            _close_list()
            html_lines.append(f'<blockquote style="border-left:3px solid #ccc;padding-left:1rem;color:#666">{_inline_format(stripped[2:])}</blockquote>')
            continue

        # List items
        if stripped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline_format(stripped[2:])}</li>")
            continue

        # Close list if needed
        _close_list()

        # Empty lines
        if not stripped:
            continue

        # Regular paragraphs
        html_lines.append(f"<p>{_inline_format(stripped)}</p>")

    _close_list()
    _close_table()

    return "\n".join(html_lines)


def _build_delta_table_html(deltas: dict[str, Any]) -> str:
    """Build a styled HTML delta table with color-coded changes.

    Expects deltas from compute_deltas(): {metric: {current, 1d: {change, pct}, ...}}
    """
    metrics = [
        ("USD/CHF", "usd_chf"),
        ("EUR/CHF", "eur_chf"),
        ("Brent", "brent"),
        ("EU Gas", "eu_gas"),
        ("Fed Rate", "fed_rate"),
        ("ECB Deposit", "ecb_rate"),
        ("US 2Y", "us_2y"),
        ("US 10Y", "us_10y"),
        ("VIX", "vix"),
    ]
    periods = ["1d", "1w", "1m"]

    rows = []
    for label, key in metrics:
        metric_data = deltas.get(key, {})
        if not metric_data:
            continue
        cells = [f"<td><strong>{label}</strong></td>"]
        for period in periods:
            pd = metric_data.get(period)
            if pd is None or not isinstance(pd, dict):
                cells.append('<td class="stale">N/A</td>')
                continue
            pct = pd.get("pct")
            change = pd.get("change")

            if pct is not None:
                css_class = "positive" if pct > 0 else "negative" if pct < 0 else ""
                if abs(pct) > 2:
                    css_class += " significant"
                cells.append(f'<td class="{css_class}">{pct:+.2f}%</td>')
            elif change is not None:
                css_class = "positive" if change > 0 else "negative" if change < 0 else ""
                cells.append(f'<td class="{css_class}">{change:+.4f}</td>')
            else:
                cells.append('<td class="stale">N/A</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return f"""<table class="delta-table">
<thead><tr><th>Metric</th><th>1D</th><th>1W</th><th>1M</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def generate_html_brief(
    brief_text: str,
    data: dict[str, Any],
    deltas: dict[str, Any],
    alerts: list[dict[str, Any]],
    chart_selections: list[str] | None = None,
) -> str:
    """Generate HTML brief with Plotly charts.

    Args:
        brief_text: Validated analysis markdown.
        data: Fetched market data snapshot.
        deltas: Historical comparison deltas.
        alerts: Triggered alerts.
        chart_selections: List of chart_type names to render. If None, renders defaults.

    Returns:
        Complete HTML string.
    """
    template_path = TEMPLATES_DIR / "daily_brief.html"

    if not template_path.exists():
        logger.warning("HTML template not found, generating minimal HTML")
        return _minimal_html(brief_text, data, alerts)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("daily_brief.html")

    # Generate Plotly charts
    if chart_selections is None:
        chart_selections = [
            "fx_history",               # FX with scenario bands
            "rate_differentials",       # Carry spreads (replaces cb_rates)
            "energy",                   # Brent + gas with annotations
            "sight_deposits",           # SNB intervention proxy
            "yield_curve",              # 3-point curve with ghost
            "vix",                      # 30d time series
            "inflation_breakevens",     # 30d with Fed target
            "delta_heatmap",            # Fixed key mapping
        ]

    charts_html = []
    if _CHARTS_AVAILABLE:
        for chart_type in chart_selections:
            chart_fn = CHART_REGISTRY.get(chart_type)
            if chart_fn is None:
                logger.warning(f"Unknown chart type: {chart_type}")
                continue
            try:
                if chart_type == "delta_heatmap":
                    fig = chart_fn(data, deltas=deltas)
                else:
                    fig = chart_fn(data)
                charts_html.append(render_chart(fig, "html"))
            except Exception as e:
                logger.warning(f"Chart '{chart_type}' failed: {e}")
    else:
        logger.warning("cockpit.render.charts not available — skipping chart generation")

    # Sanitize LLM output before rendering
    brief_text = _sanitize_brief(brief_text)

    # Convert brief markdown to HTML
    brief_html = _markdown_to_html(brief_text)

    # Build styled delta table
    delta_table_html = _build_delta_table_html(deltas)

    return template.render(
        date=date.today().isoformat(),
        brief_html=brief_html,
        charts=charts_html,
        delta_table_html=delta_table_html,
        alerts=alerts,
        stale_sources=data.get("stale", []),
    )


def generate_notion_content(
    brief_text: str,
    alerts: list[dict[str, Any]],
    stale_sources: list[str],
) -> dict[str, Any]:
    """Generate Notion page content from the brief.

    Args:
        brief_text: Validated analysis markdown.
        alerts: Triggered alerts.
        stale_sources: List of data sources that used stale data.

    Returns:
        Dict with title, status, and markdown body for Notion.
    """
    today = date.today()
    status = "OK"
    if stale_sources:
        status = "Stale"
    if any(a["severity"] == "critical" for a in alerts):
        status = "Alert"

    alert_section = ""
    if alerts:
        alert_lines = []
        for a in alerts:
            icon = "🔴" if a["severity"] in ("critical", "high") else "🟡"
            alert_lines.append(f"{icon} **{a['metric']}**: {a['message']}")
        alert_section = "\n---\n## Alerts\n" + "\n".join(alert_lines) + "\n"

    stale_section = ""
    if stale_sources:
        stale_section = (
            f"\n> ⚠️ **Stale data**: {', '.join(stale_sources)} "
            f"used yesterday's data due to API failures.\n"
        )

    # Sanitize LLM output for Notion too
    brief_text = _sanitize_brief(brief_text)

    body = f"""\
# CB Watch — {today.strftime('%A %B %d, %Y')}
{stale_section}
{alert_section}
{brief_text}

---
*Generated automatically by Swiss Treasury Cockpit pipeline*
"""

    return {
        "title": f"CB Watch — {today.isoformat()}",
        "status": status,
        "date": today.isoformat(),
        "body": body,
        "alert_count": len(alerts),
    }


def generate_dashboard(
    data: dict[str, Any],
    deltas: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> str:
    """Generate dark-themed treasury dashboard HTML with Plotly charts.

    Args:
        data: Fetched market data snapshot.
        deltas: Historical comparison deltas from compute_deltas().
        alerts: Triggered alerts from check_alerts().

    Returns:
        Complete HTML string for the dashboard.
    """
    today = date.today()

    # ── (a) Load treasury state files ──────────────────────────────
    treasury_dir = Path(__file__).resolve().parent.parent.parent.parent / "data" / "treasury_state"

    def _load_json(name: str) -> dict[str, Any]:
        path = treasury_dir / name
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return {}

    positions = _load_json("positions.json")
    var_data = _load_json("var.json")
    regulatory = _load_json("regulatory.json")

    # ── (b) Load config.yaml ───────────────────────────────────────
    config_path = _PACKAGE_DIR.parent.parent / "config.yaml"
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        config = {}

    # ── (c) Compute risk indicators ───────────────────────────────
    indicators: list[dict[str, Any]] = []

    # Brent vs escalation threshold
    brent_hist = data.get("brent_history", [])
    brent_val = brent_hist[-1]["value"] if brent_hist else None
    brent_threshold = config.get("alerts", {}).get("energy", {}).get("brent_high", 120)
    if brent_val is not None:
        pct = brent_val / brent_threshold * 100
        color = "#ff4444" if pct > 90 else "#ffaa00" if pct > 75 else "#44cc44"
        indicators.append({"color": color, "label": "Brent", "value": f"${brent_val:.1f}"})

    # Nearest catalyst from key_dates
    config_dates = config.get("key_dates", [])
    nearest_days = None
    for kd in config_dates:
        try:
            dt = datetime.strptime(kd["date"], "%Y-%m-%d").date()
            days = (dt - today).days
            if days >= 0 and (nearest_days is None or days < nearest_days):
                nearest_days = days
        except Exception:
            continue
    if nearest_days is not None:
        color = "#ff4444" if nearest_days <= 3 else "#ffaa00" if nearest_days <= 7 else "#44cc44"
        indicators.append({"color": color, "label": "Catalyst", "value": f"{nearest_days}d"})

    # VIX
    vix_ind = data.get("daily_indicators", {}).get("vix", {})
    vix_val = vix_ind.get("value") if isinstance(vix_ind, dict) else None
    if vix_val is not None:
        color = "#ff4444" if vix_val > 25 else "#ffaa00" if vix_val > 18 else "#44cc44"
        indicators.append({"color": color, "label": "VIX", "value": f"{vix_val:.1f}"})

    # EUR/CHF
    eur_chf = data.get("eur_chf_latest", {})
    eur_val = eur_chf.get("value") if isinstance(eur_chf, dict) else None
    if eur_val is not None:
        color = "#ff4444" if eur_val < 0.90 else "#ffaa00" if eur_val < 0.92 else "#44cc44"
        indicators.append({"color": color, "label": "EUR/CHF", "value": f"{eur_val:.4f}"})

    # LCR
    lcr_val = regulatory.get("latest", {}).get("lcr")
    if lcr_val is not None:
        buffer = lcr_val - 110
        color = "#ff4444" if buffer < 5 else "#ffaa00" if buffer < 10 else "#44cc44"
        indicators.append({"color": color, "label": "LCR", "value": f"{lcr_val:.0f}%"})

    # Total VaR utilization
    total_var_util = None
    for desk in var_data.get("desks", []):
        if desk.get("desk") == "Total":
            total_var_util = desk.get("utilization")
            break
    if total_var_util is not None:
        color = "#ff4444" if total_var_util > 85 else "#ffaa00" if total_var_util > 70 else "#44cc44"
        indicators.append({"color": color, "label": "VaR Util", "value": f"{total_var_util:.0f}%"})

    # Overall risk level
    colors_list = [ind["color"] for ind in indicators]
    if "#ff4444" in colors_list:
        risk_level = "ELEVATED"
        risk_color = "#ff4444"
    elif "#ffaa00" in colors_list:
        risk_level = "MODERATE"
        risk_color = "#ffaa00"
    else:
        risk_level = "LOW"
        risk_color = "#44cc44"

    red_count = colors_list.count("#ff4444")
    amber_count = colors_list.count("#ffaa00")
    green_count = colors_list.count("#44cc44")
    risk_counts = f"{red_count}R {amber_count}A {green_count}G"

    # ── (d) Compute metrics strip ─────────────────────────────────
    usd_hist = data.get("usd_chf_history", [])
    usd_val = usd_hist[-1]["value"] if usd_hist else None

    fed_eff = data.get("fed_rates", {}).get("effective")
    snb = data.get("snb_rate", {})
    snb_val = snb.get("value", 0) if isinstance(snb, dict) else 0
    carry = (fed_eff - snb_val) if fed_eff is not None else None

    def _metric_change(key: str) -> tuple[str, str]:
        """Return (change_str, change_color) for a delta key."""
        d = deltas.get(key, {}).get("1d")
        if d is None or not isinstance(d, dict):
            return ("--", "#888888")
        pct = d.get("pct")
        if pct is not None:
            color = "#44cc44" if pct > 0 else "#ff4444" if pct < 0 else "#888888"
            return (f"{pct:+.2f}%", color)
        change = d.get("change")
        if change is not None:
            color = "#44cc44" if change > 0 else "#ff4444" if change < 0 else "#888888"
            return (f"{change:+.4f}", color)
        return ("--", "#888888")

    metrics: list[dict[str, Any]] = []

    usd_change, usd_color = _metric_change("usd_chf")
    metrics.append({
        "label": "USD/CHF",
        "value": f"{usd_val:.4f}" if usd_val is not None else "N/A",
        "change": usd_change,
        "change_color": usd_color,
    })

    eur_change, eur_color = _metric_change("eur_chf")
    metrics.append({
        "label": "EUR/CHF",
        "value": f"{eur_val:.4f}" if eur_val is not None else "N/A",
        "change": eur_change,
        "change_color": eur_color,
    })

    brent_change, brent_color = _metric_change("brent")
    metrics.append({
        "label": "Brent",
        "value": f"${brent_val:.1f}" if brent_val is not None else "N/A",
        "change": brent_change,
        "change_color": brent_color,
    })

    metrics.append({
        "label": "Fed-BNS Carry",
        "value": f"{carry:.2f}%" if carry is not None else "N/A",
        "change": "--",
        "change_color": "#888888",
    })

    # ── (e) Compute upcoming dates ────────────────────────────────
    hardcoded = [
        ("2026-04-06", "Iran strikes"),
        ("2026-04-28", "FOMC"),
        ("2026-04-30", "ECB"),
        ("2026-06-18", "BNS"),
    ]
    all_dates: dict[str, str] = {}
    for d_str, evt in hardcoded:
        all_dates[d_str] = evt
    for kd in config.get("key_dates", []):
        d_str = kd.get("date", "")
        evt = kd.get("event", "")
        if d_str and d_str not in all_dates:
            all_dates[d_str] = evt

    upcoming: list[dict[str, Any]] = []
    for d_str, evt in all_dates.items():
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d").date()
            days = (dt - today).days
            if days < 0:
                continue
            upcoming.append({
                "date": dt.strftime("%b %d"),
                "event": evt,
                "days": days,
                "imminent": days <= 3,
            })
        except Exception:
            continue
    upcoming.sort(key=lambda x: x["days"])

    # ── (f) Render all 8 charts in dark mode ──────────────────────
    chart_order = [
        "fx_history",
        "rate_differentials",
        "energy",
        "yield_curve",
        "sight_deposits",
        "vix",
        "inflation_breakevens",
        "delta_heatmap",
    ]

    charts: list[dict[str, str]] = []
    if _CHARTS_AVAILABLE:
        for chart_type in chart_order:
            chart_fn = CHART_REGISTRY.get(chart_type)
            if chart_fn is None:
                logger.warning(f"Unknown chart type: {chart_type}")
                continue
            try:
                if chart_type == "delta_heatmap":
                    fig = chart_fn(data, deltas=deltas)
                else:
                    fig = chart_fn(data)
                html = render_chart_dark(fig)
                label = chart_type.replace("_", " ").upper()
                charts.append({"label": label, "html": html})
            except Exception as e:
                logger.warning(f"Dashboard chart '{chart_type}' failed: {e}")
    else:
        logger.warning("cockpit.render.charts not available — skipping dashboard charts (Task 10)")

    # ── Compute currency scores ───────────────────────────────
    from cockpit.engine.scoring.scoring import compute_scores

    scores = compute_scores(data)

    label_colors = {"Calm": "#44cc44", "Watch": "#ffaa00", "Action": "#ff4444"}
    currency_scores = {}
    for ccy, cs in scores.items():
        currency_scores[ccy] = {
            "label": cs.label,
            "label_color": label_colors.get(cs.label, "#888888"),
            "composite": cs.composite,
        }

    # ── Build per-currency tab data ───────────────────────────
    fx_configs = {
        "USD": ("usd_chf_history", "USD/CHF", "usd_chf_range"),
        "EUR": ("eur_chf_history", "EUR/CHF", "eur_chf_range"),
        "GBP": ("gbp_chf_history", "GBP/CHF", ""),
    }

    currency_tabs: dict[str, Any] = {}

    if _CHARTS_AVAILABLE:
        from cockpit.render.charts import (
            chart_score_breakdown, chart_fx_single_pair, chart_currency_yield_curve,
            chart_sight_deposits, chart_fx_history,
        )

        # USD, EUR, GBP tabs
        for ccy in ["USD", "EUR", "GBP"]:
            cs = scores[ccy]
            tab: dict[str, Any] = {}

            try:
                fig = chart_score_breakdown(cs)
                tab["score_chart"] = render_chart_dark(fig)
            except Exception as e:
                tab["score_chart"] = f"<p style='color:#888'>Score chart error: {e}</p>"

            try:
                fig = chart_currency_yield_curve(data, ccy)
                tab["yield_chart"] = render_chart_dark(fig)
            except Exception as e:
                tab["yield_chart"] = f"<p style='color:#888'>Yield curve error: {e}</p>"

            pair_key, pair_label, scenario_key = fx_configs[ccy]
            try:
                fig = chart_fx_single_pair(data, pair_key, pair_label, scenario_key)
                tab["fx_chart"] = render_chart_dark(fig)
            except Exception as e:
                tab["fx_chart"] = f"<p style='color:#888'>FX chart error: {e}</p>"

            tab["families"] = {}
            tab["raw_values"] = {}
            for fname, fs in cs.families.items():
                tab["families"][fname] = {"indicators": fs.indicators}

            currency_tabs[ccy] = tab

        # CHF tab (special)
        cs_chf = scores["CHF"]
        chf_tab: dict[str, Any] = {}

        try:
            fig = chart_score_breakdown(cs_chf)
            chf_tab["score_chart"] = render_chart_dark(fig)
        except Exception as e:
            chf_tab["score_chart"] = f"<p style='color:#888'>Score error: {e}</p>"

        try:
            fig = chart_sight_deposits(data)
            chf_tab["deposits_chart"] = render_chart_dark(fig)
        except Exception as e:
            chf_tab["deposits_chart"] = f"<p style='color:#888'>Deposits error: {e}</p>"

        try:
            fig = chart_fx_history(data)
            chf_tab["fx_chart"] = render_chart_dark(fig)
        except Exception as e:
            chf_tab["fx_chart"] = f"<p style='color:#888'>FX error: {e}</p>"

    else:
        # Fallback: minimal tab data without charts
        for ccy in ["USD", "EUR", "GBP"]:
            cs = scores[ccy]
            tab = {
                "score_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
                "yield_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
                "fx_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
                "families": {},
                "raw_values": {},
            }
            for fname, fs in cs.families.items():
                tab["families"][fname] = {"indicators": fs.indicators}
            currency_tabs[ccy] = tab

        cs_chf = scores["CHF"]
        chf_tab = {
            "score_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
            "deposits_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
            "fx_chart": "<p style='color:#888'>Charts not available (Task 10)</p>",
            "families": {},
        }
        for fname, fs in cs_chf.families.items():
            chf_tab["families"][fname] = {"indicators": fs.indicators}

    # Intervention table
    deposits = data.get("sight_deposits", [])
    deposits_table = []
    for i in range(len(deposits) - 1, -1, -1):
        dep = deposits[i]
        dom = dep.get("domestic")
        if dom is None:
            continue
        dom_b = dom / 1000
        wow = 0.0
        if i > 0:
            prev_dom = deposits[i - 1].get("domestic")
            if prev_dom is not None:
                wow = (dom - prev_dom) / 1000
        signal = "Quiet" if abs(wow) < 1 else "Active" if abs(wow) < 2 else "STRONG"
        signal_class = "calm" if signal == "Quiet" else "watch" if signal == "Active" else "action"
        deposits_table.append({
            "date": dep.get("date", ""),
            "domestic_b": f"{dom_b:.1f}",
            "wow": f"{wow:+.1f}",
            "signal": signal,
            "signal_class": signal_class,
        })

    chf_tab["deposits_table"] = deposits_table
    for fname, fs in cs_chf.families.items():
        chf_tab["families"][fname] = {"indicators": fs.indicators}

    currency_tabs["CHF"] = chf_tab

    # ── (g) Render template ───────────────────────────────────────
    template_path = TEMPLATES_DIR / "dashboard.html"
    if not template_path.exists():
        logger.warning("Dashboard template not found, returning minimal HTML")
        return _minimal_html("", data, alerts)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("dashboard.html")

    now = datetime.now()
    var_desks = var_data.get("desks", [])

    return template.render(
        date=today.isoformat(),
        time=now.strftime("%H:%M"),
        risk_level=risk_level,
        risk_color=risk_color,
        risk_counts=risk_counts,
        indicators=indicators,
        metrics=metrics,
        positions=positions,
        regulatory=regulatory,
        var_desks=var_desks,
        upcoming=upcoming,
        charts=charts,
        currency_scores=currency_scores,
        currency_tabs=currency_tabs,
    )


def _minimal_html(
    brief_text: str,
    data: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> str:
    """Generate minimal HTML when template is not available."""
    today = date.today().isoformat()
    alert_html = ""
    if alerts:
        alert_items = "\n".join(
            f'<li class="alert-{a["severity"]}">{a["message"]}</li>'
            for a in alerts
        )
        alert_html = f"<h2>Alerts</h2><ul>{alert_items}</ul>"

    # Convert markdown to basic HTML (headers and bold)
    html_body = brief_text
    for i in range(6, 0, -1):
        prefix = "#" * i
        html_body = html_body.replace(f"\n{prefix} ", f"\n<h{i}>")
        # Close tags approximately
        html_body = html_body.replace(f"<h{i}>", f"</h{max(i-1,1)}><h{i}>", 1)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>CB Watch — {today}</title>
    <style>
        body {{ font-family: 'DM Sans', sans-serif; max-width: 880px; margin: 0 auto; padding: 2rem; }}
        h1 {{ color: #1a1a2e; }}
        .alert-critical, .alert-high {{ color: #d32f2f; font-weight: bold; }}
        .alert-medium {{ color: #f57c00; }}
        pre {{ background: #f5f5f5; padding: 1rem; overflow-x: auto; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    </style>
</head>
<body>
    <h1>Central Bank Watch — {today}</h1>
    {alert_html}
    <pre>{brief_text}</pre>
</body>
</html>
"""


def create_reporter_agent(
    model: str = "qwen3.5:27b",
    ollama_host: str = OLLAMA_HOST,
) -> "Agent":
    """Create the reporter agent backed by Qwen 3.5 via Ollama.

    Raises:
        ImportError: If agent-framework is not installed. Install with:
            uv sync --extra agents
    """
    if not _AGENT_FRAMEWORK_AVAILABLE:
        raise ImportError(
            "agent-framework is required for the reporter agent. "
            "Install with: uv sync --extra agents"
        )

    client = OllamaChatClient(
        model=model,
        host=ollama_host,
    )

    return client.as_agent(
        name="ReportFormatter",
        instructions=REPORTER_SYSTEM_PROMPT,
        default_options={"think": False},
    )
