"""Verification tools for the reviewer agent.

Tools close over source data via factory function, allowing the reviewer
LLM to programmatically verify numbers cited in the analyst's brief.
"""

from __future__ import annotations

from typing import Annotated, Any

try:
    from agent_framework import tool
    _AGENT_FRAMEWORK_AVAILABLE = True
except ImportError:
    _AGENT_FRAMEWORK_AVAILABLE = False
    tool = None  # type: ignore[assignment]


def _resolve_path(data: dict[str, Any], path: str) -> Any:
    """Traverse a dot-separated path into a nested dict.

    Args:
        data: The nested dictionary to traverse.
        path: Dot-separated key path (e.g. "fed_rates.upper").

    Returns:
        The value at the path, or None if not found.
    """
    current = data
    for key in path.split("."):
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return current


# Metric aliases for common lookups
METRIC_ALIASES: dict[str, str] = {
    "fed_rate": "fed_rates.mid",
    "fed_upper": "fed_rates.upper",
    "fed_lower": "fed_rates.lower",
    "ecb_deposit": "ecb_rates.deposit_facility",
    "ecb_refi": "ecb_rates.main_refinancing",
    "saron": "saron.rate",
    "eur_chf": "eur_chf_latest.value",
    "usd_chf": "usd_chf_latest.value",
    "brent": "energy.brent.value",
    "eu_gas": "energy.eu_gas.value",
    "vix": "indicators.VIXCLS.value",
    "us_2y": "indicators.DGS2.value",
    "us_10y": "indicators.DGS10.value",
    "breakeven_5y": "indicators.T5YIE.value",
    "breakeven_10y": "indicators.T10YIE.value",
    "sight_deposits_domestic": "sight_deposits.domestic.value",
    "sight_deposits_total": "sight_deposits.total.value",
    "snb_rate": "snb_rate.value",
}


def create_reviewer_tools(
    source_data: dict[str, Any],
    deltas: dict[str, Any],
) -> list:
    """Create verification tools that close over the source data.

    Args:
        source_data: The fetched market data snapshot.
        deltas: Historical comparison deltas (1d, 1w, 1m).

    Returns:
        List of FunctionTool instances for the reviewer agent.

    Raises:
        ImportError: If agent-framework is not installed. Install with:
            uv sync --extra agents
    """
    if not _AGENT_FRAMEWORK_AVAILABLE:
        raise ImportError(
            "agent-framework is required for reviewer tools. "
            "Install with: uv sync --extra agents"
        )

    @tool(max_invocation_exceptions=2)
    def verify_number(
        metric: Annotated[str, "Metric key (e.g. 'fed_rate', 'eur_chf', 'brent') or dot-path (e.g. 'fed_rates.upper')"],
        cited_value: Annotated[float, "The numeric value cited in the analyst's brief"],
        tolerance: Annotated[float, "Acceptable absolute deviation (default 0.01)"] = 0.01,
    ) -> str:
        """Verify a number from the brief against source data. Returns MATCH or MISMATCH with details."""
        path = METRIC_ALIASES.get(metric, metric)
        actual = _resolve_path(source_data, path)
        if actual is None:
            return f"NOT_FOUND: metric '{metric}' (path: {path}) not found in source data"
        try:
            actual_f = float(actual)
        except (TypeError, ValueError):
            return f"NOT_NUMERIC: metric '{metric}' has value '{actual}' which is not numeric"
        diff = abs(actual_f - cited_value)
        if diff <= tolerance:
            return f"MATCH: {metric} = {actual_f} (cited {cited_value}, diff {diff:.4f} within tolerance {tolerance})"
        return f"MISMATCH: {metric} = {actual_f} but brief cites {cited_value} (diff {diff:.4f} exceeds tolerance {tolerance})"

    @tool(max_invocation_exceptions=2)
    def compute_spread(
        rate1_metric: Annotated[str, "First rate metric key (e.g. 'fed_rate', 'ecb_deposit')"],
        rate2_metric: Annotated[str, "Second rate metric key"],
    ) -> str:
        """Compute the rate differential (rate1 - rate2) for verification. Returns the computed spread."""
        path1 = METRIC_ALIASES.get(rate1_metric, rate1_metric)
        path2 = METRIC_ALIASES.get(rate2_metric, rate2_metric)
        val1 = _resolve_path(source_data, path1)
        val2 = _resolve_path(source_data, path2)
        if val1 is None:
            return f"NOT_FOUND: '{rate1_metric}' (path: {path1})"
        if val2 is None:
            return f"NOT_FOUND: '{rate2_metric}' (path: {path2})"
        try:
            spread = float(val1) - float(val2)
        except (TypeError, ValueError):
            return f"NOT_NUMERIC: cannot compute spread between '{val1}' and '{val2}'"
        return f"SPREAD: {rate1_metric} ({val1}) - {rate2_metric} ({val2}) = {spread:+.4f}"

    @tool(max_invocation_exceptions=2)
    def get_source_value(
        metric_path: Annotated[str, "Metric key (e.g. 'fed_rate') or dot-path (e.g. 'fed_rates.mid')"],
    ) -> str:
        """Look up a raw value from the source data. Returns the value or NOT_FOUND."""
        path = METRIC_ALIASES.get(metric_path, metric_path)
        val = _resolve_path(source_data, path)
        if val is None:
            available = ", ".join(sorted(METRIC_ALIASES.keys()))
            return f"NOT_FOUND: '{metric_path}' (path: {path}). Available aliases: {available}"
        return f"VALUE: {metric_path} = {val}"

    @tool(max_invocation_exceptions=2)
    def check_pct_change(
        metric: Annotated[str, "Metric key matching delta keys (e.g. 'usd_chf', 'brent')"],
        period: Annotated[str, "Time period: '1d', '1w', or '1m'"],
        cited_pct: Annotated[float, "The percentage change cited in the brief"],
        tolerance: Annotated[float, "Acceptable absolute deviation in percentage points"] = 0.5,
    ) -> str:
        """Verify a percentage change claim against computed deltas. Returns MATCH or MISMATCH."""
        period_deltas = deltas.get(period, {})
        if not period_deltas:
            return f"NOT_FOUND: no delta data for period '{period}'"
        metric_delta = period_deltas.get(metric)
        if metric_delta is None:
            available = ", ".join(sorted(period_deltas.keys()))
            return f"NOT_FOUND: no '{metric}' in {period} deltas. Available: {available}"
        pct = metric_delta.get("pct_change")
        if pct is None:
            abs_change = metric_delta.get("change")
            if abs_change is not None:
                return f"NO_PCT: '{metric}' {period} has absolute change {abs_change} but no percentage change computed"
            return f"NOT_FOUND: no change data for '{metric}' in {period}"
        diff = abs(float(pct) - cited_pct)
        if diff <= tolerance:
            return f"MATCH: {metric} {period} change = {pct:.2f}% (cited {cited_pct}%, diff {diff:.2f}pp within tolerance)"
        return f"MISMATCH: {metric} {period} change = {pct:.2f}% but brief cites {cited_pct}% (diff {diff:.2f}pp exceeds tolerance)"

    return [verify_number, compute_spread, get_source_value, check_pct_change]
