"""Parser for WIRP (rate expectations) Excel files."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_wirp(path: Path) -> pd.DataFrame:
    """Parse WIRP → long DataFrame with (Indice, Meeting date, Rate, Hike/Cut)."""
    raw = pd.read_excel(path, skiprows=2, usecols=[2, 3, 4, 5], engine="openpyxl")
    raw.columns = ["Indice", "Meeting", "Rate", "Hike / Cut"]
    raw["Indice"] = raw["Indice"].ffill()
    raw = raw.dropna(subset=["Meeting"])
    raw["Meeting"] = pd.to_datetime(raw["Meeting"], errors="coerce", dayfirst=True)
    raw = raw.dropna(subset=["Meeting"])
    return raw.reset_index(drop=True)
