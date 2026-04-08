"""Scenario chart data builders: Risk Cube, Deposit Behavior, Scenario Studio, Hedge Strategy."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from cockpit.pnl_dashboard.charts.constants import (
    CURRENCY_COLORS,
    PRODUCT_COLORS,
)

logger = logging.getLogger(__name__)


def _build_risk_cube(
    df: pd.DataFrame,
    pnl_by_deal: Optional[pd.DataFrame] = None,
) -> dict:
    """Cross-dimensional risk analytics: Product x Currency, Counterparty x Product, Direction x Currency."""
    source = None
    if pnl_by_deal is not None and not pnl_by_deal.empty:
        source = pnl_by_deal.copy()
        if "Shock" in source.columns:
            source = source[source["Shock"] == "0"]
    elif not df.empty:
        source = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")].copy()

    if source is None or source.empty:
        return {"has_data": False, "product_currency": {}, "counterparty_product": {},
                "direction_currency": {}}

    # Standardize column names
    ccy_col = None
    for c in ["Currency", "Deal currency"]:
        if c in source.columns:
            ccy_col = c
            break
    prod_col = None
    for c in ["Product", "Product2BuyBack"]:
        if c in source.columns:
            prod_col = c
            break
    pnl_col = "PnL" if "PnL" in source.columns else "Value" if "Value" in source.columns else None

    if pnl_col is None:
        return {"has_data": False, "product_currency": {}, "counterparty_product": {},
                "direction_currency": {}}

    # 1. Product x Currency heatmap
    product_currency = {"products": [], "currencies": [], "matrix": [], "totals_by_prod": {}, "totals_by_ccy": {}}
    if prod_col and ccy_col:
        pivot = source.groupby([prod_col, ccy_col])[pnl_col].sum().unstack(fill_value=0)
        products = sorted(pivot.index.tolist())
        currencies = sorted(pivot.columns.tolist())
        matrix = []
        for prod in products:
            row = []
            for ccy in currencies:
                val = float(pivot.loc[prod, ccy]) if ccy in pivot.columns else 0
                row.append(round(val, 0))
            matrix.append(row)
        product_currency = {
            "products": [str(p) for p in products],
            "currencies": [str(c) for c in currencies],
            "matrix": matrix,
            "totals_by_prod": {str(p): round(float(pivot.loc[p].sum()), 0) for p in products},
            "totals_by_ccy": {str(c): round(float(pivot[c].sum()), 0) for c in currencies},
        }

    # 2. Counterparty x Product (top 10 counterparties)
    counterparty_product = {"counterparties": [], "products": [], "matrix": []}
    cpty_col = "Counterparty" if "Counterparty" in source.columns else None
    if cpty_col and prod_col:
        # Top 10 counterparties by absolute P&L
        cpty_totals = source.groupby(cpty_col)[pnl_col].sum().abs().sort_values(ascending=False)
        top_cptys = cpty_totals.head(10).index.tolist()
        filtered = source[source[cpty_col].isin(top_cptys)]
        if not filtered.empty:
            pivot2 = filtered.groupby([cpty_col, prod_col])[pnl_col].sum().unstack(fill_value=0)
            cptys = [str(c) for c in top_cptys if c in pivot2.index]
            prods2 = sorted([str(p) for p in pivot2.columns.tolist()])
            matrix2 = []
            for cp in cptys:
                row = []
                for p in prods2:
                    val = float(pivot2.loc[cp, p]) if p in pivot2.columns else 0
                    row.append(round(val, 0))
                matrix2.append(row)
            counterparty_product = {
                "counterparties": cptys,
                "products": prods2,
                "matrix": matrix2,
            }

    # 3. Direction x Currency
    direction_currency = {"directions": [], "currencies": [], "matrix": []}
    dir_col = "Direction" if "Direction" in source.columns else None
    if dir_col and ccy_col:
        pivot3 = source.groupby([dir_col, ccy_col])[pnl_col].sum().unstack(fill_value=0)
        dirs = sorted(pivot3.index.tolist())
        ccys3 = sorted(pivot3.columns.tolist())
        matrix3 = []
        for d in dirs:
            row = [round(float(pivot3.loc[d, c]), 0) if c in pivot3.columns else 0 for c in ccys3]
            matrix3.append(row)
        direction_currency = {
            "directions": [str(d) for d in dirs],
            "currencies": [str(c) for c in ccys3],
            "matrix": matrix3,
        }

    return {
        "has_data": True,
        "product_currency": product_currency,
        "counterparty_product": counterparty_product,
        "direction_currency": direction_currency,
    }


def _build_deposit_behavior(
    deals: Optional[pd.DataFrame] = None,
    nmd_profiles: Optional[pd.DataFrame] = None,
    df: Optional[pd.DataFrame] = None,
) -> dict:
    """Deposit behavior intelligence: volume trends, beta validation, concentration."""
    if deals is None or deals.empty:
        return {"has_data": False, "volume_by_ccy": {}, "volume_by_product": {},
                "beta_analysis": {}, "concentration": {}, "kpis": {}}

    d = deals.copy()

    # Filter to deposits (Direction = D or S)
    dir_col = "Direction" if "Direction" in d.columns else None
    if dir_col:
        deposits = d[d[dir_col].isin(["D", "S"])].copy()
    else:
        return {"has_data": False, "volume_by_ccy": {}, "volume_by_product": {},
                "beta_analysis": {}, "concentration": {}, "kpis": {}}

    if deposits.empty:
        return {"has_data": False, "volume_by_ccy": {}, "volume_by_product": {},
                "beta_analysis": {}, "concentration": {}, "kpis": {}}

    # Nominal
    nom_col = "Amount" if "Amount" in deposits.columns else "Nominal" if "Nominal" in deposits.columns else None
    if nom_col:
        deposits["_nom"] = pd.to_numeric(deposits[nom_col], errors="coerce").fillna(0).abs()
    else:
        deposits["_nom"] = 0.0

    ccy_col = "Currency" if "Currency" in deposits.columns else "Deal currency" if "Deal currency" in deposits.columns else None
    prod_col = "Product" if "Product" in deposits.columns else "Product2BuyBack" if "Product2BuyBack" in deposits.columns else None

    total_deposits = float(deposits["_nom"].sum())

    # Volume by currency
    volume_by_ccy = {}
    if ccy_col:
        for ccy in sorted(deposits[ccy_col].dropna().unique()):
            subset = deposits[deposits[ccy_col] == ccy]
            vol = float(subset["_nom"].sum())
            volume_by_ccy[str(ccy)] = {
                "volume": round(vol, 0),
                "pct": round(vol / total_deposits * 100, 1) if total_deposits > 0 else 0,
                "count": len(subset),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # Volume by product
    volume_by_product = {}
    if prod_col:
        for prod in sorted(deposits[prod_col].dropna().unique()):
            subset = deposits[deposits[prod_col] == prod]
            vol = float(subset["_nom"].sum())
            volume_by_product[str(prod)] = {
                "volume": round(vol, 0),
                "pct": round(vol / total_deposits * 100, 1) if total_deposits > 0 else 0,
                "count": len(subset),
                "color": PRODUCT_COLORS.get(str(prod), "#8b949e"),
            }

    # Beta analysis: compare modeled beta from NMD profiles with implied rate passthrough
    beta_analysis = {"by_tier": {}, "by_currency": {}}
    if nmd_profiles is not None and not nmd_profiles.empty:
        profiles = nmd_profiles.copy()
        # Summarize NMD profiles
        if "tier" in profiles.columns:
            for tier in sorted(profiles["tier"].unique()):
                t_data = profiles[profiles["tier"] == tier]
                beta_col = "deposit_beta" if "deposit_beta" in t_data.columns else None
                decay_col = "decay_rate" if "decay_rate" in t_data.columns else None
                bm_col = "behavioral_maturity_years" if "behavioral_maturity_years" in t_data.columns else \
                         "behavioral_maturity" if "behavioral_maturity" in t_data.columns else None
                beta_analysis["by_tier"][str(tier)] = {
                    "count": len(t_data),
                    "avg_beta": round(float(t_data[beta_col].mean()), 3) if beta_col else None,
                    "avg_decay": round(float(t_data[decay_col].mean()), 4) if decay_col else None,
                    "avg_bm_years": round(float(t_data[bm_col].mean()), 1) if bm_col else None,
                }

        # By currency
        if "currency" in profiles.columns:
            beta_col = "deposit_beta" if "deposit_beta" in profiles.columns else None
            for ccy in sorted(profiles["currency"].unique()):
                c_data = profiles[profiles["currency"] == ccy]
                beta_analysis["by_currency"][str(ccy)] = {
                    "count": len(c_data),
                    "avg_beta": round(float(c_data[beta_col].mean()), 3) if beta_col else None,
                    "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
                }

    # Implied beta from OIS vs deposit rates
    implied_beta = {}
    if df is not None and not df.empty and ccy_col:
        ois_rows = df[(df["Indice"] == "OISfwd") & (df["Shock"] == "0")]
        ref_rows = df[(df["Indice"] == "RateRef") & (df["Shock"] == "0")]
        if not ois_rows.empty and not ref_rows.empty:
            # Filter to deposit direction
            dep_ref = ref_rows[ref_rows["Direction"].isin(["D", "S"])] if "Direction" in ref_rows.columns else ref_rows
            for ccy_val in dep_ref["Deal currency"].unique() if "Deal currency" in dep_ref.columns else []:
                _ois_s = ois_rows[ois_rows["Deal currency"] == ccy_val]["Value"] if "Deal currency" in ois_rows.columns else pd.Series(dtype=float)
                ccy_ois = float(_ois_s.mean()) if not _ois_s.empty and pd.notna(_ois_s.mean()) else 0
                _ref_s = dep_ref[dep_ref["Deal currency"] == ccy_val]["Value"]
                ccy_ref = float(_ref_s.mean()) if not _ref_s.empty and pd.notna(_ref_s.mean()) else 0
                # Implied beta = deposit_rate / OIS_rate (simplified)
                if ccy_ois != 0:
                    implied = ccy_ref / ccy_ois
                    implied_beta[str(ccy_val)] = round(float(implied), 3)
    beta_analysis["implied_beta"] = implied_beta

    # Deposit concentration: top 10 depositors
    concentration = {"top_10": [], "hhi": 0}
    cpty_col = "Counterparty" if "Counterparty" in deposits.columns else None
    if cpty_col:
        by_cpty = deposits.groupby(cpty_col)["_nom"].sum().sort_values(ascending=False)
        total = by_cpty.sum()
        top10 = by_cpty.head(10)
        concentration["top_10"] = [
            {
                "counterparty": str(cp),
                "volume": round(float(vol), 0),
                "pct": round(float(vol) / total * 100, 1) if total > 0 else 0,
            }
            for cp, vol in top10.items()
        ]
        if total > 0:
            shares = (by_cpty / total * 100)
            concentration["hhi"] = round(float((shares ** 2).sum()), 0)
        concentration["top10_pct"] = round(float(top10.sum()) / total * 100, 1) if total > 0 else 0

    # KPIs
    avg_rate = 0
    rate_col = None
    for c in ["RateRef", "EqOisRate", "Clientrate"]:
        if c in deposits.columns:
            rate_col = c
            break
    if rate_col:
        deposits["_rate"] = pd.to_numeric(deposits[rate_col], errors="coerce").fillna(0)
        avg_rate = float((deposits["_rate"] * deposits["_nom"]).sum()) / total_deposits if total_deposits > 0 else 0

    kpis = {
        "total_deposits": round(total_deposits, 0),
        "deal_count": len(deposits),
        "avg_rate_pct": round(avg_rate * 100, 4),
        "n_currencies": len(volume_by_ccy),
        "hhi": concentration.get("hhi", 0),
    }

    return {
        "has_data": True,
        "volume_by_ccy": volume_by_ccy,
        "volume_by_product": volume_by_product,
        "beta_analysis": beta_analysis,
        "concentration": concentration,
        "kpis": kpis,
    }


def _build_scenario_studio(
    df: pd.DataFrame,
    scenarios_data: Optional[pd.DataFrame] = None,
    eve_scenarios: Optional[pd.DataFrame] = None,
    nii_at_risk: Optional[dict] = None,
    eve_data: Optional[dict] = None,
) -> dict:
    """Scenario Studio -- side-by-side scenario comparison with combined NII + EVE view.

    Provides:
    - Combined NII + ΔEVE per scenario (dual-impact ranking)
    - Scenario ranking table (worst-to-best)
    - Probability-weighted expected NII
    - Decision matrix: scenario x action recommendation
    """
    empty: dict = {
        "has_data": False, "combined": [], "ranking": [],
        "probability_weighted": {}, "decision_matrix": [],
    }

    # Need at least NII scenario data
    nii_risk = nii_at_risk or {}
    if not nii_risk.get("has_data"):
        return empty

    tornado = nii_risk.get("tornado", [])
    base_nii = nii_risk.get("base_total", 0)
    heatmap_nii = nii_risk.get("heatmap", [])
    scenarios = nii_risk.get("scenarios", [])

    if not tornado:
        return empty

    # Build NII lookup: scenario -> {nii, delta}
    nii_lookup = {}
    for t in tornado:
        nii_lookup[t["scenario"]] = {"nii": t["nii"], "delta": t["delta"]}

    # Build EVE lookup: scenario -> {delta_eve}
    eve_lookup = {}
    eve_sc = (eve_data or {}).get("scenarios", {})
    if eve_sc:
        for row in eve_sc.get("heatmap", []):
            sc = row.get("scenario", "")
            eve_lookup[sc] = {"delta_eve": row.get("total", 0)}

    # Scenario probabilities (uniform by default, with slight weighting for parallel)
    scenario_probs = {}
    for sc in scenarios:
        if "parallel" in str(sc).lower():
            scenario_probs[sc] = 0.20
        elif "short" in str(sc).lower():
            scenario_probs[sc] = 0.15
        else:
            scenario_probs[sc] = 0.15
    # Normalize
    total_prob = sum(scenario_probs.values())
    if total_prob > 0:
        scenario_probs = {k: round(v / total_prob, 4) for k, v in scenario_probs.items()}

    # Combined table: scenario -> NII, ΔNII, ΔEVE, combined impact
    combined = []
    for sc in scenarios:
        nii_info = nii_lookup.get(sc, {"nii": 0, "delta": 0})
        eve_info = eve_lookup.get(sc, {"delta_eve": 0})
        delta_nii = nii_info["delta"]
        delta_eve = eve_info["delta_eve"]
        combined_impact = delta_nii + delta_eve
        prob = scenario_probs.get(sc, 0)

        # Per-currency NII from heatmap
        ccy_nii = {}
        for hm_row in heatmap_nii:
            if hm_row.get("scenario") == sc:
                for k, v in hm_row.items():
                    if k not in ("scenario", "total"):
                        ccy_nii[k] = v
                break

        combined.append({
            "scenario": sc,
            "nii": round(nii_info["nii"], 0),
            "delta_nii": round(delta_nii, 0),
            "delta_eve": round(delta_eve, 0),
            "combined_impact": round(combined_impact, 0),
            "probability": prob,
            "weighted_nii": round(nii_info["nii"] * prob, 0),
            "ccy_nii": ccy_nii,
        })

    # Ranking: sort by combined impact (worst first)
    ranking = sorted(combined, key=lambda x: x["combined_impact"])

    # Probability-weighted expected NII
    pw_nii = sum(c["weighted_nii"] for c in combined)
    pw_delta = pw_nii - base_nii * sum(scenario_probs.values()) if base_nii else 0
    probability_weighted = {
        "expected_nii": round(pw_nii, 0),
        "expected_delta": round(pw_delta, 0),
        "base_nii": round(base_nii, 0),
    }

    # Decision matrix: severity classification per scenario
    decision_matrix = []
    for c in ranking:
        delta = c["delta_nii"]
        severity = "low"
        action = "Monitor"
        if abs(delta) > abs(base_nii) * 0.15:
            severity = "critical"
            action = "Immediate hedge action required"
        elif abs(delta) > abs(base_nii) * 0.10:
            severity = "high"
            action = "Review hedge strategy"
        elif abs(delta) > abs(base_nii) * 0.05:
            severity = "medium"
            action = "Increase monitoring frequency"

        decision_matrix.append({
            "scenario": c["scenario"],
            "delta_nii": c["delta_nii"],
            "delta_eve": c["delta_eve"],
            "severity": severity,
            "action": action,
        })

    # Reverse stress test: find shock level that breaches NII limit
    reverse_stress = None
    try:
        from pnl_engine.reverse_stress import reverse_stress_nii, reverse_stress_eve
        # Estimate sensitivity per bp from tornado data
        if len(tornado) >= 2 and base_nii != 0:
            # Use parallel_up scenario if available
            up = next((t for t in tornado if "up" in t["scenario"].lower() and "parallel" in t["scenario"].lower()), None)
            if up and up["delta"] != 0:
                sens_per_bp = up["delta"] / 200.0  # parallel_up is typically 200bp
                nii_limit = base_nii * 0.85  # 15% loss threshold
                rs_nii = reverse_stress_nii(base_nii, sens_per_bp, nii_limit)
                reverse_stress = {"nii": rs_nii}

                # EVE reverse stress if DV01 available
                eve_d = eve_data or {}
                if eve_d.get("dv01") and eve_d.get("has_data"):
                    outlier = eve_d.get("outlier_test")
                    tier1 = outlier["tier1_capital"] if outlier else 0
                    dv01 = eve_d["dv01"].get("total_dv01", 0)
                    if tier1 > 0 and dv01 != 0:
                        rs_eve = reverse_stress_eve(eve_d["total_eve"], tier1, dv01)
                        reverse_stress["eve"] = rs_eve
    except Exception as e:
        logger.warning("Reverse stress test failed: %s", e)

    return {
        "has_data": True,
        "combined": combined,
        "ranking": ranking,
        "probability_weighted": probability_weighted,
        "decision_matrix": decision_matrix,
        "base_nii": round(base_nii, 0),
        "has_eve": bool(eve_lookup),
        "reverse_stress": reverse_stress,
    }


def _build_hedge_strategy(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
    hedge_pairs: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    sensitivity: Optional[dict] = None,
    nii_at_risk: Optional[dict] = None,
) -> dict:
    """Hedge Strategy Optimizer -- hedge coverage, naked exposure, cost, roll calendar."""
    empty: dict = {
        "has_data": False, "coverage": [], "naked_exposure": [],
        "hedge_cost": {}, "roll_calendar": [], "kpis": {},
    }

    if deals is None or deals.empty:
        return empty

    dir_col = "Direction" if "Direction" in deals.columns else None
    prod_col = "Product" if "Product" in deals.columns else None
    ccy_col = "Deal currency" if "Deal currency" in deals.columns else ("Currency" if "Currency" in deals.columns else None)
    nom_col = None
    for c in ["NominalResiduel", "Nominal", "NominalInit"]:
        if c in deals.columns:
            nom_col = c
            break

    if not ccy_col or not nom_col:
        return empty

    deals = deals.copy()
    deals["_nom"] = pd.to_numeric(deals[nom_col], errors="coerce").fillna(0).abs()

    # Classify: hedging instruments = Direction=S or IRS/swap products
    hedge_mask = pd.Series(False, index=deals.index)
    if dir_col:
        hedge_mask |= deals[dir_col].isin(["S"])
    if prod_col:
        hedge_mask |= deals[prod_col].str.contains(r"(?i)irs|swap", na=False)

    hedging = deals[hedge_mask]
    non_hedging = deals[~hedge_mask]

    if hedging.empty and non_hedging.empty:
        return empty

    # --- Coverage by currency ---
    coverage = []
    currencies = sorted(deals[ccy_col].unique())
    total_hedged_nom = 0
    total_all_nom = 0

    for ccy in currencies:
        ccy_hedge = hedging[hedging[ccy_col] == ccy]["_nom"].sum()
        ccy_non_hedge = non_hedging[non_hedging[ccy_col] == ccy]["_nom"].sum()
        ccy_total = ccy_hedge + ccy_non_hedge
        ratio = ccy_hedge / ccy_total if ccy_total > 0 else 0
        total_hedged_nom += ccy_hedge
        total_all_nom += ccy_total

        coverage.append({
            "currency": str(ccy),
            "hedged_notional": round(float(ccy_hedge), 0),
            "total_notional": round(float(ccy_total), 0),
            "hedge_ratio": round(float(ratio), 4),
            "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
        })

    overall_ratio = total_hedged_nom / total_all_nom if total_all_nom > 0 else 0

    # --- Naked exposure (unhedged sensitivity) ---
    naked_exposure = []
    sens = sensitivity or {}
    if sens.get("shocks"):
        for item in sens.get("shocks", []):
            ccy = item.get("currency", "")
            cov = next((c for c in coverage if c["currency"] == ccy), None)
            hr = cov["hedge_ratio"] if cov else 0
            delta = item.get("delta_50", 0)
            naked_exposure.append({
                "currency": ccy,
                "total_delta": round(delta, 0),
                "hedged_delta": round(delta * hr, 0),
                "naked_delta": round(delta * (1 - hr), 0),
                "hedge_ratio": round(hr, 4),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            })

    # --- Hedge cost (P&L from hedging instruments) ---
    hedge_cost: dict = {"total": 0, "by_currency": {}}
    if pnl_by_deal is not None and not pnl_by_deal.empty and "Dealid" in pnl_by_deal.columns:
        hedge_pnl = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy() if "Shock" in pnl_by_deal.columns else pnl_by_deal.copy()
        hedge_deal_ids = set(hedging["Dealid"].astype(str).unique()) if "Dealid" in hedging.columns else set()
        if hedge_deal_ids:
            hedge_pnl_matched = hedge_pnl[hedge_pnl["Dealid"].astype(str).isin(hedge_deal_ids)]
            pnl_col = "PnL" if "PnL" in hedge_pnl_matched.columns else "Value"
            if pnl_col in hedge_pnl_matched.columns:
                total_hc = float(hedge_pnl_matched[pnl_col].sum())
                hedge_cost["total"] = round(total_hc, 0)
                if ccy_col in hedge_pnl_matched.columns:
                    for ccy in currencies:
                        ccy_hc = float(hedge_pnl_matched[hedge_pnl_matched[ccy_col] == ccy][pnl_col].sum())
                        hedge_cost["by_currency"][str(ccy)] = round(ccy_hc, 0)

    # --- Roll calendar (upcoming hedge maturities) ---
    roll_calendar = []
    mat_col = None
    for c in ["Maturity", "MaturityDate", "EndDate"]:
        if c in hedging.columns:
            mat_col = c
            break

    if mat_col and not hedging.empty:
        hedging_cal = hedging.copy()
        hedging_cal["_mat"] = pd.to_datetime(hedging_cal[mat_col], errors="coerce")
        hedging_cal = hedging_cal.dropna(subset=["_mat"]).sort_values("_mat")
        now = pd.Timestamp.now()
        upcoming = hedging_cal[hedging_cal["_mat"] <= now + pd.DateOffset(months=12)]

        for _, row in upcoming.head(20).iterrows():
            deal_id = str(row.get("Dealid", ""))
            roll_calendar.append({
                "deal_id": deal_id,
                "currency": str(row.get(ccy_col, "")),
                "product": str(row.get(prod_col, "")) if prod_col else "",
                "notional": round(float(row["_nom"]), 0),
                "maturity": row["_mat"].strftime("%Y-%m-%d"),
                "days_to_maturity": max((row["_mat"] - now).days, 0),
            })

    # --- KPIs ---
    kpis = {
        "overall_hedge_ratio": round(float(overall_ratio), 4),
        "total_hedged_notional": round(float(total_hedged_nom), 0),
        "total_notional": round(float(total_all_nom), 0),
        "hedge_instrument_count": len(hedging),
        "hedge_cost_total": hedge_cost.get("total", 0),
        "next_roll_days": roll_calendar[0]["days_to_maturity"] if roll_calendar else None,
    }

    return {
        "has_data": True,
        "coverage": coverage,
        "naked_exposure": naked_exposure,
        "hedge_cost": hedge_cost,
        "roll_calendar": roll_calendar,
        "kpis": kpis,
    }
