"""Daily KPI snapshot storage and retrieval for trend analysis.

Saves a compact daily snapshot of key ALM metrics and loads historical
series for the Trends dashboard tab.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def save_daily_kpis(
    dashboard_data: dict,
    date: str,
    output_dir: Path,
) -> Path | None:
    """Save daily KPI snapshot from build_pnl_dashboard_data result.

    Args:
        dashboard_data: Full result dict from build_pnl_dashboard_data().
        date: Date string (YYYY-MM-DD).
        output_dir: Directory for snapshot files.

    Returns:
        Path to saved file, or None if no data.
    """
    kpis = {}

    # NII (base)
    summary = dashboard_data.get("summary", {})
    shock_0 = summary.get("kpis", {}).get("shock_0", {})
    if shock_0:
        kpis["nii_base"] = shock_0.get("total", 0)

    # NII sensitivity (+50bp - base)
    kpis["nii_sensitivity_50bp"] = summary.get("kpis", {}).get("delta_50_0", 0)

    # NIM
    nim = dashboard_data.get("nim", {})
    if nim.get("has_data"):
        kpis["nim_bps"] = nim.get("kpis", {}).get("nim_bps", 0)

    # EVE
    eve = dashboard_data.get("eve", {})
    if eve.get("has_data"):
        kpis["eve_total"] = eve.get("total_eve", 0)
        conv = eve.get("convexity", {})
        if conv:
            kpis["effective_duration"] = conv.get("effective_duration", 0)
        sc = eve.get("scenarios", {})
        if sc:
            kpis["eve_worst_delta"] = sc.get("worst_delta", 0)

    # Counterparty HHI
    cpty = dashboard_data.get("counterparty_pnl", {})
    if cpty.get("has_data"):
        kpis["hhi"] = cpty.get("hhi", 0)

    # Liquidity survival
    liq = dashboard_data.get("liquidity", {})
    if liq.get("has_data"):
        liq_sum = liq.get("summary", {})
        kpis["liquidity_net_30d"] = liq_sum.get("net_30d", 0)
        if liq_sum.get("survival_days") is not None:
            kpis["survival_days"] = liq_sum["survival_days"]

    # Alert count
    alerts = dashboard_data.get("pnl_alerts", {})
    if alerts.get("has_data"):
        a_sum = alerts.get("summary", {})
        kpis["alert_count"] = (
            a_sum.get("critical", 0) + a_sum.get("high", 0) + a_sum.get("medium", 0)
        )

    if not kpis:
        return None

    snapshot = {"date": date, **{k: round(float(v), 2) if v is not None else None for k, v in kpis.items()}}

    snapshot_dir = output_dir / "kpi_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_kpis.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return out_path


def load_kpi_history(
    snapshot_dir: Path,
    lookback_days: int = 90,
) -> Optional[pd.DataFrame]:
    """Load KPI history from snapshot files.

    Args:
        snapshot_dir: Directory containing *_kpis.json files.
        lookback_days: Maximum number of days to look back.

    Returns:
        DataFrame with date column + one column per metric.
        Returns None if no snapshots found.
    """
    kpi_dir = snapshot_dir / "kpi_snapshots"
    if not kpi_dir.exists():
        return None

    files = sorted(kpi_dir.glob("*_kpis.json"))
    if not files:
        return None

    rows = []
    for f in files[-lookback_days:]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rows.append(data)
        except Exception:
            continue

    if not rows:
        return None

    return pd.DataFrame(rows)
