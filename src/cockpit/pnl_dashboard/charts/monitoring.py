"""Monitoring chart data builders: ALCO Decision Pack, Data Quality, SNB Reserves, Peer Benchmark, NMD Backtest, Basis Risk."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from cockpit.data.quality import build_quality_report
from cockpit.pnl_dashboard.charts.helpers import safe_float

logger = logging.getLogger(__name__)


def _build_basis_risk(
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
) -> dict:
    """Build basis risk data for the dashboard tab."""
    if deals is None or deals.empty or pnl_by_deal is None or pnl_by_deal.empty:
        return {"has_data": False}
    try:
        from pnl_engine.basis_risk import compute_basis_risk
        # Build approximate matrices from pnl_by_deal summary
        # For the dashboard, we use a simplified approach based on deal-level P&L
        base = pnl_by_deal[pnl_by_deal["Shock"] == "0"] if "Shock" in pnl_by_deal.columns else pnl_by_deal
        if base.empty:
            return {"has_data": False}

        products = deals["Product"].str.strip().values if "Product" in deals.columns else []
        currencies = deals["Currency"].str.strip().str.upper().values if "Currency" in deals.columns else []
        unique_products = sorted(p for p in set(products) if pd.notna(p))
        unique_currencies = sorted(c for c in set(currencies) if pd.notna(c))

        # Pre-convert Amount once for all loops
        amount_numeric = pd.to_numeric(deals["Amount"], errors="coerce").fillna(0) if "Amount" in deals.columns else pd.Series(0, index=deals.index)

        # Compute base NII by product and currency from pnl_by_deal
        by_product = {}
        by_currency = {}
        shocks = ["-50bp", "-25bp", "-10bp", "+0bp", "+10bp", "+25bp", "+50bp"]
        shock_bps = [-50, -25, -10, 0, 10, 25, 50]

        pnl_col = "PnL" if "PnL" in base.columns else "pnl" if "pnl" in base.columns else None
        if pnl_col is None:
            return {"has_data": False}

        for prod in unique_products:
            mask = deals["Product"].str.strip() == prod
            deal_ids = set(deals.loc[mask, "Dealid"].values) if "Dealid" in deals.columns else set()
            prod_pnl = base[base["Dealid"].isin(deal_ids)][pnl_col].sum() if "Dealid" in base.columns and deal_ids else 0
            by_product[prod] = {"base_nii": round(float(prod_pnl), 0)}
            prod_nom = float(amount_numeric[mask].sum())
            for label, bp in zip(shocks, shock_bps):
                by_product[prod][label] = round(prod_nom * bp / 10_000, 0)

        for ccy in unique_currencies:
            mask = deals["Currency"].str.strip().str.upper() == ccy
            deal_ids = set(deals.loc[mask, "Dealid"].values) if "Dealid" in deals.columns else set()
            ccy_pnl = base[base["Dealid"].isin(deal_ids)][pnl_col].sum() if "Dealid" in base.columns and deal_ids else 0
            by_currency[ccy] = {"base_nii": round(float(ccy_pnl), 0)}
            ccy_nom = float(amount_numeric[mask].sum())
            for label, bp in zip(shocks, shock_bps):
                by_currency[ccy][label] = round(ccy_nom * bp / 10_000, 0)

        return {
            "has_data": True,
            "shocks": shocks,
            "by_product": by_product,
            "by_currency": by_currency,
        }
    except Exception as e:
        logger.warning("Could not compute basis risk: %s", e)
        return {"has_data": False}


def _build_snb_reserves(
    deals: Optional[pd.DataFrame] = None,
    ois_rate: float = 0.0,
    limits: Optional[pd.DataFrame] = None,
) -> dict:
    """Build SNB reserve compliance data for the dashboard tab."""
    if deals is None or deals.empty:
        return {"has_data": False}
    try:
        from pnl_engine.snb_reserves import compute_snb_reserves

        # Extract HQLA and Tier1 from limits if available
        hqla = 0.0
        tier1 = 0.0
        if limits is not None and not limits.empty and "metric" in limits.columns:
            hqla_rows = limits[limits["metric"].str.strip() == "hqla"]
            if not hqla_rows.empty:
                hqla = safe_float(hqla_rows.iloc[0].get("limit_value", 0))
            t1_rows = limits[limits["metric"].str.strip() == "tier1_capital"]
            if not t1_rows.empty:
                tier1 = safe_float(t1_rows.iloc[0].get("limit_value", 0))

        result = compute_snb_reserves(deals, ois_rate=ois_rate, hqla_amount=hqla, tier1_capital=tier1)
        if not result.get("has_data"):
            return result

        # Add template-compatible aliases
        result["reserve_requirement"] = result.get("net_requirement", 0)
        result["eligible_hqla"] = result.get("hqla_amount", 0)
        result["opportunity_cost"] = result.get("opportunity_cost_annual", 0)
        result["total_sight_liabilities"] = result.get("sight_liabilities", 0)

        # Build by-product breakdown for template table
        by_product = []
        if deals is not None and "Product" in deals.columns and "Direction" in deals.columns:
            from pnl_engine.config import LIABILITY_DIRECTIONS
            sight_mask = deals["Direction"].str.strip().str.upper().isin(LIABILITY_DIRECTIONS)
            if "Currency" in deals.columns:
                sight_mask &= deals["Currency"].str.strip().str.upper() == "CHF"
            sight_deals = deals[sight_mask]
            if not sight_deals.empty and "Amount" in sight_deals.columns:
                for prod, grp in sight_deals.groupby(sight_deals["Product"].str.strip()):
                    balance = float(pd.to_numeric(grp["Amount"], errors="coerce").fillna(0).sum())
                    by_product.append({
                        "product": prod,
                        "balance": round(balance, 0),
                        "reserve": round(balance * 0.025, 0),
                    })
        result["by_product"] = by_product

        return result
    except Exception as e:
        logger.warning("Could not compute SNB reserves: %s", e)
        return {"has_data": False}


def _build_peer_benchmark(result: dict) -> dict:
    """Build peer benchmark comparison from computed results."""
    try:
        from cockpit.integrations.peer_benchmark import compute_peer_comparison

        bank_metrics = {}
        eve = result.get("eve", {})
        if eve.get("has_data"):
            outlier = eve.get("outlier_test")
            if outlier:
                bank_metrics["delta_eve_pct_tier1"] = outlier.get("worst_pct", 0)

        nii_risk = result.get("nii_at_risk", {})
        if nii_risk.get("has_data"):
            # Use tornado data (list of dicts with "delta") for worst NII sensitivity
            tornado = nii_risk.get("tornado", [])
            base_total = nii_risk.get("base_total", 0)
            if tornado and base_total:
                worst_delta = min((t.get("delta", 0) for t in tornado if isinstance(t, dict)), default=0)
                bank_metrics["nii_sensitivity_pct"] = worst_delta / abs(base_total) * 100 if base_total else 0

        if not bank_metrics:
            return {"has_data": False}

        return compute_peer_comparison(bank_metrics)
    except Exception as e:
        logger.warning("Could not compute peer benchmark: %s", e)
        return {"has_data": False}


def _build_nmd_backtest(
    deals: Optional[pd.DataFrame] = None,
    nmd_profiles: Optional[pd.DataFrame] = None,
) -> dict:
    """Build NMD backtest data (placeholder — needs actual_balances input)."""
    # NMD backtest requires historical balance data which isn't in the standard pipeline.
    # For now, return a structure indicating the feature exists but needs data.
    if deals is None or nmd_profiles is None or nmd_profiles.empty:
        return {"has_data": False, "message": "Requires actual_balances history"}
    return {"has_data": False, "message": "Provide actual_balances.xlsx for NMD back-test"}


def _build_data_quality(
    date_run: Optional[datetime],
    deals: Optional[pd.DataFrame] = None,
    echeancier: Optional[pd.DataFrame] = None,
    ois_curves: Optional[pd.DataFrame] = None,
) -> dict:
    """Build data quality report for the dashboard tab."""
    if date_run is None:
        return {"has_data": False}
    report = build_quality_report(date_run, deals, echeancier, ois_curves)
    result = report.to_dict()
    result["has_data"] = True
    return result


def _build_alco_decision_pack(result: dict) -> dict:
    """ALCO Decision Pack -- structured summary for print/PDF export."""
    alco = result.get("alco", {})
    if not alco.get("has_data"):
        return {"has_data": False, "sections": [], "decisions": [], "executive_summary": []}

    metrics = alco.get("metrics", [])

    # --- Executive summary bullets ---
    exec_summary = []
    for m in metrics:
        val = m.get("value", 0)
        status = m.get("status", "neutral")
        metric_name = m.get("metric", "")
        display = m.get("display", "")
        unit = m.get("unit", "")

        if status == "red":
            if display:
                exec_summary.append({"text": f"{metric_name}: {display} \u2014 ACTION REQUIRED", "severity": "critical"})
            elif unit:
                exec_summary.append({"text": f"{metric_name}: {val:,.2f}{unit} \u2014 ACTION REQUIRED", "severity": "critical"})
            else:
                exec_summary.append({"text": f"{metric_name}: {val:,.0f} \u2014 ACTION REQUIRED", "severity": "critical"})
        elif status == "yellow":
            if display:
                exec_summary.append({"text": f"{metric_name}: {display} \u2014 Monitor closely", "severity": "warning"})
            elif unit:
                exec_summary.append({"text": f"{metric_name}: {val:,.2f}{unit} \u2014 Monitor closely", "severity": "warning"})
            else:
                exec_summary.append({"text": f"{metric_name}: {val:,.0f} \u2014 Monitor closely", "severity": "warning"})

    # --- Decisions required ---
    decisions = []
    for m in metrics:
        if "sensitivity" in m["metric"].lower() and m.get("utilization") and m["utilization"] > 80:
            decisions.append({
                "topic": "NII Sensitivity",
                "description": f"Limit utilization at {m['utilization']:.1f}%. Consider reducing duration or adding hedges.",
                "priority": "high" if m["utilization"] > 90 else "medium",
            })
        if "hedge" in m["metric"].lower() and m.get("status") == "red":
            decisions.append({
                "topic": "Hedge Effectiveness",
                "description": f"{m.get('display', 'Failing pairs detected')}. Review hedge designations.",
                "priority": "high",
            })
        if "liquidity" in m["metric"].lower() and m.get("status") == "red":
            decisions.append({
                "topic": "Liquidity",
                "description": f"Net 30d position: {m['value']:,.0f}. Arrange contingent funding.",
                "priority": "critical",
            })
        if "alm margin" in m["metric"].lower() and m.get("status") == "red":
            decisions.append({
                "topic": "FTP / ALM Margin",
                "description": f"ALM margin negative ({m['value']:,.0f}). Review transfer pricing.",
                "priority": "high",
            })

    # Check scenario risk
    scenario_studio = result.get("scenario_studio", {})
    if scenario_studio.get("has_data"):
        ranking = scenario_studio.get("ranking", [])
        for r in ranking[:2]:
            if r.get("combined_impact", 0) < 0 and abs(r["combined_impact"]) > abs(scenario_studio.get("base_nii", 1)) * 0.10:
                decisions.append({
                    "topic": f"Scenario Risk ({r['scenario']})",
                    "description": f"Combined NII+EVE impact: {r['combined_impact']:,.0f}.",
                    "priority": "high",
                })

    sections = [
        {"title": "Risk Overview", "source": "alco_metrics"},
        {"title": "Scenario Analysis", "source": "scenario_studio"},
        {"title": "Hedge Coverage", "source": "hedge_strategy"},
        {"title": "Limit Utilization", "source": "limits"},
        {"title": "Alerts", "source": "pnl_alerts"},
    ]

    return {
        "has_data": True,
        "executive_summary": exec_summary,
        "decisions": decisions,
        "sections": sections,
        "n_critical": sum(1 for d in decisions if d["priority"] == "critical"),
        "n_high": sum(1 for d in decisions if d["priority"] == "high"),
        "n_medium": sum(1 for d in decisions if d["priority"] == "medium"),
    }
