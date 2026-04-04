"""Historical comparison module for 1d/1w/1m deltas.

Computes changes in FX rates, energy prices, central bank rates,
and sight deposits by comparing current data against archived snapshots.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from cockpit.config import DATA_DIR

ARCHIVE_DIR = DATA_DIR / "archive"


def compute_deltas(current_data: dict[str, Any]) -> dict[str, Any]:
    """Compute 1d, 1w, 1m changes for all tracked metrics.

    Args:
        current_data: Latest fetched data snapshot.

    Returns:
        Dict with delta information per metric:
        {
            "usd_chf": {
                "current": 0.7950,
                "1d": {"value": 0.7940, "change": 0.0010, "pct": 0.13},
                "1w": {"value": 0.7880, "change": 0.0070, "pct": 0.89},
                "1m": {"value": 0.8100, "change": -0.0150, "pct": -1.85},
            },
            ...
        }
    """
    today = date.today()
    periods = {
        "1d": today - timedelta(days=1),
        "1w": today - timedelta(days=7),
        "1m": today - timedelta(days=30),
    }

    # Load archive snapshots for each period
    archives: dict[str, dict[str, Any] | None] = {}
    for label, target_date in periods.items():
        archives[label] = _load_nearest_archive(target_date)

    # Extract current values
    metrics = _extract_metrics(current_data)

    # Compute deltas
    deltas: dict[str, Any] = {}
    for metric_name, current_value in metrics.items():
        deltas[metric_name] = {"current": current_value}

        for period_label, archive_data in archives.items():
            if archive_data is None:
                deltas[metric_name][period_label] = None
                continue

            past_metrics = _extract_metrics(archive_data)
            past_value = past_metrics.get(metric_name)

            if past_value is not None and past_value != 0:
                change = current_value - past_value
                pct = (change / abs(past_value)) * 100
                deltas[metric_name][period_label] = {
                    "value": round(past_value, 6),
                    "change": round(change, 6),
                    "pct": round(pct, 2),
                }
            else:
                deltas[metric_name][period_label] = None

    return deltas


def _extract_metrics(data: dict[str, Any]) -> dict[str, float]:
    """Extract key numeric metrics from a data snapshot.

    Handles both current fetched data format and archived JSON format.
    """
    metrics: dict[str, float] = {}

    # USD/CHF
    usd_chf = data.get("usd_chf_history", [])
    if usd_chf and isinstance(usd_chf, list):
        metrics["usd_chf"] = usd_chf[-1].get("value", 0)

    # EUR/CHF
    eur_chf = data.get("eur_chf_latest")
    if isinstance(eur_chf, dict):
        metrics["eur_chf"] = eur_chf.get("value", 0)
    elif isinstance(data.get("eur_chf_history"), list) and data["eur_chf_history"]:
        metrics["eur_chf"] = data["eur_chf_history"][-1].get("value", 0)

    # GBP/CHF
    gbp_chf = data.get("gbp_chf_history", [])
    if gbp_chf and isinstance(gbp_chf, list):
        metrics["gbp_chf"] = gbp_chf[-1].get("value", 0)

    # Brent
    brent = data.get("brent_history", [])
    if brent and isinstance(brent, list):
        metrics["brent"] = brent[-1].get("value", 0)

    # EU gas
    eu_gas = data.get("eu_gas_history", [])
    if eu_gas and isinstance(eu_gas, list):
        metrics["eu_gas"] = eu_gas[-1].get("value", 0)

    # Fed rates
    fed = data.get("fed_rates", {})
    if isinstance(fed, dict) and "mid" in fed:
        metrics["fed_rate"] = fed["mid"]

    # ECB rates
    ecb = data.get("ecb_rates", {})
    if isinstance(ecb, dict) and "deposit_facility" in ecb:
        metrics["ecb_rate"] = ecb["deposit_facility"]

    # Daily indicators
    daily = data.get("daily_indicators", {})
    if isinstance(daily, dict):
        for key in ["us_2y", "us_10y", "vix", "breakeven_5y", "breakeven_10y"]:
            if key in daily and isinstance(daily[key], dict):
                metrics[key] = daily[key].get("value", 0)

    # Sight deposits (domestic)
    deposits = data.get("sight_deposits", [])
    if deposits and isinstance(deposits, list):
        last = deposits[-1]
        if "domestic" in last and isinstance(last["domestic"], (int, float)):
            metrics["sight_deposits_domestic"] = last["domestic"]

    return metrics


def _load_nearest_archive(target_date: date) -> dict[str, Any] | None:
    """Load the archive snapshot nearest to target_date.

    Searches for the closest available archive within +/- 5 days,
    preferring earlier dates (past) over later dates (future).
    """
    if not ARCHIVE_DIR.exists():
        return None

    # Search outward from target date: 0, -1, +1, -2, +2, ...
    for offset in range(6):
        candidates = [target_date] if offset == 0 else [
            target_date - timedelta(days=offset),
            target_date + timedelta(days=offset),
        ]
        for check_date in candidates:
            archive_dir = ARCHIVE_DIR / check_date.isoformat()
            snapshot = archive_dir / "latest_snapshot.json"
            if snapshot.exists():
                try:
                    with open(snapshot) as f:
                        data = json.load(f)
                    if offset > 0:
                        logger.debug(
                            f"Archive for {target_date} not found, "
                            f"using {check_date} (offset {offset}d)"
                        )
                    return data
                except json.JSONDecodeError:
                    continue

    return None


def format_deltas_for_brief(deltas: dict[str, Any]) -> str:
    """Format deltas as a readable markdown table for the morning brief.

    Returns:
        Markdown table string.
    """
    lines = [
        "| Metric | Current | 1D Change | 1W Change | 1M Change |",
        "|--------|---------|-----------|-----------|-----------|",
    ]

    display_names = {
        "usd_chf": "USD/CHF",
        "eur_chf": "EUR/CHF",
        "brent": "Brent ($/bbl)",
        "eu_gas": "EU Gas (EUR/MWh)",
        "fed_rate": "Fed Rate (%)",
        "ecb_rate": "ECB Deposit (%)",
        "us_2y": "US 2Y (%)",
        "us_10y": "US 10Y (%)",
        "vix": "VIX",
        "sight_deposits_domestic": "SNB Domestic Dep. (B CHF)",
    }

    for metric, name in display_names.items():
        if metric not in deltas:
            continue
        d = deltas[metric]
        current = f"{d['current']:.4f}" if d["current"] < 10 else f"{d['current']:.2f}"
        cols = [f"**{current}**"]

        for period in ["1d", "1w", "1m"]:
            pd = d.get(period)
            if pd is None:
                cols.append("—")
            else:
                sign = "+" if pd["change"] >= 0 else ""
                cols.append(f"{sign}{pd['change']:.4f} ({sign}{pd['pct']:.1f}%)")

        lines.append(f"| {name} | {' | '.join(cols)} |")

    return "\n".join(lines)
