"""PDF export for the P&L dashboard.

Converts the rendered HTML dashboard to PDF using weasyprint or pdfkit
(whichever is available). Falls back gracefully if neither is installed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def export_html_to_pdf(
    html_path: Path | str,
    output_path: Optional[Path | str] = None,
) -> Path | None:
    """Convert HTML dashboard to PDF.

    Tries weasyprint first, then pdfkit. Returns None if neither available.

    Args:
        html_path: Path to the rendered HTML file.
        output_path: Output PDF path (default: same name with .pdf extension).

    Returns:
        Path to the generated PDF, or None on failure.
    """
    html_path = Path(html_path)
    if output_path is None:
        output_path = html_path.with_suffix(".pdf")
    output_path = Path(output_path)

    # Try weasyprint
    try:
        from weasyprint import HTML
        HTML(filename=str(html_path)).write_pdf(str(output_path))
        return output_path
    except ImportError:
        pass
    except Exception as e:
        print(f"[pdf-export] weasyprint failed: {e}")

    # Try pdfkit
    try:
        import pdfkit
        pdfkit.from_file(str(html_path), str(output_path))
        return output_path
    except ImportError:
        pass
    except Exception as e:
        print(f"[pdf-export] pdfkit failed: {e}")

    print("[pdf-export] Neither weasyprint nor pdfkit available. Install with: pip install weasyprint")
    return None
