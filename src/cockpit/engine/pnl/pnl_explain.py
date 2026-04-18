"""P&L Explain — waterfall decomposition of NII changes between two runs.

Decomposes Δ(Forecast NII) between two engine runs into:
  • New deals     — Σ curr_pnl for deals present only in curr
  • Matured       — −Σ prev_pnl for deals present only in prev
  • Rate effect   — ΔOIS impact on existing deals (held at prev rates)
  • Spread effect — ΔClientRate (RateRef) impact on existing deals
  • Residual      — amortization, mix, forecast-window shrinkage, cross-terms

The decomposition is internally consistent and reconciles by construction:
  total_delta = new + matured + existing_delta
  existing_delta = rate_effect + spread_effect + residual

The rate/spread factors are self-calibrated from the prev run's P&L identity
  prev_pnl_ccy = T_p × spread_p_avg    (where T_p = Σ Nom·days/MM)
so effects are on the same scale as the forecast totals, regardless of how
many days elapsed between runs.
"""
from __future__ import annotations

import logging
from datetime import datetime

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
        curr_pnl_all_s: Current stacked P&L (for rate aggregates per currency).
        prev_pnl_all_s: Previous stacked P&L.
        deals: Unused; retained for call-site compatibility. Classification is
            now set-based (membership in each run), not date-based.
        date_run: Current run date (label only).
        prev_date_run: Previous run date (label only).

    Returns:
        Dict with waterfall data, by-currency breakdown, and deal-level details.
    """
    _ = deals  # unused; retained for call-site compatibility
    if curr_pnl_by_deal is None or curr_pnl_by_deal.empty:
        return {"has_data": False}
    if prev_pnl_by_deal is None or prev_pnl_by_deal.empty:
        return {"has_data": False}

    # Filter to Shock=0 (read-only downstream; no .copy needed)
    curr = curr_pnl_by_deal[curr_pnl_by_deal["Shock"] == "0"] if "Shock" in curr_pnl_by_deal.columns else curr_pnl_by_deal
    prev = prev_pnl_by_deal[prev_pnl_by_deal["Shock"] == "0"] if "Shock" in prev_pnl_by_deal.columns else prev_pnl_by_deal

    # Aggregate to deal-level totals (across months) with string Dealid for matching
    curr_by_deal = _aggregate_deal_pnl(curr)
    prev_by_deal = _aggregate_deal_pnl(prev)
    if "Dealid" in curr_by_deal.columns:
        curr_by_deal = curr_by_deal.assign(Dealid=curr_by_deal["Dealid"].astype(str))
    if "Dealid" in prev_by_deal.columns:
        prev_by_deal = prev_by_deal.assign(Dealid=prev_by_deal["Dealid"].astype(str))

    # Set-based classification: membership in each run is the clean criterion.
    # Date-based reclassification was removed — a deal in both runs IS existing;
    # its ΔP&L belongs in existing_delta (which splits into rate + spread + residual).
    curr_ids = set(curr_by_deal["Dealid"])
    prev_ids = set(prev_by_deal["Dealid"])
    new_ids = curr_ids - prev_ids
    matured_ids = prev_ids - curr_ids
    existing_ids = curr_ids & prev_ids

    # Bucket P&L: new, matured, existing
    new_deal_pnl = float(curr_by_deal[curr_by_deal["Dealid"].isin(new_ids)]["PnL"].sum()) if new_ids else 0.0
    matured_deal_pnl = float(-prev_by_deal[prev_by_deal["Dealid"].isin(matured_ids)]["PnL"].sum()) if matured_ids else 0.0

    existing_prev_pnl = prev_by_deal[prev_by_deal["Dealid"].isin(existing_ids)]
    existing_curr_pnl = curr_by_deal[curr_by_deal["Dealid"].isin(existing_ids)]
    existing_prev_by_ccy = existing_prev_pnl.groupby("Currency")["PnL"].sum().to_dict() if "Currency" in existing_prev_pnl.columns else {}
    existing_curr_by_ccy = existing_curr_pnl.groupby("Currency")["PnL"].sum().to_dict() if "Currency" in existing_curr_pnl.columns else {}

    # Per-currency rate snapshots from pnlAllS (nominal-weighted avg across horizon)
    curr_s = _safe_reset(curr_pnl_all_s)
    prev_s = _safe_reset(prev_pnl_all_s)
    curr_rates = _extract_by_ccy(curr_s, "OISfwd")
    prev_rates = _extract_by_ccy(prev_s, "OISfwd")
    curr_ref = _extract_by_ccy(curr_s, "RateRef")
    prev_ref = _extract_by_ccy(prev_s, "RateRef")

    rate_effect = 0.0
    spread_effect = 0.0
    residual_effect = 0.0
    by_currency = {}

    currencies = sorted(set(existing_prev_by_ccy.keys()) | set(existing_curr_by_ccy.keys())
                        | set(prev_rates.keys()) | set(curr_rates.keys()))

    for ccy in currencies:
        ois_p = float(prev_rates.get(ccy, 0.0))
        ois_c = float(curr_rates.get(ccy, 0.0))
        ref_p = float(prev_ref.get(ccy, 0.0))
        ref_c = float(curr_ref.get(ccy, 0.0))
        spread_p = ois_p - ref_p
        spread_c = ois_c - ref_c

        exist_prev_ccy = float(existing_prev_by_ccy.get(ccy, 0.0))
        exist_curr_ccy = float(existing_curr_by_ccy.get(ccy, 0.0))
        exist_delta_ccy = exist_curr_ccy - exist_prev_ccy

        # Self-calibrated nominal-time factor from the prev P&L identity:
        #   prev_pnl = T_p × spread_p_avg  ⇒  T_p = prev_pnl / spread_p
        # Ensures rate/spread effects scale with forecast P&L, not with
        # elapsed days between runs.
        if abs(spread_p) > 1e-8:
            t_p = exist_prev_ccy / spread_p
        else:
            t_p = 0.0

        # ΔOIS on existing book (client rate held at prev)
        rate_eff_ccy = t_p * (ois_c - ois_p)
        # ΔClientRate on existing book (OIS held at prev). Signed: a lower
        # client rate on assets increases (OIS − Ref) and thus P&L.
        spread_eff_ccy = t_p * (ref_p - ref_c)
        # Residual = amortization, mix, forecast-window shrinkage, cross-term
        residual_ccy = exist_delta_ccy - rate_eff_ccy - spread_eff_ccy

        rate_effect += rate_eff_ccy
        spread_effect += spread_eff_ccy
        residual_effect += residual_ccy

        by_currency[ccy] = {
            "ois_prev": round(ois_p * 10000, 1),
            "ois_curr": round(ois_c * 10000, 1),
            "spread_prev": round(spread_p * 10000, 1),
            "spread_curr": round(spread_c * 10000, 1),
            "existing_prev_pnl": round(exist_prev_ccy, 0),
            "existing_curr_pnl": round(exist_curr_ccy, 0),
            "rate_effect": round(rate_eff_ccy, 0),
            "spread_effect": round(spread_eff_ccy, 0),
            "residual": round(residual_ccy, 0),
        }

    # Total P&L (reconciles by construction: delta = new + matured + rate + spread + residual)
    total_curr = float(curr_by_deal["PnL"].sum())
    total_prev = float(prev_by_deal["PnL"].sum())
    total_delta = total_curr - total_prev

    # Build waterfall steps
    waterfall = [
        {"label": f"Prev NII ({prev_date_run.strftime('%Y-%m-%d')})", "value": round(total_prev, 0), "type": "base"},
        {"label": f"New Deals (+{len(new_ids)})", "value": round(new_deal_pnl, 0), "type": "effect"},
        {"label": f"Maturing Deals (-{len(matured_ids)})", "value": round(matured_deal_pnl, 0), "type": "effect"},
        {"label": "Rate Effect (ΔOIS)", "value": round(rate_effect, 0), "type": "effect"},
        {"label": "Spread Effect (ΔClientRate)", "value": round(spread_effect, 0), "type": "effect"},
        {"label": "Residual (time / mix / amort.)", "value": round(residual_effect, 0), "type": "effect"},
        {"label": f"Current NII ({date_run.strftime('%Y-%m-%d')})", "value": round(total_curr, 0), "type": "total"},
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
            "prev_nii": round(total_prev, 0),
            "curr_nii": round(total_curr, 0),
            "delta": round(total_delta, 0),
            "new_deal_effect": round(new_deal_pnl, 0),
            "matured_deal_effect": round(matured_deal_pnl, 0),
            "rate_effect": round(rate_effect, 0),
            "spread_effect": round(spread_effect, 0),
            "residual_effect": round(residual_effect, 0),
            # Back-compat alias — older renderers may read `time_effect`.
            "time_effect": round(residual_effect, 0),
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
    """Reset MultiIndex to flat columns. Returns input unchanged when already flat."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.index, pd.MultiIndex):
        return df.reset_index()
    return df


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
