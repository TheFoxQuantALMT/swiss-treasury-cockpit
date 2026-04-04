import json
from pathlib import Path
from cockpit.render.renderer import render_cockpit


def test_render_cockpit_empty_context(tmp_path: Path):
    output = tmp_path / "test_cockpit.html"
    render_cockpit(
        macro_data=None,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    assert output.exists()
    html = output.read_text()
    assert "Swiss Treasury Cockpit" in html
    assert "2026-04-03" in html
    # All tabs should have placeholders
    assert "cockpit fetch" in html or "cockpit compute" in html


def test_render_cockpit_with_macro_data(tmp_path: Path):
    output = tmp_path / "test_cockpit.html"
    macro = {
        "rates": {"fed_rates": {"mid": 3.625}},
        "scores": {"USD": {"composite": 55, "label": "Watch", "driver": "policy", "families": {}}},
        "alerts": [],
    }
    render_cockpit(
        macro_data=macro,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    html = output.read_text()
    assert "Watch" in html
    assert "3.625" in html or "3.63" in html


def test_render_cockpit_self_contained(tmp_path: Path):
    """Verify no external CDN references."""
    output = tmp_path / "test_cockpit.html"
    render_cockpit(
        macro_data=None,
        pnl_data=None,
        portfolio_data=None,
        scores_data=None,
        brief_data=None,
        date="2026-04-03",
        output_path=output,
    )
    html = output.read_text()
    assert "cdn." not in html.lower()
    assert "unpkg.com" not in html.lower()
