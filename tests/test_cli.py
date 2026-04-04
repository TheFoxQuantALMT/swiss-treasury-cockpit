import json
from pathlib import Path
from unittest.mock import patch, AsyncMock
from cockpit.cli import cmd_render


def test_cmd_render_creates_html(tmp_path: Path):
    """render command should produce HTML even with no input data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    cmd_render(date="2026-04-03", data_dir=data_dir, output_dir=output_dir)

    html_files = list(output_dir.glob("*.html"))
    assert len(html_files) == 1
    assert "2026-04-03" in html_files[0].name
    html = html_files[0].read_text()
    assert "Swiss Treasury Cockpit" in html


def test_cmd_render_with_macro_data(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    macro = {"rates": {"fed_rates": {"mid": 3.625}}, "alerts": []}
    (data_dir / "2026-04-03_macro_snapshot.json").write_text(json.dumps(macro))

    cmd_render(date="2026-04-03", data_dir=data_dir, output_dir=output_dir)

    html = (output_dir / "2026-04-03_cockpit.html").read_text()
    assert "3.625" in html or "cockpit fetch" not in html
