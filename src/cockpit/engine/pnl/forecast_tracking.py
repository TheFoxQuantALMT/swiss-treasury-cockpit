"""NII forecast snapshot storage and retrieval.

Saves daily NII forecast snapshots and loads historical series
for the forecast tracking dashboard tab.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def save_nii_forecast(
    pnl_all_s: pd.DataFrame,
    date: str,
    output_dir: Path,
) -> Path | None:
    """Save current 12M NII forecast as a dated JSON snapshot.

    Args:
        pnl_all_s: Stacked P&L DataFrame.
        date: Date string (YYYY-MM-DD).
        output_dir: Directory for snapshot files.

    Returns:
        Path to saved file, or None if no data.
    """
    if pnl_all_s is None or pnl_all_s.empty:
        return None

    df = pnl_all_s.copy()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()

    pnl = df[(df["Indice"] == "PnL_Simple") & (df["Shock"] == "0")]
    if pnl.empty:
        return None

    by_currency = {}
    if "Deal currency" in pnl.columns:
        for ccy in sorted(pnl["Deal currency"].unique()):
            by_currency[ccy] = round(float(pnl[pnl["Deal currency"] == ccy]["Value"].sum()), 2)

    total = round(float(pnl["Value"].sum()), 2)

    snapshot = {
        "date": date,
        "by_currency": by_currency,
        "total": total,
    }

    snapshot_dir = output_dir / "pnl_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_nii_forecast.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return out_path


def load_forecast_history(
    snapshot_dir: Path,
    lookback_days: int = 90,
) -> Optional[pd.DataFrame]:
    """Load NII forecast history from snapshot files.

    Args:
        snapshot_dir: Directory containing *_nii_forecast.json files.
        lookback_days: Maximum number of days to look back.

    Returns:
        DataFrame with columns: date, currency, nii_forecast.
        Returns None if no snapshots found.
    """
    if not snapshot_dir.exists():
        return None

    files = sorted(snapshot_dir.glob("*_nii_forecast.json"))
    if not files:
        return None

    rows = []
    for f in files[-lookback_days:]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            date = data.get("date", f.stem.split("_")[0])
            for ccy, val in data.get("by_currency", {}).items():
                rows.append({"date": date, "currency": ccy, "nii_forecast": val})
        except Exception:
            continue

    if not rows:
        return None

    return pd.DataFrame(rows)
