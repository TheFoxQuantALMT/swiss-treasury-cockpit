"""Output formatting: Excel export."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_excel(pnl_all: pd.DataFrame, path: Path) -> Path:
    """Write P&L results to Excel."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pnl_all.to_excel(path, index=False, engine="openpyxl")
    return path
