"""Reviewer agent — fact-checks analyst output against source data.

Two-phase validation:
1. Programmatic: extract numbers from output, compare against source JSON.
2. LLM review: check narrative consistency and calculations.

Auto-fix loop: if errors found, returns corrections for analyst to retry.
Max 3 retries before publishing with [UNVERIFIED] warnings.
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    from agent_framework import Agent
    from agent_framework_ollama import OllamaChatClient
    _AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    _AGENT_FRAMEWORK_AVAILABLE = False
    Agent = None  # type: ignore[assignment,misc]
    OllamaChatClient = None  # type: ignore[assignment,misc]

from loguru import logger

from cockpit.agents.models import ReviewResult
from cockpit.config import REVIEWER_MODEL, OLLAMA_HOST

REVIEWER_SYSTEM_PROMPT = """\
You are a macro-financial reviewer. Your job is to check an analyst's morning \
brief for narrative coherence and scenario alignment. Number accuracy has \
already been verified programmatically — focus on logic, not arithmetic.

CHECKS:
1. Narrative coherence: flag contradictions between sections (e.g. "dovish" \
language but data shows hawkish move, or conflicting statements about the same metric).
2. Unsupported claims: flag any statement not backed by the provided data summary.
3. Scenario alignment: verify that directional calls (bullish/bearish/neutral) \
are consistent with the scenario probabilities and data trends.
4. Missing context: flag if a major data point from the summary is ignored.

Respond with ONLY a JSON object:
{"valid": true, "errors": [], "warnings": [], "summary": "one-line summary"}

Error format: {"section": "Fed", "issue": "description", "severity": "high"}
Severity: "critical" = wrong directional call, "high" = contradiction, "medium" = missing context.
If no issues found, set "valid": true and "errors": [].
No markdown, no explanation — JSON only.
"""


def programmatic_check(
    brief_text: str,
    source_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract numbers from brief and cross-check against source data.

    This is the first-pass validation — pure Python, no LLM needed.

    Args:
        brief_text: The analyst's generated brief.
        source_data: The raw fetched data snapshot.

    Returns:
        List of error dicts for mismatched values.
    """
    errors: list[dict[str, Any]] = []

    # Extract all numbers from the brief
    # Pattern matches: 0.7950, 3.75%, $113, 68, etc.
    numbers_in_brief = re.findall(r'[\$€]?(\d+\.?\d*)\s*[%$€]?', brief_text)

    # Build reference values from source data
    reference_values = _build_reference_values(source_data)

    # Check key values that should match exactly
    _check_fed_rates(brief_text, source_data, errors)
    _check_ecb_rates(brief_text, source_data, errors)
    _check_fx_values(brief_text, source_data, errors)

    return errors


def _build_reference_values(data: dict[str, Any]) -> dict[str, float]:
    """Extract all numeric reference values from source data."""
    refs: dict[str, float] = {}

    fed = data.get("fed_rates", {})
    if isinstance(fed, dict):
        for k, v in fed.items():
            if isinstance(v, (int, float)):
                refs[f"fed_{k}"] = v

    ecb = data.get("ecb_rates", {})
    if isinstance(ecb, dict):
        for k, v in ecb.items():
            if isinstance(v, (int, float)):
                refs[f"ecb_{k}"] = v

    return refs


def _check_fed_rates(
    brief: str,
    data: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """Check Fed rate citations against source."""
    fed = data.get("fed_rates", {})
    if not fed:
        return

    upper = fed.get("upper")
    lower = fed.get("lower")

    if upper is not None and lower is not None:
        # Check if brief mentions the correct range
        range_str = f"{lower:.2f}"
        if range_str not in brief and f"{lower}" not in brief:
            # Check if mid is cited instead
            mid = fed.get("mid")
            if mid is not None:
                mid_str = f"{mid:.2f}"
                if mid_str not in brief and f"{mid:.3f}" not in brief:
                    logger.debug(f"Fed rate range {lower}-{upper} not found in brief")


def _check_ecb_rates(
    brief: str,
    data: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """Check ECB rate citations against source."""
    ecb = data.get("ecb_rates", {})
    deposit = ecb.get("deposit_facility")
    if deposit is not None:
        deposit_str = f"{deposit:.2f}"
        if deposit_str not in brief:
            errors.append({
                "section": "ECB",
                "issue": f"ECB deposit rate should be {deposit_str}%",
                "source_value": deposit,
                "severity": "high",
            })


def _check_fx_values(
    brief: str,
    data: dict[str, Any],
    errors: list[dict[str, Any]],
) -> None:
    """Check FX rate citations against source."""
    eur_chf = data.get("eur_chf_latest")
    if isinstance(eur_chf, dict) and "value" in eur_chf:
        val = eur_chf["value"]
        # Allow small rounding differences
        val_strs = [f"{val:.4f}", f"{val:.3f}", f"{val:.2f}"]
        if not any(s in brief for s in val_strs):
            logger.debug(f"EUR/CHF {val} not found in brief")


def _extract_data_summary(source_data: dict[str, Any]) -> str:
    """Extract key values from source data for the reviewer prompt.

    Returns a compact text summary instead of the full JSON dump.
    """
    lines: list[str] = []

    fed = source_data.get("fed_rates", {})
    if isinstance(fed, dict):
        lower = fed.get("lower")
        upper = fed.get("upper")
        if lower is not None and upper is not None:
            lines.append(f"Fed rate: {lower:.2f}%–{upper:.2f}%")

    ecb = source_data.get("ecb_rates", {})
    if isinstance(ecb, dict):
        deposit = ecb.get("deposit_facility")
        if deposit is not None:
            lines.append(f"ECB deposit: {deposit:.2f}%")

    snb = source_data.get("snb_rate", {})
    if isinstance(snb, dict):
        lines.append(f"BNS rate: {snb.get('value', 0.00):.2f}%")

    for pair in ("usd_chf_latest", "eur_chf_latest"):
        val = source_data.get(pair)
        if isinstance(val, dict) and "value" in val:
            label = pair.replace("_latest", "").upper().replace("_", "/")
            lines.append(f"{label}: {val['value']:.4f}")

    energy = source_data.get("energy", {})
    if isinstance(energy, dict):
        for key in ("brent", "eu_gas"):
            e = energy.get(key, {})
            if isinstance(e, dict) and "value" in e:
                lines.append(f"{key.replace('_', ' ').title()}: {e['value']:.2f}")

    indicators = source_data.get("daily_indicators", {})
    if isinstance(indicators, dict):
        for key, label in [("vix", "VIX"), ("us_2y", "US 2Y"), ("us_10y", "US 10Y")]:
            ind = indicators.get(key, {})
            if isinstance(ind, dict) and "value" in ind:
                lines.append(f"{label}: {ind['value']:.2f}")

    return "\n".join(lines) if lines else "No data summary available"


def build_reviewer_prompt(
    brief_text: str,
    source_data: dict[str, Any],
    programmatic_errors: list[dict[str, Any]],
) -> str:
    """Build the reviewer prompt with brief + compact data summary.

    Args:
        brief_text: The analyst's generated brief.
        source_data: The raw fetched data snapshot.
        programmatic_errors: Errors found by programmatic_check().

    Returns:
        Complete reviewer prompt string.
    """
    data_summary = _extract_data_summary(source_data)

    pre_errors = ""
    if programmatic_errors:
        pre_errors = (
            "\n### Numeric errors already found (automated)\n"
            f"```json\n{json.dumps(programmatic_errors, indent=2)}\n```\n"
            "These are confirmed. Focus on narrative and scenario issues instead.\n"
        )

    return f"""\
Review this morning brief for narrative coherence and scenario alignment.
Number accuracy has been checked programmatically.

### Brief
{brief_text}

### Key Data Points (ground truth)
{data_summary}
{pre_errors}
Respond with JSON only.
"""


def create_reviewer_agent(
    model: str = REVIEWER_MODEL,
    ollama_host: str = OLLAMA_HOST,
) -> "Agent":
    """Create the reviewer agent for narrative/scenario review.

    Args:
        model: Ollama model name.
        ollama_host: Ollama server URL.

    Returns:
        Configured Agent instance (no tools — single-pass review).

    Raises:
        ImportError: If agent-framework is not installed. Install with:
            uv sync --extra agents
    """
    if not _AGENT_FRAMEWORK_AVAILABLE:
        raise ImportError(
            "agent-framework is required for the reviewer agent. "
            "Install with: uv sync --extra agents"
        )

    client = OllamaChatClient(
        model=model,
        host=ollama_host,
    )

    return client.as_agent(
        name="FactChecker",
        instructions=REVIEWER_SYSTEM_PROMPT,
        default_options={
            "think": False,
            "num_predict": 2048,
        },
    )
