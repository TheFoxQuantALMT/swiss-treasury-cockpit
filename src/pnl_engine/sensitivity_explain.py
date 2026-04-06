"""Sensitivity explain — decompose delta-sensitivity into drivers.

Breaks down the change in NII sensitivity between two dates into
contributing factors: new deals, maturing deals, rate changes, and
volume changes.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def explain_sensitivity_change(
    current_sensitivity: dict[str, float],
    previous_sensitivity: dict[str, float],
    current_deals: Optional[pd.DataFrame] = None,
    previous_deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Decompose the change in NII sensitivity into drivers.

    Args:
        current_sensitivity: Current sensitivity by currency {"CHF": -5000, ...}.
        previous_sensitivity: Previous sensitivity by currency.
        current_deals: Current deal set (for new/maturing analysis).
        previous_deals: Previous deal set.

    Returns:
        Dict with waterfall components per currency.
    """
    if not current_sensitivity or not previous_sensitivity:
        return {"has_data": False}

    all_ccys = sorted(set(current_sensitivity.keys()) | set(previous_sensitivity.keys()))
    waterfall = []

    for ccy in all_ccys:
        curr = current_sensitivity.get(ccy, 0.0)
        prev = previous_sensitivity.get(ccy, 0.0)
        total_change = curr - prev

        # Decompose into components
        new_deals_impact = 0.0
        maturing_impact = 0.0
        rate_effect = 0.0

        if current_deals is not None and previous_deals is not None:
            curr_ids = set(current_deals["Dealid"].dropna()) if "Dealid" in current_deals.columns else set()
            prev_ids = set(previous_deals["Dealid"].dropna()) if "Dealid" in previous_deals.columns else set()

            new_ids = curr_ids - prev_ids
            matured_ids = prev_ids - curr_ids

            # Approximate: new deals contribute proportionally
            if curr_ids:
                new_ratio = len(new_ids) / len(curr_ids)
                new_deals_impact = curr * new_ratio * 0.5  # Rough approximation
            if prev_ids:
                mat_ratio = len(matured_ids) / len(prev_ids)
                maturing_impact = -prev * mat_ratio * 0.5

            rate_effect = total_change - new_deals_impact - maturing_impact
        else:
            rate_effect = total_change

        waterfall.append({
            "currency": ccy,
            "previous": round(prev, 0),
            "current": round(curr, 0),
            "total_change": round(total_change, 0),
            "new_deals": round(new_deals_impact, 0),
            "maturing": round(maturing_impact, 0),
            "rate_effect": round(rate_effect, 0),
        })

    total_prev = sum(previous_sensitivity.values())
    total_curr = sum(current_sensitivity.values())

    return {
        "has_data": True,
        "waterfall": waterfall,
        "total_previous": round(total_prev, 0),
        "total_current": round(total_curr, 0),
        "total_change": round(total_curr - total_prev, 0),
    }
