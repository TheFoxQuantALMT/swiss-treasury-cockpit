"""Sensitivity explain — decompose delta-sensitivity into drivers.

Breaks down the change in NII sensitivity between two dates into
contributing factors: new deals, maturing deals, rate changes, and
volume changes.

Uses actual deal-level sensitivity data when available for precise
attribution (not proportional approximation).
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
    current_deal_sensitivity: Optional[pd.DataFrame] = None,
    previous_deal_sensitivity: Optional[pd.DataFrame] = None,
) -> dict:
    """Decompose the change in NII sensitivity into drivers.

    When deal-level sensitivity DataFrames are provided, the decomposition
    uses actual per-deal sensitivity contributions instead of rough
    proportional estimates.

    Args:
        current_sensitivity: Current sensitivity by currency {"CHF": -5000, ...}.
        previous_sensitivity: Previous sensitivity by currency.
        current_deals: Current deal set (for new/maturing analysis).
        previous_deals: Previous deal set.
        current_deal_sensitivity: Per-deal sensitivity (Dealid, Currency, sensitivity).
            Sensitivity = PnL(shock=50) - PnL(shock=0) per deal.
        previous_deal_sensitivity: Previous period per-deal sensitivity.

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

        new_deals_impact = 0.0
        maturing_impact = 0.0
        volume_effect = 0.0
        rate_effect = 0.0

        has_deal_sens = (
            current_deal_sensitivity is not None
            and previous_deal_sensitivity is not None
            and not current_deal_sensitivity.empty
            and not previous_deal_sensitivity.empty
        )

        if has_deal_sens:
            # Use actual deal-level sensitivity for precise attribution
            curr_ds = current_deal_sensitivity
            prev_ds = previous_deal_sensitivity

            # Filter to this currency if Currency column available
            if "Currency" in curr_ds.columns:
                curr_ds = curr_ds[curr_ds["Currency"] == ccy]
            if "Currency" in prev_ds.columns:
                prev_ds = prev_ds[prev_ds["Currency"] == ccy]

            curr_ids = set(curr_ds["Dealid"].dropna()) if "Dealid" in curr_ds.columns else set()
            prev_ids = set(prev_ds["Dealid"].dropna()) if "Dealid" in prev_ds.columns else set()

            new_ids = curr_ids - prev_ids
            matured_ids = prev_ids - curr_ids
            existing_ids = curr_ids & prev_ids

            sens_col = "sensitivity"
            if sens_col not in curr_ds.columns:
                sens_col = next((c for c in curr_ds.columns if "sens" in c.lower()), None)

            if sens_col and sens_col in curr_ds.columns and sens_col in prev_ds.columns:
                # New deals: their actual sensitivity contribution
                if new_ids:
                    new_mask = curr_ds["Dealid"].isin(new_ids)
                    new_deals_impact = float(curr_ds.loc[new_mask, sens_col].sum())

                # Matured deals: their lost sensitivity
                if matured_ids:
                    mat_mask = prev_ds["Dealid"].isin(matured_ids)
                    maturing_impact = -float(prev_ds.loc[mat_mask, sens_col].sum())

                # Existing deals: decompose into volume and rate effects
                if existing_ids:
                    existing_curr = curr_ds[curr_ds["Dealid"].isin(existing_ids)]
                    existing_prev = prev_ds[prev_ds["Dealid"].isin(existing_ids)]

                    existing_change = (
                        float(existing_curr[sens_col].sum())
                        - float(existing_prev[sens_col].sum())
                    )

                    # If Nominal available, split into volume vs rate
                    if "Nominal" in existing_curr.columns and "Nominal" in existing_prev.columns:
                        nom_curr = float(existing_curr["Nominal"].sum())
                        nom_prev = float(existing_prev["Nominal"].sum())
                        sens_prev_total = float(existing_prev[sens_col].sum())

                        if abs(nom_prev) > 1e-6 and abs(sens_prev_total) > 1e-6:
                            sens_per_unit = sens_prev_total / nom_prev
                            volume_effect = (nom_curr - nom_prev) * sens_per_unit
                            rate_effect = existing_change - volume_effect
                        else:
                            rate_effect = existing_change
                    else:
                        rate_effect = existing_change
                else:
                    rate_effect = total_change - new_deals_impact - maturing_impact
            else:
                # sens_col not found — fall back to deal-count method with deals
                rate_effect = total_change
        elif current_deals is not None and previous_deals is not None:
            # Fallback: use deal sets for new/matured identification
            curr_ids = set(current_deals["Dealid"].dropna()) if "Dealid" in current_deals.columns else set()
            prev_ids = set(previous_deals["Dealid"].dropna()) if "Dealid" in previous_deals.columns else set()

            new_ids = curr_ids - prev_ids
            matured_ids = prev_ids - curr_ids

            # Filter deals by currency if possible
            if "Currency" in current_deals.columns:
                ccy_curr = current_deals[current_deals["Currency"] == ccy]
                ccy_prev = previous_deals[previous_deals["Currency"] == ccy] if "Currency" in previous_deals.columns else previous_deals
                curr_ids_ccy = set(ccy_curr["Dealid"].dropna())
                prev_ids_ccy = set(ccy_prev["Dealid"].dropna())
                new_ids = curr_ids_ccy - prev_ids_ccy
                matured_ids = prev_ids_ccy - curr_ids_ccy
                n_curr = len(curr_ids_ccy)
                n_prev = len(prev_ids_ccy)
            else:
                n_curr = len(curr_ids)
                n_prev = len(prev_ids)

            # Without deal-level sensitivity, use proportional estimate
            # weighted by deal count ratio
            if n_curr > 0:
                new_deals_impact = curr * (len(new_ids) / n_curr)
            if n_prev > 0:
                maturing_impact = -prev * (len(matured_ids) / n_prev)

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
            "volume_effect": round(volume_effect, 0),
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
