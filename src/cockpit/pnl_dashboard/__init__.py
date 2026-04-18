"""P&L dashboard package.

``render_pnl_dashboard`` is lazy-loaded so the package remains importable
in deployments that ship only the xlsx-export pipeline (no Jinja templates,
no HTML renderer).
"""
from __future__ import annotations

__all__ = ["render_pnl_dashboard"]


def __getattr__(name: str):
    if name == "render_pnl_dashboard":
        from cockpit.pnl_dashboard.renderer import render_pnl_dashboard
        return render_pnl_dashboard
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
