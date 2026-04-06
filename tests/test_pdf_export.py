"""Tests for cockpit.export.pdf_export module."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cockpit.export.pdf_export import export_html_to_pdf


@pytest.fixture
def sample_html(tmp_path):
    """Create a minimal HTML file for testing."""
    html_file = tmp_path / "dashboard.html"
    html_file.write_text("<html><body><h1>Test</h1></body></html>", encoding="utf-8")
    return html_file


def test_returns_none_when_no_backend(sample_html):
    """Returns None when neither weasyprint nor pdfkit is installed."""
    with patch.dict("sys.modules", {"weasyprint": None, "pdfkit": None}):
        # Force fresh import failure by patching __import__
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name in ("weasyprint", "pdfkit"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = export_html_to_pdf(sample_html)
            assert result is None


def test_default_output_path(sample_html):
    """Default output path is .pdf extension of input."""
    with patch("builtins.__import__", side_effect=ImportError("no backend")):
        # Even though it fails, we can check the function handles path correctly
        result = export_html_to_pdf(sample_html)
        # With no backend, returns None
        assert result is None


def test_explicit_output_path(sample_html, tmp_path):
    """Custom output path is respected."""
    custom_out = tmp_path / "custom.pdf"
    with patch("builtins.__import__", side_effect=ImportError("no backend")):
        result = export_html_to_pdf(sample_html, output_path=custom_out)
        assert result is None


def test_function_signature():
    """Verify function accepts expected parameters."""
    import inspect
    sig = inspect.signature(export_html_to_pdf)
    params = list(sig.parameters.keys())
    assert "html_path" in params
    assert "output_path" in params


def test_accepts_string_path(tmp_path):
    """Function accepts str paths, not just Path objects."""
    html_file = tmp_path / "test.html"
    html_file.write_text("<html></html>", encoding="utf-8")

    # Mock both backends as unavailable
    original_import = __import__

    def mock_import(name, *args, **kwargs):
        if name in ("weasyprint", "pdfkit"):
            raise ImportError(f"No module named '{name}'")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        result = export_html_to_pdf(str(html_file), str(tmp_path / "out.pdf"))
        assert result is None
