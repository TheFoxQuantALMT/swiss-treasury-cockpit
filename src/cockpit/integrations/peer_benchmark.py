"""Peer benchmarking hooks — overlay FINMA aggregate IRRBB statistics.

Provides comparison of the bank's IRRBB metrics against industry
aggregate data from FINMA publications.
"""
from __future__ import annotations

from typing import Optional


# FINMA aggregate statistics (from annual IRRBB publication, 2024 data)
# These are illustrative; in production, would be loaded from an external source.
FINMA_AGGREGATES = {
    "delta_eve_pct_tier1": {
        "p25": 3.2,
        "median": 6.8,
        "p75": 11.4,
        "mean": 7.5,
        "label": "ΔEVE / Tier 1 (%)",
    },
    "nii_sensitivity_pct": {
        "p25": -2.1,
        "median": -4.5,
        "p75": -8.2,
        "mean": -5.0,
        "label": "NII Sensitivity +200bp (%)",
    },
    "avg_duration_years": {
        "p25": 1.8,
        "median": 3.2,
        "p75": 5.1,
        "mean": 3.4,
        "label": "Average Duration (years)",
    },
    "nmd_share_pct": {
        "p25": 25,
        "median": 38,
        "p75": 52,
        "mean": 39,
        "label": "NMD Share (%)",
    },
}


def compute_peer_comparison(
    bank_metrics: dict[str, float],
    aggregates: Optional[dict] = None,
) -> dict:
    """Compare bank metrics against FINMA peer group aggregates.

    Args:
        bank_metrics: Bank's own metrics keyed by metric name.
            Expected keys: delta_eve_pct_tier1, nii_sensitivity_pct,
            avg_duration_years, nmd_share_pct.
        aggregates: Optional override for peer data (default: FINMA_AGGREGATES).

    Returns:
        Dict with per-metric comparison (percentile position, vs median).
    """
    agg = aggregates or FINMA_AGGREGATES
    if not bank_metrics:
        return {"has_data": False}

    comparisons = []
    for key, bank_val in bank_metrics.items():
        if key not in agg:
            continue
        peer = agg[key]
        # Determine percentile position (simplified linear interpolation)
        if bank_val <= peer["p25"]:
            percentile = 25 * (bank_val / peer["p25"]) if peer["p25"] != 0 else 0
        elif bank_val <= peer["median"]:
            percentile = 25 + 25 * (bank_val - peer["p25"]) / (peer["median"] - peer["p25"]) if peer["median"] != peer["p25"] else 50
        elif bank_val <= peer["p75"]:
            percentile = 50 + 25 * (bank_val - peer["median"]) / (peer["p75"] - peer["median"]) if peer["p75"] != peer["median"] else 75
        else:
            percentile = min(99, 75 + 25 * (bank_val - peer["p75"]) / max(peer["p75"] - peer["median"], 1))

        # Determine assessment
        if percentile < 25:
            assessment, severity = "Well below peers", "positive"
        elif percentile < 50:
            assessment, severity = "Below median", "positive"
        elif percentile < 75:
            assessment, severity = "Above median", "warning"
        else:
            assessment, severity = "High outlier", "negative"

        # Unit from label (extract parenthetical)
        unit = ""
        if "(%)" in peer["label"] or "(%" in peer["label"]:
            unit = "%"
        elif "(years)" in peer["label"]:
            unit = "Y"

        comparisons.append({
            "metric": peer["label"],
            "bank_value": round(bank_val, 2),
            "median": peer["median"],
            "p25": peer["p25"],
            "p75": peer["p75"],
            "percentile": round(max(0, min(99, percentile)), 0),
            "vs_median": round(bank_val - peer["median"], 2),
            "unit": unit,
            "assessment": assessment,
            "severity": severity,
        })

    return {
        "has_data": len(comparisons) > 0,
        "comparisons": comparisons,
    }
