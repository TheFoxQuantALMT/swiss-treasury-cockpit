"""Analyst agent — generates market commentary using DeepSeek-R1.

Template-fill approach: Python builds a pre-filled brief with all numbers,
section headers, and data tables. The LLM only writes interpretation bullets
where marked [INTERPRET]. This eliminates number hallucination and ensures
all required sections are present.
"""

from __future__ import annotations

from datetime import date
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

from cockpit.config import ANALYST_MODEL, OLLAMA_HOST

# Path to cockpit config.yaml (project root / config.yaml)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = _PROJECT_ROOT / "config.yaml"

ANALYST_SYSTEM_PROMPT = """\
You are a senior macro-financial analyst. You will receive a pre-filled morning \
brief with all data already inserted. Your ONLY job is to replace each \
[INTERPRET] marker with 1-2 sentences of professional market commentary.

RULES:
1. Write ONLY in English. Never use Chinese, Japanese, or any non-Latin script.
2. Do NOT change any numbers, dates, or data already in the brief.
3. Replace each [INTERPRET] with concise, actionable analysis. Remove the \
[INTERPRET] tag entirely — the output must contain zero [INTERPRET] markers.
4. Use market terminology: "pricing", "dovish/hawkish", "carry", "risk-on/risk-off".
5. One sentence = one idea. No filler, no redundant conclusions.
6. For directional calls, choose exactly one of: bullish / neutral / bearish.
7. Output the completed brief as-is — keep all markdown formatting intact.
8. Do NOT invent policy actions. If a rate is "unchanged", say "unchanged" — \
do not say "tightening" or "easing" unless the data shows an actual change.
9. Distinguish between current policy stance and market pricing of future moves.
"""


def _safe_get(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return default
    return current if current is not None else default


def _build_template(
    data: dict[str, Any],
    deltas: dict[str, Any],
    delta_table: str,
    alerts: list[dict[str, Any]],
) -> str:
    """Build the pre-filled brief template with [INTERPRET] markers.

    All numbers come from Python. The LLM only fills in commentary.
    """
    today = date.today()

    # Extract all values
    fed_rates = data.get("fed_rates", {})
    fed_lower = _safe_get(fed_rates, "lower")
    fed_upper = _safe_get(fed_rates, "upper")
    fed_effective = _safe_get(fed_rates, "effective") or _safe_get(fed_rates, "mid")

    ecb_rates = data.get("ecb_rates", {})
    ecb_deposit = _safe_get(ecb_rates, "deposit_facility")
    ecb_refi = _safe_get(ecb_rates, "main_refinancing")

    snb_rate_data = data.get("snb_rate")
    if isinstance(snb_rate_data, dict):
        snb_rate = snb_rate_data.get("value", 0.00)
    else:
        snb_rate = 0.00

    usd_chf = _safe_get(data, "usd_chf_history")
    usd_chf_latest = usd_chf[-1]["value"] if usd_chf and isinstance(usd_chf, list) else None
    eur_chf_latest = _safe_get(data, "eur_chf_latest", "value")

    indicators = data.get("daily_indicators", {})
    us_2y = _safe_get(indicators, "us_2y", "value")
    us_10y = _safe_get(indicators, "us_10y", "value")
    vix = _safe_get(indicators, "vix", "value")
    be_5y = _safe_get(indicators, "breakeven_5y", "value")
    be_10y = _safe_get(indicators, "breakeven_10y", "value")

    brent_hist = data.get("brent_history", [])
    brent_latest = brent_hist[-1]["value"] if brent_hist else None
    eu_gas_hist = data.get("eu_gas_history", [])
    eu_gas_latest = eu_gas_hist[-1]["value"] if eu_gas_hist else None

    deposits = data.get("sight_deposits", [])
    saron = data.get("saron")

    # Rate differentials (pre-computed, no LLM arithmetic)
    spreads = {}
    if fed_effective is not None and ecb_deposit is not None:
        spreads["fed_ecb"] = fed_effective - ecb_deposit
    if fed_effective is not None:
        spreads["fed_bns"] = fed_effective - snb_rate
    if ecb_deposit is not None:
        spreads["ecb_bns"] = ecb_deposit - snb_rate

    spread_2s10s = None
    if us_2y is not None and us_10y is not None:
        spread_2s10s = us_10y - us_2y

    vix_level = ""
    if vix is not None:
        vix_level = "elevated" if vix > 25 else "moderate" if vix > 18 else "low"

    # Alerts
    alert_text = ""
    if alerts:
        alert_lines = [f"- **[{a['severity'].upper()}]** {a['message']}" for a in alerts]
        alert_text = "\n".join(alert_lines)

    # Stale sources
    stale_text = ""
    if data.get("stale"):
        stale_text = f"> ⚠️ **Stale data**: {', '.join(data['stale'])} used yesterday's data.\n"

    # Sight deposits — full WoW history for intervention assessment
    deposit_text = "Data unavailable."
    deposit_wow_summary = ""
    if deposits and len(deposits) >= 1:
        last_dep = deposits[-1]
        dom = last_dep.get("domestic")
        tot = last_dep.get("total")
        dep_date = last_dep.get("date", "unknown")
        if dom is not None:
            deposit_text = f"Domestic: {dom/1000:.1f}B CHF, Total: {tot/1000:.1f}B CHF (as of {dep_date})."
            if len(deposits) >= 2:
                prev_dep = deposits[-2]
                prev_dom = prev_dep.get("domestic")
                if prev_dom is not None and prev_dom > 0:
                    wow_change = (dom - prev_dom) / 1000
                    deposit_text += f" Week-over-week change: {wow_change:+.1f}B CHF."

            # Build full WoW change history for context
            wow_lines = []
            max_abs_wow = 0.0
            max_wow_date = ""
            # Also compute cumulative change over the window
            first_dom = None
            for i, dep in enumerate(deposits):
                d = dep.get("domestic")
                if d is None:
                    continue
                d_b = d / 1000
                if first_dom is None:
                    first_dom = d_b
                if i > 0:
                    prev_d = deposits[i - 1].get("domestic")
                    if prev_d is not None:
                        wow = (d - prev_d) / 1000
                        wow_lines.append(f"  {dep.get('date', '?')}: {wow:+.1f}B")
                        if abs(wow) > abs(max_abs_wow):
                            max_abs_wow = wow
                            max_wow_date = dep.get("date", "?")

            if wow_lines:
                cumulative = dom / 1000 - first_dom if first_dom else 0
                # Flag large moves explicitly so the LLM cannot ignore them
                large_moves = [
                    line for i, line in enumerate(wow_lines)
                    if i < len(deposits) - 1
                ]
                intervention_flag = ""
                if abs(max_abs_wow) >= 2.0:
                    intervention_flag = (
                        f"\n- **INTERVENTION SIGNAL**: The {max_abs_wow:+.1f}B move on "
                        f"{max_wow_date} exceeds the ±2.0B threshold — "
                        f"probable FX intervention (correlation 0.68 with official data)"
                    )
                deposit_wow_summary = (
                    f"- Recent weekly changes (domestic sight deposits):\n"
                    + "\n".join(wow_lines)
                    + f"\n- Largest single-week move: **{max_abs_wow:+.1f}B CHF** ({max_wow_date})"
                    + intervention_flag
                    + f"\n- Cumulative change over window: **{cumulative:+.1f}B CHF**"
                    + f"\n- Alert threshold: +/-2.0B CHF/week"
                )

    # Scenarios from config
    scenario_table = _build_scenario_table()

    # Energy deltas
    brent_1d = deltas.get("brent", {}).get("1d")
    eu_gas_1d = deltas.get("eu_gas", {}).get("1d")
    brent_change_str = f"{brent_1d['pct']:+.1f}% 1D" if brent_1d else "N/A"
    eu_gas_change_str = f"{eu_gas_1d['pct']:+.1f}% 1D" if eu_gas_1d else "N/A"

    # Build the template
    sections = []

    sections.append(f"## CB Watch — {today.strftime('%A %B %d, %Y')}\n")
    sections.append(stale_text)

    if alert_text:
        sections.append(f"### Alerts\n{alert_text}\n")

    # Executive Summary — LLM writes this
    sections.append("## Executive Summary\n[INTERPRET: Write 3-4 bullet points summarizing the key takeaways from the data below. Focus on what changed and what it means for markets.]\n")

    # Fed
    fed_section = "## Fed\n"
    if fed_lower is not None and fed_upper is not None:
        fed_section += f"- Target range: **{fed_lower:.2f}%–{fed_upper:.2f}%** (unchanged)\n"
    if fed_effective is not None:
        fed_section += f"- Effective rate: **{fed_effective:.2f}%**\n"
    if us_2y is not None:
        fed_section += f"- US 2Y yield: **{us_2y:.2f}%**, 10Y: **{us_10y:.2f}%**"
        if spread_2s10s is not None:
            fed_section += f", 2s10s spread: **{spread_2s10s:+.2f}pp** ({'normal' if spread_2s10s > 0 else 'inverted'})"
        fed_section += "\n"
    if be_5y is not None:
        fed_section += f"- Breakeven inflation: 5Y **{be_5y:.2f}%**, 10Y **{be_10y:.2f}%**\n"
    if vix is not None:
        fed_section += f"- VIX: **{vix:.1f}** ({vix_level})\n"
    if "fed_bns" in spreads:
        fed_section += f"- Fed-BNS carry: **{spreads['fed_bns']:+.2f}pp** (favors USD)\n"
    fed_section += (
        "\n[INTERPRET: What does this mean for Fed policy outlook and USD/CHF? "
        "Base your stance label (hawkish/dovish/neutral) strictly on the data above — "
        "breakevens, VIX level, yield curve shape, and rate differentials. "
        "Do not say 'dovish' if rates are unchanged and breakevens are above 2%. 1-2 sentences.]\n"
    )
    sections.append(fed_section)

    # ECB
    ecb_section = "## ECB\n"
    if ecb_deposit is not None:
        ecb_section += f"- Deposit facility: **{ecb_deposit:.2f}%**\n"
    if ecb_refi is not None:
        ecb_section += f"- Main refinancing: **{ecb_refi:.2f}%**\n"
    if "fed_ecb" in spreads:
        ecb_section += f"- Fed-ECB spread: **{spreads['fed_ecb']:+.2f}pp**\n"
    if "ecb_bns" in spreads:
        ecb_section += f"- ECB-BNS carry: **{spreads['ecb_bns']:+.2f}pp** (favors EUR)\n"
    if eur_chf_latest is not None:
        ecb_section += f"- EUR/CHF: **{eur_chf_latest:.4f}**\n"
    ecb_section += "\n[INTERPRET: ECB policy bias, EUR/CHF outlook. 1-2 sentences.]\n"
    sections.append(ecb_section)

    # BNS
    bns_section = "## BNS\n"
    bns_section += f"- Policy rate: **{snb_rate:.2f}%**\n"
    bns_section += f"- Sight deposits: {deposit_text}\n"
    if deposit_wow_summary:
        bns_section += deposit_wow_summary + "\n"
    if usd_chf_latest is not None:
        bns_section += f"- USD/CHF: **{usd_chf_latest:.4f}**\n"
    bns_section += (
        "\n[INTERPRET: BNS intervention assessment. Consider the FULL WoW history above — "
        "not just the latest week. Flag any large moves (>2B) as probable intervention signals. "
        "Also consider cumulative change. 2-3 sentences.]\n"
    )
    sections.append(bns_section)

    # Geopolitics & Energy
    energy_section = "## Geopolitics & Energy\n"
    if brent_latest is not None:
        energy_section += f"- Brent crude: **${brent_latest:.2f}/bbl** ({brent_change_str})\n"
    if eu_gas_latest is not None:
        energy_section += f"- EU gas (TTF): **€{eu_gas_latest:.2f}/MWh** ({eu_gas_change_str})\n"
    energy_section += "\n[INTERPRET: Geopolitical context (Iran conflict, energy supply), transmission to central bank policy. 2-3 sentences.]\n"
    sections.append(energy_section)

    # Key upcoming dates (inject as context for the LLM)
    key_dates = _build_key_dates(today)
    if key_dates:
        sections.append(f"## Key Dates\n{key_dates}\n")

    # FX Trading Matrix
    fx_section = "## FX Trading Matrix\n"
    fx_section += scenario_table + "\n"
    fx_section += "\n[INTERPRET: Probability-weighted view — which scenario dominates current price action? 1-2 sentences.]\n"
    sections.append(fx_section)

    # Directional Calls
    calls_section = "## Directional Calls\n"
    calls_section += "- USD/CHF: [INTERPRET: bullish/neutral/bearish — one sentence rationale]\n"
    calls_section += "- EUR/CHF: [INTERPRET: bullish/neutral/bearish — one sentence rationale]\n"
    calls_section += "- Brent: [INTERPRET: higher/stable/lower — one sentence rationale]\n"
    sections.append(calls_section)

    # Historical Changes table
    sections.append(f"## Historical Changes\n{delta_table}\n")

    return "\n".join(sections)


def _build_key_dates(today: date) -> str:
    """Build upcoming key dates section from config or hardcoded calendar."""
    try:
        import yaml
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        key_dates = config.get("key_dates", [])
    except Exception:
        key_dates = []

    # Hardcoded critical dates (supplement config)
    hardcoded = [
        ("2026-04-06", "End of Trump pause on Iran infrastructure strikes"),
        ("2026-04-28", "FOMC meeting (day 1)"),
        ("2026-04-29", "FOMC meeting (day 2) — decision"),
        ("2026-04-30", "ECB monetary policy meeting"),
        ("2026-06-18", "BNS quarterly monetary policy assessment"),
    ]

    lines = []
    for date_str, desc in hardcoded:
        try:
            d = date.fromisoformat(date_str)
            if d >= today:
                delta = (d - today).days
                urgency = " **⟵ IMMINENT**" if delta <= 3 else ""
                lines.append(f"- **{date_str}** ({delta}d): {desc}{urgency}")
        except ValueError:
            continue

    return "\n".join(lines) if lines else ""


def _build_scenario_table() -> str:
    """Build the scenario matrix from config.yaml."""
    try:
        import yaml
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f)
        scenarios = config.get("scenarios", {})
    except Exception:
        return "Scenario data unavailable."

    lines = [
        "| Scenario | Prob. | Brent | USD/CHF | EUR/CHF |",
        "|----------|-------|-------|---------|---------|",
    ]
    display_names = {
        "ceasefire_rapid": "Rapid ceasefire",
        "conflict_contained": "Contained conflict",
        "escalation_major": "Major escalation",
    }
    for key, sc in scenarios.items():
        name = display_names.get(key, key.replace("_", " ").title())
        prob = sc.get("probability", 0)
        brent = sc.get("brent_target", "?")
        if isinstance(brent, list):
            brent = f"${brent[0]}–{brent[1]}"
        else:
            brent = f"${brent}"
        usd = sc.get("usd_chf_range", [])
        eur = sc.get("eur_chf_range", [])
        usd_str = f"{usd[0]}–{usd[1]}" if len(usd) == 2 else "?"
        eur_str = f"{eur[0]}–{eur[1]}" if len(eur) == 2 else "?"
        lines.append(f"| {name} | {prob:.0%} | {brent} | {usd_str} | {eur_str} |")

    return "\n".join(lines)


def build_analyst_prompt(
    data: dict[str, Any],
    deltas: dict[str, Any],
    delta_table: str,
    alerts: list[dict[str, Any]],
) -> str:
    """Build the analyst prompt with a pre-filled template.

    The template contains all numbers and section headers. The LLM only
    replaces [INTERPRET] markers with commentary.
    """
    template = _build_template(data, deltas, delta_table, alerts)

    return f"""\
Complete the following pre-filled morning brief by replacing every [INTERPRET] \
marker with your analysis. Keep all existing text, numbers, and formatting. \
Write in English only.

{template}

Replace each [INTERPRET] marker now. Output the completed brief.
"""


def create_analyst_agent(
    model: str = ANALYST_MODEL,
    ollama_host: str = OLLAMA_HOST,
) -> "Agent":
    """Create the analyst agent backed by DeepSeek-R1 via Ollama.

    Args:
        model: Ollama model name.
        ollama_host: Ollama server URL.

    Returns:
        Configured Agent instance.

    Raises:
        ImportError: If agent-framework is not installed. Install with:
            uv sync --extra agents
    """
    if not _AGENT_FRAMEWORK_AVAILABLE:
        raise ImportError(
            "agent-framework is required for the analyst agent. "
            "Install with: uv sync --extra agents"
        )

    client = OllamaChatClient(
        model=model,
        host=ollama_host,
    )

    return client.as_agent(
        name="MacroAnalyst",
        instructions=ANALYST_SYSTEM_PROMPT,
        default_options={"think": False},
    )
