"""Alert system for threshold breaches.

Checks FX levels, rate changes, and sight deposit moves against
configured thresholds. Generates alert payloads for Notion.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from cockpit.config import (
    FX_ALERT_BANDS,
    ENERGY_THRESHOLDS,
    DEPOSIT_THRESHOLDS,
    DAILY_MOVE_THRESHOLDS,
)


def check_alerts(
    current_data: dict[str, Any],
    deltas: dict[str, Any],
) -> list[dict[str, Any]]:
    """Check all thresholds and return triggered alerts.

    Args:
        current_data: Latest fetched data snapshot.
        deltas: Historical comparison deltas from comparison module.

    Returns:
        List of alert dicts:
        [
            {
                "type": "fx_breach",
                "severity": "high",
                "metric": "EUR/CHF",
                "current": 0.8990,
                "threshold": 0.90,
                "direction": "below",
                "message": "EUR/CHF below 0.90 — potential BNS intervention zone",
            },
            ...
        ]
    """
    alerts: list[dict[str, Any]] = []

    # FX alerts
    _check_fx_alerts(deltas, FX_ALERT_BANDS, alerts)

    # Energy alerts
    _check_energy_alerts(deltas, ENERGY_THRESHOLDS, alerts)

    # Sight deposit alerts
    _check_deposit_alerts(current_data, DEPOSIT_THRESHOLDS, alerts)

    # Daily move alerts (large % changes)
    _check_daily_moves(deltas, DAILY_MOVE_THRESHOLDS, alerts)

    # Rate change alerts — check if any rate changes occurred
    _check_rate_changes(deltas, alerts)

    if alerts:
        logger.warning(f"{len(alerts)} alert(s) triggered")
        for alert in alerts:
            logger.warning(f"  [{alert['severity']}] {alert['message']}")

    return alerts


def _check_fx_alerts(
    deltas: dict[str, Any],
    fx_bands: dict[str, dict[str, float]],
    alerts: list[dict[str, Any]],
) -> None:
    """Check FX level thresholds."""
    fx_map = {
        "eur_chf": ("EUR/CHF", "EUR_CHF"),
        "usd_chf": ("USD/CHF", "USD_CHF"),
        "gbp_chf": ("GBP/CHF", "GBP_CHF"),
    }

    for metric_key, (display_name, band_key) in fx_map.items():
        if metric_key not in deltas:
            continue
        if band_key not in fx_bands:
            continue

        current = deltas[metric_key]["current"]
        bands = fx_bands[band_key]
        low_threshold = bands.get("low")
        high_threshold = bands.get("high")

        if low_threshold is not None and current < low_threshold:
            alerts.append({
                "type": "fx_breach",
                "severity": "high",
                "metric": display_name,
                "current": current,
                "threshold": low_threshold,
                "direction": "below",
                "message": f"{display_name} at {current:.4f} — below {low_threshold} threshold",
            })

        if high_threshold is not None and current > high_threshold:
            alerts.append({
                "type": "fx_breach",
                "severity": "medium",
                "metric": display_name,
                "current": current,
                "threshold": high_threshold,
                "direction": "above",
                "message": f"{display_name} at {current:.4f} — above {high_threshold} threshold",
            })


def _check_energy_alerts(
    deltas: dict[str, Any],
    thresholds: dict[str, float],
    alerts: list[dict[str, Any]],
) -> None:
    """Check energy price thresholds."""
    energy_map = {
        "brent": ("Brent", "brent", "$/bbl"),
        "eu_gas": ("EU Gas (TTF)", "eu_gas", "EUR/MWh"),
    }

    for metric_key, (display_name, threshold_prefix, unit) in energy_map.items():
        if metric_key not in deltas:
            continue

        current = deltas[metric_key]["current"]
        high_key = f"{threshold_prefix}_high"
        low_key = f"{threshold_prefix}_low"

        if high_key in thresholds and current > thresholds[high_key]:
            alerts.append({
                "type": "energy_breach",
                "severity": "high",
                "metric": display_name,
                "current": current,
                "threshold": thresholds[high_key],
                "direction": "above",
                "message": f"{display_name} at {current:.2f} {unit} — above escalation threshold {thresholds[high_key]}",
            })

        if low_key in thresholds and current < thresholds[low_key]:
            alerts.append({
                "type": "energy_breach",
                "severity": "medium",
                "metric": display_name,
                "current": current,
                "threshold": thresholds[low_key],
                "direction": "below",
                "message": f"{display_name} at {current:.2f} {unit} — below ceasefire threshold {thresholds[low_key]}",
            })


def _check_deposit_alerts(
    current_data: dict[str, Any],
    thresholds: dict[str, float],
    alerts: list[dict[str, Any]],
) -> None:
    """Check sight deposit weekly moves for intervention signals."""
    threshold_bln = thresholds.get("weekly_change_threshold_bln", 2.0)

    deposits = current_data.get("sight_deposits", [])
    if not deposits or len(deposits) < 2:
        return

    # Compare last two weeks of domestic deposits
    last = deposits[-1]
    prev = deposits[-2]

    for col in ["Domestic", "domestic", "Inland"]:
        if col in last and col in prev:
            current_val = last[col]
            prev_val = prev[col]
            if isinstance(current_val, (int, float)) and isinstance(prev_val, (int, float)):
                # Values from SNB are in millions CHF — convert to billions
                change_bln = (current_val - prev_val) / 1000
                if abs(change_bln) >= threshold_bln:
                    direction = "increase" if change_bln > 0 else "decrease"
                    alerts.append({
                        "type": "deposit_move",
                        "severity": "high",
                        "metric": "BNS Domestic Sight Deposits",
                        "current": current_val,
                        "change": change_bln,
                        "threshold": threshold_bln,
                        "direction": direction,
                        "message": (
                            f"BNS domestic sight deposits {direction} of "
                            f"{abs(change_bln):.1f}B CHF — exceeds {threshold_bln}B threshold "
                            f"(probable FX intervention signal)"
                        ),
                    })
            break


def _check_daily_moves(
    deltas: dict[str, Any],
    thresholds: dict[str, float],
    alerts: list[dict[str, Any]],
) -> None:
    """Check for large daily percentage moves."""
    metric_thresholds = {
        "brent": ("Brent", thresholds.get("brent_pct", 5.0), "$/bbl"),
        "eu_gas": ("EU Gas (TTF)", thresholds.get("eu_gas_pct", 5.0), "EUR/MWh"),
        "usd_chf": ("USD/CHF", thresholds.get("fx_pct", 1.0), ""),
        "eur_chf": ("EUR/CHF", thresholds.get("fx_pct", 1.0), ""),
        "vix": ("VIX", thresholds.get("vix_pct", 10.0), ""),
    }

    for metric_key, (display_name, threshold_pct, unit) in metric_thresholds.items():
        if metric_key not in deltas:
            continue

        d1 = deltas[metric_key].get("1d")
        if d1 is None or not isinstance(d1, dict):
            continue

        pct = d1.get("pct", 0)
        if abs(pct) >= threshold_pct:
            direction = "up" if pct > 0 else "down"
            current = deltas[metric_key]["current"]
            severity = "high" if abs(pct) >= threshold_pct * 1.5 else "medium"
            value_str = f"{current:.2f} {unit}".strip() if unit else f"{current:.4f}"
            alerts.append({
                "type": "daily_move",
                "severity": severity,
                "metric": display_name,
                "current": current,
                "change_pct": pct,
                "threshold_pct": threshold_pct,
                "direction": direction,
                "message": (
                    f"{display_name} {direction} {abs(pct):.1f}% in 1D "
                    f"(now {value_str}) — exceeds {threshold_pct:.0f}% daily move threshold"
                ),
            })


def _check_rate_changes(
    deltas: dict[str, Any],
    alerts: list[dict[str, Any]],
) -> None:
    """Check for any central bank rate changes (1d delta)."""
    rate_metrics = {
        "fed_rate": "Fed Funds Rate",
        "ecb_rate": "ECB Deposit Rate",
    }

    for metric_key, display_name in rate_metrics.items():
        if metric_key not in deltas:
            continue

        d1 = deltas[metric_key].get("1d")
        if d1 is not None and d1["change"] != 0:
            alerts.append({
                "type": "rate_change",
                "severity": "critical",
                "metric": display_name,
                "current": deltas[metric_key]["current"],
                "change": d1["change"],
                "direction": "hike" if d1["change"] > 0 else "cut",
                "message": (
                    f"{display_name} changed by {d1['change']:+.2f}% to "
                    f"{deltas[metric_key]['current']:.2f}%"
                ),
            })
