"""Smoke tests for cockpit.agents module."""


def test_models_import():
    from cockpit.agents.models import ReviewResult, AnalystOutput, ChartSelection
    assert ReviewResult is not None
    assert AnalystOutput is not None
    assert ChartSelection is not None


def test_analyst_template_builder():
    from cockpit.agents.analyst import _build_template
    assert callable(_build_template)


def test_reviewer_programmatic_check():
    from cockpit.agents.reviewer import programmatic_check
    assert callable(programmatic_check)


def test_models_instantiation():
    """Verify Pydantic models can be instantiated with valid data."""
    from cockpit.agents.models import ReviewResult, ReviewError, AnalystOutput, ChartSelection

    err = ReviewError(section="Fed", issue="rate mismatch", severity="high")
    result = ReviewResult(valid=False, errors=[err], warnings=[], summary="test")
    assert result.valid is False
    assert len(result.errors) == 1

    chart = ChartSelection(chart_type="fx_history", rationale="test")
    output = AnalystOutput(brief="test brief", charts=[chart], highlights=["h1"])
    assert output.brief == "test brief"
    assert len(output.charts) == 1


def test_programmatic_check_returns_list():
    """Verify programmatic_check returns a list (even on empty data)."""
    from cockpit.agents.reviewer import programmatic_check

    errors = programmatic_check("some brief text", {})
    assert isinstance(errors, list)


def test_build_template_returns_string():
    """Verify _build_template returns a non-empty string."""
    from cockpit.agents.analyst import _build_template

    result = _build_template(data={}, deltas={}, delta_table="", alerts=[])
    assert isinstance(result, str)
    assert len(result) > 0
    assert "[INTERPRET" in result


def test_tools_metric_aliases():
    """Verify METRIC_ALIASES dict is accessible."""
    from cockpit.agents.tools import METRIC_ALIASES
    assert isinstance(METRIC_ALIASES, dict)
    assert "fed_rate" in METRIC_ALIASES
    assert "eur_chf" in METRIC_ALIASES


def test_reporter_sanitize():
    """Verify _sanitize_brief removes [INTERPRET] markers."""
    from cockpit.agents.reporter import _sanitize_brief

    dirty = "Some text [INTERPRET: do something] more text"
    clean = _sanitize_brief(dirty)
    assert "[INTERPRET" not in clean
    assert "Some text" in clean
    assert "more text" in clean


def test_reporter_markdown_to_html():
    """Verify _markdown_to_html converts basic markdown."""
    from cockpit.agents.reporter import _markdown_to_html

    md = "## Header\n- item one\n- item two\n"
    html = _markdown_to_html(md)
    assert "<h2>" in html
    assert "<li>" in html
