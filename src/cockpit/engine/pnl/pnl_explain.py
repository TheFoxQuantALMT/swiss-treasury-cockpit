"""P&L Explain — waterfall decomposition of NII changes between two dates.

Decomposes ΔP&L into actionable drivers:
  1. Time/Roll-down effect — P&L from passage of time at unchanged rates
  2. New deals — NII contribution from deals entered since prev date
  3. Maturing deals — NII lost from deals that matured
  4. Rate effect — impact of OIS curve movement on existing portfolio
  5. Spread effect — change in client rate vs OIS spread
  6. Residual — unexplained (mix, rounding, model)

The waterfall reads:
  Prev NII → +Time → +New Deals → -Matured → +Rate → +Spread → +Residual → Current NII

Requires two engine runs (current and previous) to compare.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_pnl_explain(
    curr_pnl_by_deal: pd.DataFrame,
    prev_pnl_by_deal: pd.DataFrame,
    curr_pnl_all_s: pd.DataFrame,
    prev_pnl_all_s: pd.DataFrame,
    deals: pd.DataFrame,
    date_run: datetime,
    prev_date_run: datetime,
) -> dict:
    """Compute P&L explain waterfall between two dates.

    Args:
        curr_pnl_by_deal: Current deal-level P&L (Shock=0).
        prev_pnl_by_deal: Previous deal-level P&L (Shock=0).
        curr_pnl_all_s: Current stacked P&L (for rate/nominal aggregates).
        prev_pnl_all_s: Previous stacked P&L.
        deals: Current deal metadata (with Valuedate, Maturitydate).
        date_run: Current run date.
        prev_date_run: Previous run date.

    Returns:
        Dict with waterfall data, by-currency breakdown, and deal-level details.
    """
    if curr_pnl_by_deal is None or curr_pnl_by_deal.empty:
        return {"has_data": False}
    if prev_pnl_by_deal is None or prev_pnl_by_deal.empty:
        return {"has_data": False}

    # Filter to Shock=0
    curr = curr_pnl_by_deal[curr_pnl_by_deal["Shock"] == "0"].copy() if "Shock" in curr_pnl_by_deal.columns else curr_pnl_by_deal.copy()
    prev = prev_pnl_by_deal[prev_pnl_by_deal["Shock"] == "0"].copy() if "Shock" in prev_pnl_by_deal.columns else prev_pnl_by_deal.copy()

    # Ensure string Dealid for matching
    for df in [curr, prev]:
        if "Dealid" in df.columns:
            df["Dealid"] = df["Dealid"].astype(str)

    # Aggregate to deal-level totals (across months)
    curr_by_deal = _aggregate_deal_pnl(curr)
    prev_by_deal = _aggregate_deal_pnl(prev)

    # Classify deals
    curr_ids = set(curr_by_deal["Dealid"])
    prev_ids = set(prev_by_deal["Dealid"])

    new_ids = curr_ids - prev_ids
    matured_ids = prev_ids - curr_ids
    existing_ids = curr_ids & prev_ids

    # Also classify by date if deal metadata available
    if deals is not None and not deals.empty:
        deals_meta = deals.copy()
        if "Dealid" in deals_meta.columns:
            deals_meta["Dealid"] = deals_meta["Dealid"].astype(str)
            mat_dates = pd.to_datetime(deals_meta.set_index("Dealid")["Maturitydate"], errors="coerce")
            val_dates = pd.to_datetime(deals_meta.set_index("Dealid")["Valuedate"], errors="coerce")
            prev_ts = pd.Timestamp(prev_date_run)
            curr_ts = pd.Timestamp(date_run)

            # Deals that started after prev_date (new production)
            for did in existing_ids.copy():
                vd = val_dates.get(did)
                if vd is not None and pd.notna(vd) and vd > prev_ts:
                    new_ids.add(did)
                    existing_ids.discard(did)

            # Deals that matured between prev and current
            for did in existing_ids.copy():
                md = mat_dates.get(did)
                if md is not None and pd.notna(md) and md <= curr_ts and md > prev_ts:
                    matured_ids.add(did)
                    existing_ids.discard(did)

    # --- Compute effects ---
    # 1. New deals: sum current P&L for new deals
    new_deal_pnl = curr_by_deal[curr_by_deal["Dealid"].isin(new_ids)]["PnL"].sum() if new_ids else 0.0

    # 2. Maturing deals: negative of prev P&L for matured deals
    matured_deal_pnl = -(prev_by_deal[prev_by_deal["Dealid"].isin(matured_ids)]["PnL"].sum()) if matured_ids else 0.0

    # 3. For existing deals: decompose ΔP&L into rate + time + spread
    existing_curr = curr_by_deal[curr_by_deal["Dealid"].isin(existing_ids)].set_index("Dealid")
    existing_prev = prev_by_deal[prev_by_deal["Dealid"].isin(existing_ids)].set_index("Dealid")

    # Join existing deals
    both_ids = sorted(existing_ids)
    time_effect = 0.0
    rate_effect = 0.0
    spread_effect = 0.0

    # Get aggregate rate/nominal data from pnlAllS
    curr_s = _safe_reset(curr_pnl_all_s)
    prev_s = _safe_reset(prev_pnl_all_s)

    curr_rates = _extract_by_ccy(curr_s, "OISfwd")
    prev_rates = _extract_by_ccy(prev_s, "OISfwd")
    curr_ref = _extract_by_ccy(curr_s, "RateRef")
    prev_ref = _extract_by_ccy(prev_s, "RateRef")
    curr_nom = _extract_by_ccy(curr_s, "Nominal")
    prev_nom = _extract_by_ccy(prev_s, "Nominal")

    currencies = sorted(set(curr_rates.keys()) | set(prev_rates.keys()))
    by_currency = {}

    for ccy in currencies:
        nom_p = prev_nom.get(ccy, 0)
        nom_c = curr_nom.get(ccy, 0)
        ois_p = prev_rates.get(ccy, 0)
        ois_c = curr_rates.get(ccy, 0)
        ref_p = prev_ref.get(ccy, 0)
        ref_c = curr_ref.get(ccy, 0)

        # Spread = OIS - RateRef (the margin)
        spread_p = ois_p - ref_p
        spread_c = ois_c - ref_c

        # Rate effect on existing portfolio: Nom_prev × ΔOIS / MM (approx)
        ccy_rate_eff = nom_p * (ois_c - ois_p) / 360 * 30  # ~1 month approx
        rate_effect += ccy_rate_eff

        # Spread effect: Nom_prev × ΔSpread / MM
        ccy_spread_eff = nom_p * ((spread_c) - (spread_p)) / 360 * 30
        spread_effect += ccy_spread_eff

        by_currency[ccy] = {
            "ois_prev": round(float(ois_p) * 10000, 1),  # bps
            "ois_curr": round(float(ois_c) * 10000, 1),
            "nominal_prev": round(float(nom_p), 0),
            "nominal_curr": round(float(nom_c), 0),
            "spread_prev": round(float(spread_p) * 10000, 1),
            "spread_curr": round(float(spread_c) * 10000, 1),
        }

    # Total P&L
    total_curr = curr_by_deal["PnL"].sum()
    total_prev = prev_by_deal["PnL"].sum()
    total_delta = total_curr - total_prev

    # Time effect = residual after accounting for other effects
    time_effect = total_delta - new_deal_pnl - matured_deal_pnl - rate_effect - spread_effect

    # Build waterfall steps
    waterfall = [
        {"label": f"Prev NII ({prev_date_run.strftime('%Y-%m-%d')})", "value": round(float(total_prev), 0), "type": "base"},
        {"label": "Time / Roll-down", "value": round(float(time_effect), 0), "type": "effect"},
        {"label": f"New Deals (+{len(new_ids)})", "value": round(float(new_deal_pnl), 0), "type": "effect"},
        {"label": f"Maturing Deals (-{len(matured_ids)})", "value": round(float(matured_deal_pnl), 0), "type": "effect"},
        {"label": "Rate Effect", "value": round(float(rate_effect), 0), "type": "effect"},
        {"label": "Spread Effect", "value": round(float(spread_effect), 0), "type": "effect"},
        {"label": f"Current NII ({date_run.strftime('%Y-%m-%d')})", "value": round(float(total_curr), 0), "type": "total"},
    ]

    # Detail tables
    new_deals_detail = []
    if new_ids:
        nd = curr_by_deal[curr_by_deal["Dealid"].isin(new_ids)]
        for _, row in nd.iterrows():
            new_deals_detail.append({
                "deal_id": str(row.get("Dealid", "")),
                "counterparty": str(row.get("Counterparty", "")),
                "currency": str(row.get("Currency", "")),
                "product": str(row.get("Product", "")),
                "pnl": round(float(row["PnL"]), 0),
                "nominal": round(float(row.get("Nominal", 0)), 0),
            })
    new_deals_detail.sort(key=lambda x: abs(x["pnl"]), reverse=True)

    matured_deals_detail = []
    if matured_ids:
        md = prev_by_deal[prev_by_deal["Dealid"].isin(matured_ids)]
        for _, row in md.iterrows():
            matured_deals_detail.append({
                "deal_id": str(row.get("Dealid", "")),
                "counterparty": str(row.get("Counterparty", "")),
                "currency": str(row.get("Currency", "")),
                "product": str(row.get("Product", "")),
                "pnl_lost": round(-float(row["PnL"]), 0),
                "nominal": round(float(row.get("Nominal", 0)), 0),
            })
    matured_deals_detail.sort(key=lambda x: abs(x["pnl_lost"]), reverse=True)

    return {
        "has_data": True,
        "waterfall": waterfall,
        "by_currency": by_currency,
        "new_deals": new_deals_detail,
        "matured_deals": matured_deals_detail,
        "summary": {
            "prev_nii": round(float(total_prev), 0),
            "curr_nii": round(float(total_curr), 0),
            "delta": round(float(total_delta), 0),
            "time_effect": round(float(time_effect), 0),
            "new_deal_effect": round(float(new_deal_pnl), 0),
            "matured_deal_effect": round(float(matured_deal_pnl), 0),
            "rate_effect": round(float(rate_effect), 0),
            "spread_effect": round(float(spread_effect), 0),
            "n_new": len(new_ids),
            "n_matured": len(matured_ids),
            "n_existing": len(existing_ids),
            "prev_date": prev_date_run.strftime("%Y-%m-%d"),
            "curr_date": date_run.strftime("%Y-%m-%d"),
        },
    }


def _aggregate_deal_pnl(pnl_by_deal: pd.DataFrame) -> pd.DataFrame:
    """Aggregate deal-level P&L across months to annual totals."""
    group_cols = [c for c in ["Dealid", "Counterparty", "Currency", "Product",
                              "Direction", "Périmètre TOTAL"]
                  if c in pnl_by_deal.columns]
    if not group_cols or "Dealid" not in group_cols:
        return pnl_by_deal

    agg = pnl_by_deal.groupby(group_cols).agg(
        PnL=("PnL", "sum"),
        Nominal=("Nominal", "mean"),
    ).reset_index()
    return agg


def _safe_reset(df: pd.DataFrame) -> pd.DataFrame:
    """Reset MultiIndex to flat columns."""
    if df is None or df.empty:
        return pd.DataFrame()
    result = df.copy()
    if isinstance(result.index, pd.MultiIndex):
        result = result.reset_index()
    return result


def _extract_by_ccy(df: pd.DataFrame, indice: str) -> dict:
    """Extract weighted-average value per currency for a given Indice (shock=0)."""
    if df.empty:
        return {}
    rows = df[(df.get("Indice", pd.Series()) == indice) & (df.get("Shock", pd.Series()) == "0")]
    if rows.empty:
        return {}
    if "Deal currency" in rows.columns:
        return rows.groupby("Deal currency")["Value"].mean().to_dict()
    return {}
