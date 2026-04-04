"""Pydantic models for structured agent I/O.

Used by reviewer (ReviewResult) and analyst (AnalystOutput) agents
to produce typed, schema-validated responses via Ollama's response_format.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ReviewError(BaseModel):
    """A single factual error found in the analyst's brief."""

    section: str
    issue: str
    source_value: float | None = None
    cited_value: float | None = None
    severity: Literal["critical", "high", "medium"]


class ReviewResult(BaseModel):
    """Structured output from the reviewer agent."""

    valid: bool
    errors: list[ReviewError]
    warnings: list[str]
    summary: str


class ChartSelection(BaseModel):
    """A chart selected by the analyst for inclusion in the brief."""

    chart_type: Literal[
        "fx_history",
        "energy",
        "cb_rates",
        "yield_curve",
        "inflation_breakevens",
        "vix",
        "sight_deposits",
        "delta_heatmap",
        "scenario_waterfall",
    ]
    params: dict[str, Any] = {}
    rationale: str


class AnalystOutput(BaseModel):
    """Structured output from the analyst agent."""

    brief: str
    charts: list[ChartSelection]
    highlights: list[str]
