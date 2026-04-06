"""Profitability chart data builders: Hedge Effectiveness, NII-at-Risk, Deal Explorer, Fixed/Float, NIM."""
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
from cockpit.pnl_dashboard.charts.helpers import _filter_total, _month_labels

logger = logging.getLogger(__name__)


def _build_hedge_effectiveness(
    df: pd.DataFrame,
    hedge_pairs: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    scenarios_data: Optional[pd.DataFrame] = None,
) -> dict:
    """Hedge effectiveness per pair.

    Uses pnl_by_deal (deal-level summary) when available, since the aggregated
    pnlAllS drops Dealid during pivot. Falls back to df if it has Dealid.
    """
    if hedge_pairs is None or hedge_pairs.empty:
        return {"has_data": False, "pairs": [], "summary": {"pass": 0, "fail": 0, "total": 0}}

    # Pick the best source for deal-level PnL
    source = None
    pnl_col = "Value"
    dealid_col = "Dealid"
    month_col = "Month"

    if pnl_by_deal is not None and not pnl_by_deal.empty and "Dealid" in pnl_by_deal.columns:
        source = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy()
        pnl_col = "PnL"
    elif not df.empty and "Dealid" in df.columns:
        source = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")].copy()
    else:
        return {"has_data": False, "pairs": [], "summary": {"pass": 0, "fail": 0, "total": 0}}

    pnl = source
    pairs = []
    n_pass = 0
    n_fail = 0

    for _, pair_row in hedge_pairs.iterrows():
        pair_id = pair_row.get("pair_id", "")
        pair_name = pair_row.get("pair_name", f"Pair {pair_id}")
        hedge_type = pair_row.get("hedge_type", "cash_flow")
        ias_standard = pair_row.get("ias_standard", "IFRS9")

        # Parse deal IDs
        hedged_ids = _parse_deal_ids(pair_row.get("hedged_item_deal_ids", ""))
        instrument_ids = _parse_deal_ids(pair_row.get("hedging_instrument_deal_ids", ""))

        # Extract monthly PnL for each side
        hedged_pnl = pnl[pnl["Dealid"].isin(hedged_ids)].groupby("Month")[pnl_col].sum()
        instrument_pnl = pnl[pnl["Dealid"].isin(instrument_ids)].groupby("Month")[pnl_col].sum()

        cum_hedged = hedged_pnl.sum()
        cum_instrument = instrument_pnl.sum()

        # Dollar-offset ratio
        dollar_offset = (cum_instrument / cum_hedged) if abs(cum_hedged) > 0 else 0.0

        # R-squared (simple)
        r_squared = 0.0
        common_months = sorted(set(hedged_pnl.index) & set(instrument_pnl.index))
        if len(common_months) >= 3:
            x = np.array([hedged_pnl.get(m, 0) for m in common_months])
            y = np.array([instrument_pnl.get(m, 0) for m in common_months])
            if np.std(x) > 0 and np.std(y) > 0:
                corr = np.corrcoef(x, y)[0, 1]
                r_squared = float(corr ** 2)

        # Pass/fail
        if ias_standard == "IAS39":
            passed = -1.25 <= dollar_offset <= -0.80
        else:  # IFRS9 -- economic relationship
            passed = r_squared >= 0.80

        if passed:
            n_pass += 1
        else:
            n_fail += 1

        pairs.append({
            "pair_id": str(pair_id),
            "pair_name": str(pair_name),
            "hedge_type": str(hedge_type),
            "ias_standard": str(ias_standard),
            "dollar_offset": round(float(dollar_offset), 4),
            "r_squared": round(float(r_squared), 4),
            "status": "pass" if passed else "fail",
            "hedged_pnl": round(float(cum_hedged), 0),
            "instrument_pnl": round(float(cum_instrument), 0),
        })

    # --- Scenario cross-reference: hedge effectiveness under stress ---
    scenario_xref = []
    if scenarios_data is not None and isinstance(scenarios_data, pd.DataFrame) and not scenarios_data.empty:
        sc_df = scenarios_data.copy()
        if isinstance(sc_df.index, pd.MultiIndex):
            sc_df = sc_df.reset_index()
        sc_pnl = sc_df[sc_df["Indice"] == "PnL"] if "Indice" in sc_df.columns else sc_df
        if "Shock" in sc_pnl.columns and "Dealid" in sc_pnl.columns:
            scenarios_list = sorted(sc_pnl["Shock"].unique())
            for pair_info in pairs:
                pair_row_match = hedge_pairs[
                    hedge_pairs.get("pair_id", hedge_pairs.index).astype(str) == pair_info["pair_id"]
                ]
                if pair_row_match.empty:
                    continue
                pr = pair_row_match.iloc[0]
                hedged_ids = _parse_deal_ids(pr.get("hedged_item_deal_ids", ""))
                instrument_ids = _parse_deal_ids(pr.get("hedging_instrument_deal_ids", ""))

                for sc in scenarios_list:
                    sc_slice = sc_pnl[sc_pnl["Shock"] == sc]
                    h_pnl = float(sc_slice[sc_slice["Dealid"].isin(hedged_ids)]["Value"].sum()) if "Value" in sc_slice.columns else 0
                    i_pnl = float(sc_slice[sc_slice["Dealid"].isin(instrument_ids)]["Value"].sum()) if "Value" in sc_slice.columns else 0
                    ratio = (i_pnl / h_pnl) if abs(h_pnl) > 0 else 0.0
                    net = h_pnl + i_pnl
                    scenario_xref.append({
                        "pair_name": pair_info["pair_name"],
                        "scenario": sc,
                        "hedged_pnl": round(h_pnl, 0),
                        "instrument_pnl": round(i_pnl, 0),
                        "net_pnl": round(net, 0),
                        "ratio": round(ratio, 4),
                    })

    return {
        "has_data": len(pairs) > 0,
        "pairs": pairs,
        "summary": {"pass": n_pass, "fail": n_fail, "total": n_pass + n_fail},
        "scenario_xref": scenario_xref,
    }


def _parse_deal_ids(s: str) -> list:
    """Parse comma-separated deal IDs."""
    if not s or pd.isna(s):
        return []
    return [x.strip() for x in str(s).split(",") if x.strip()]


def _build_nii_at_risk(df: pd.DataFrame, scenarios_data: Optional[pd.DataFrame] = None) -> dict:
    """NII-at-Risk from BCBS 368 scenarios.

    scenarios_data: Stacked DataFrame with Shock = scenario name (from run_scenarios).
    """
    empty = {"has_data": False, "scenarios": [], "by_currency": {}, "worst_case": {},
             "heatmap": [], "tornado": []}

    if scenarios_data is None or (isinstance(scenarios_data, pd.DataFrame) and scenarios_data.empty):
        return empty

    if isinstance(scenarios_data, dict):
        return {"has_data": True, **scenarios_data}

    sc_df = scenarios_data.copy()
    if isinstance(sc_df.index, pd.MultiIndex):
        sc_df = sc_df.reset_index()

    # Filter to PnL rows
    pnl = sc_df[sc_df["Indice"] == "PnL"] if "Indice" in sc_df.columns else sc_df
    if pnl.empty or "Shock" not in pnl.columns:
        return empty

    scenarios = sorted(pnl["Shock"].unique())
    currencies = sorted(pnl["Deal currency"].unique()) if "Deal currency" in pnl.columns else []

    # Also get base NII (shock=0) from the main df for delta computation
    base_nii = {}
    if not df.empty:
        base_pnl = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")]
        if "Deal currency" in base_pnl.columns:
            for ccy in currencies:
                base_nii[ccy] = float(base_pnl[base_pnl["Deal currency"] == ccy]["Value"].sum())
    base_total = sum(base_nii.values())

    # Heatmap: scenario x currency -> NII
    heatmap = []
    by_currency = {}
    scenario_totals = {}

    for sc in scenarios:
        sc_pnl = pnl[pnl["Shock"] == sc]
        row = {"scenario": sc}
        sc_total = 0.0
        for ccy in currencies:
            nii = float(sc_pnl[sc_pnl["Deal currency"] == ccy]["Value"].sum()) if "Deal currency" in sc_pnl.columns else 0.0
            row[ccy] = round(nii, 0)
            sc_total += nii
            by_currency.setdefault(ccy, {})[sc] = round(nii, 0)
        row["total"] = round(sc_total, 0)
        heatmap.append(row)
        scenario_totals[sc] = sc_total

    # Tornado chart: sorted by NII delta from base
    tornado = []
    for sc in scenarios:
        delta = scenario_totals.get(sc, 0) - base_total
        tornado.append({"scenario": sc, "nii": round(scenario_totals.get(sc, 0), 0),
                        "delta": round(delta, 0)})
    tornado.sort(key=lambda x: x["delta"])

    # Worst case
    worst = min(tornado, key=lambda x: x["nii"]) if tornado else {}

    # --- Parametric Earnings-at-Risk ---
    # Approximate EaR from scenario deltas: assume normal distribution of NII outcomes
    ear = None
    if len(tornado) >= 3 and base_total != 0:
        deltas = [t["delta"] for t in tornado]
        mean_delta = float(np.mean(deltas))
        std_delta = float(np.std(deltas, ddof=0))
        if std_delta > 0:
            # 95% and 99% VaR (1-sided)
            ear_95 = mean_delta - 1.645 * std_delta
            ear_99 = mean_delta - 2.326 * std_delta
            ear = {
                "mean_delta": round(mean_delta, 0),
                "std_delta": round(std_delta, 0),
                "ear_95": round(ear_95, 0),
                "ear_99": round(ear_99, 0),
                "ear_95_pct": round(ear_95 / abs(base_total) * 100, 2) if base_total else 0,
                "ear_99_pct": round(ear_99 / abs(base_total) * 100, 2) if base_total else 0,
                "n_scenarios": len(tornado),
                "min_delta": round(float(min(deltas)), 0),
                "max_delta": round(float(max(deltas)), 0),
                "scenario_nii": [{"scenario": t["scenario"], "nii": t["nii"], "delta": t["delta"]} for t in tornado],
            }

    return {
        "has_data": True,
        "scenarios": scenarios,
        "by_currency": by_currency,
        "heatmap": heatmap,
        "tornado": tornado,
        "worst_case": worst,
        "base_total": round(base_total, 0),
        "ear": ear,
    }


def _build_deal_explorer(
    df: pd.DataFrame,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Deal-level drill-down with sortable table, P&L histogram, maturity profile."""
    if pnl_by_deal is None or (isinstance(pnl_by_deal, pd.DataFrame) and pnl_by_deal.empty):
        return {"has_data": False, "deals": [], "histogram": {}, "maturity_profile": {},
                "summary_stats": {}, "by_product": {}, "by_currency": {}}

    by_deal = pnl_by_deal.copy()

    # Filter to base shock
    if "Shock" in by_deal.columns:
        by_deal = by_deal[by_deal["Shock"] == "0"]
    if by_deal.empty:
        return {"has_data": False, "deals": [], "histogram": {}, "maturity_profile": {},
                "summary_stats": {}, "by_product": {}, "by_currency": {}}

    # Aggregate across months to annual deal-level totals
    id_cols = [c for c in ["Dealid", "Counterparty", "Currency", "Product",
                           "Direction", "P\u00e9rim\u00e8tre TOTAL"]
               if c in by_deal.columns]
    if "Dealid" not in id_cols:
        return {"has_data": False, "deals": [], "histogram": {}, "maturity_profile": {},
                "summary_stats": {}, "by_product": {}, "by_currency": {}}

    agg_cols = {}
    for col in ["PnL", "GrossCarry", "FundingCost"]:
        if col in by_deal.columns:
            agg_cols[col] = (col, "sum")
    for col in ["Nominal", "OISfwd", "RateRef"]:
        if col in by_deal.columns:
            agg_cols[col] = (col, "mean")

    agg = by_deal.groupby(id_cols).agg(**agg_cols).reset_index()

    # Enrich with deal metadata (maturity, amount) if deals DataFrame available
    if deals is not None and not deals.empty and "Dealid" in deals.columns:
        meta_cols = ["Dealid"]
        for c in ["Maturitydate", "Valuedate", "Amount", "FTP"]:
            if c in deals.columns:
                meta_cols.append(c)
        meta = deals[meta_cols].drop_duplicates(subset=["Dealid"])
        agg["Dealid"] = agg["Dealid"].astype(str)
        meta["Dealid"] = meta["Dealid"].astype(str)
        agg = agg.merge(meta, on="Dealid", how="left")

    # Compute spread (bps)
    if "OISfwd" in agg.columns and "RateRef" in agg.columns:
        agg["Spread_bps"] = (agg["OISfwd"] - agg["RateRef"]) * 10000
    else:
        agg["Spread_bps"] = 0.0

    # Build deal list (capped at 200 for HTML performance)
    agg_sorted = agg.sort_values("PnL", key=abs, ascending=False)
    deal_list = []
    for _, row in agg_sorted.head(200).iterrows():
        d = {
            "deal_id": str(row.get("Dealid", "")),
            "counterparty": str(row.get("Counterparty", "")),
            "currency": str(row.get("Currency", "")),
            "product": str(row.get("Product", "")),
            "direction": str(row.get("Direction", "")),
            "perimeter": str(row.get("P\u00e9rim\u00e8tre TOTAL", "")),
            "pnl": round(float(row.get("PnL", 0)), 0),
            "nominal": round(float(row.get("Nominal", 0)), 0),
            "ois": round(float(row.get("OISfwd", 0)) * 100, 4),
            "rate_ref": round(float(row.get("RateRef", 0)) * 100, 4),
            "spread_bps": round(float(row.get("Spread_bps", 0)), 1),
        }
        if "Maturitydate" in row.index and pd.notna(row.get("Maturitydate")):
            d["maturity"] = str(pd.Timestamp(row["Maturitydate"]).strftime("%Y-%m-%d"))
        else:
            d["maturity"] = ""
        if "FTP" in row.index and pd.notna(row.get("FTP")):
            d["ftp"] = round(float(row["FTP"]) * 100, 4)
        else:
            d["ftp"] = None
        deal_list.append(d)

    # P&L histogram (binned)
    pnl_values = agg["PnL"].dropna().values
    histogram = {"bins": [], "counts": []}
    if len(pnl_values) > 0:
        n_bins = min(30, max(10, len(pnl_values) // 5))
        counts, bin_edges = np.histogram(pnl_values, bins=n_bins)
        histogram["bins"] = [round(float(b), 0) for b in bin_edges[:-1]]
        histogram["counts"] = [int(c) for c in counts]
        histogram["bin_width"] = round(float(bin_edges[1] - bin_edges[0]), 0)

    # Maturity profile (deals maturing per quarter)
    maturity_profile = {"labels": [], "counts": [], "volumes": []}
    if "Maturitydate" in agg.columns:
        mat = pd.to_datetime(agg["Maturitydate"], errors="coerce")
        valid = agg[mat.notna()].copy()
        valid["MatQ"] = mat[mat.notna()].dt.to_period("Q").astype(str)
        if not valid.empty:
            grp = valid.groupby("MatQ").agg(
                count=("Dealid", "count"),
                volume=("Nominal", "sum"),
            ).sort_index()
            maturity_profile["labels"] = grp.index.tolist()[:20]
            maturity_profile["counts"] = grp["count"].tolist()[:20]
            maturity_profile["volumes"] = [round(float(v), 0) for v in grp["volume"].values[:20]]

    # Summary stats
    total_pnl = float(agg["PnL"].sum())
    positive = agg[agg["PnL"] > 0]
    negative = agg[agg["PnL"] <= 0]
    summary_stats = {
        "total_deals": len(agg),
        "total_pnl": round(total_pnl, 0),
        "avg_pnl": round(float(agg["PnL"].mean()), 0) if len(agg) > 0 else 0,
        "median_pnl": round(float(agg["PnL"].median()), 0) if len(agg) > 0 else 0,
        "positive_count": len(positive),
        "negative_count": len(negative),
        "positive_pnl": round(float(positive["PnL"].sum()), 0) if len(positive) > 0 else 0,
        "negative_pnl": round(float(negative["PnL"].sum()), 0) if len(negative) > 0 else 0,
        "top1_pct": round(float(agg_sorted.head(1)["PnL"].sum()) / total_pnl * 100, 1) if total_pnl != 0 else 0,
        "top10_pct": round(float(agg_sorted.head(10)["PnL"].sum()) / total_pnl * 100, 1) if total_pnl != 0 else 0,
    }

    # By product breakdown
    by_product = {}
    if "Product" in agg.columns:
        for prod, grp in agg.groupby("Product"):
            by_product[str(prod)] = {
                "count": len(grp),
                "pnl": round(float(grp["PnL"].sum()), 0),
                "nominal": round(float(grp["Nominal"].sum()), 0),
                "color": PRODUCT_COLORS.get(str(prod), "#8b949e"),
            }

    # By currency breakdown
    by_currency = {}
    if "Currency" in agg.columns:
        for ccy, grp in agg.groupby("Currency"):
            by_currency[str(ccy)] = {
                "count": len(grp),
                "pnl": round(float(grp["PnL"].sum()), 0),
                "nominal": round(float(grp["Nominal"].sum()), 0),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    return {
        "has_data": True,
        "deals": deal_list,
        "histogram": histogram,
        "maturity_profile": maturity_profile,
        "summary_stats": summary_stats,
        "by_product": by_product,
        "by_currency": by_currency,
    }


def _build_fixed_float(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Fixed vs Floating mix analysis by currency with sensitivity attribution."""
    if deals is None or deals.empty:
        return {"has_data": False, "mix": {}, "by_currency": {}, "sensitivity": {}}

    d = deals.copy()

    # Identify floating: deals with non-empty Floating Rates Short Name
    float_col = None
    for c in ["Floating Rates Short Name", "FloatingRateShortName", "is_floating"]:
        if c in d.columns:
            float_col = c
            break

    if float_col is None:
        return {"has_data": False, "mix": {}, "by_currency": {}, "sensitivity": {}}

    if float_col == "is_floating":
        d["_is_float"] = d[float_col].astype(bool)
    else:
        d["_is_float"] = d[float_col].fillna("").astype(str).str.strip().ne("")

    d["_type"] = d["_is_float"].map({True: "Floating", False: "Fixed"})

    # Need nominal -- use Amount or Nominal
    nom_col = "Amount" if "Amount" in d.columns else "Nominal" if "Nominal" in d.columns else None
    if nom_col is None:
        return {"has_data": False, "mix": {}, "by_currency": {}, "sensitivity": {}}

    d["_nom"] = pd.to_numeric(d[nom_col], errors="coerce").fillna(0).abs()

    # Overall mix
    mix = {}
    for t in ["Fixed", "Floating"]:
        subset = d[d["_type"] == t]
        mix[t] = {
            "count": len(subset),
            "nominal": round(float(subset["_nom"].sum()), 0),
        }
    total_nom = d["_nom"].sum()
    for t in mix:
        mix[t]["pct"] = round(mix[t]["nominal"] / total_nom * 100, 1) if total_nom > 0 else 0

    # By currency
    ccy_col = "Currency" if "Currency" in d.columns else "Deal currency" if "Deal currency" in d.columns else None
    by_currency = {}
    if ccy_col:
        for ccy in sorted(d[ccy_col].dropna().unique()):
            subset = d[d[ccy_col] == ccy]
            ccy_total = subset["_nom"].sum()
            fixed = subset[subset["_type"] == "Fixed"]["_nom"].sum()
            floating = subset[subset["_type"] == "Floating"]["_nom"].sum()
            by_currency[str(ccy)] = {
                "fixed": round(float(fixed), 0),
                "floating": round(float(floating), 0),
                "fixed_pct": round(float(fixed) / ccy_total * 100, 1) if ccy_total > 0 else 0,
                "floating_pct": round(float(floating) / ccy_total * 100, 1) if ccy_total > 0 else 0,
                "count_fixed": int(len(subset[subset["_type"] == "Fixed"])),
                "count_floating": int(len(subset[subset["_type"] == "Floating"])),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # Sensitivity attribution: floating reprices -> full rate sensitivity;
    # fixed -> no direct NII sensitivity (only EVE)
    # Extract from P&L stacked data if available
    sensitivity = {}
    if not df.empty and "Shock" in df.columns:
        pnl_base = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")]
        pnl_50 = df[(df["Indice"] == "PnL") & (df["Shock"] == "50")]
        if not pnl_base.empty and not pnl_50.empty:
            base_total = _filter_total(pnl_base)["Value"].sum()
            shock_total = _filter_total(pnl_50)["Value"].sum()
            delta = shock_total - base_total
            # Floating book is ~100% of rate sensitivity
            sensitivity = {
                "total_delta": round(float(delta), 0),
                "floating_nom_pct": mix.get("Floating", {}).get("pct", 0),
                "note": "Floating book reprices at next fixing \u2192 drives NII sensitivity. "
                        "Fixed book locked in \u2192 drives EVE sensitivity.",
            }

    return {
        "has_data": True,
        "mix": mix,
        "by_currency": by_currency,
        "sensitivity": sensitivity,
    }


def _build_nim(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Net Interest Margin: NIM = NII / Avg Earning Assets. Jaws chart (yield vs cost)."""
    if df.empty:
        return {"has_data": False, "kpis": {}, "jaws": {}, "by_currency": {}, "by_month": {}}

    pnl = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")].copy()
    nom = df[(df["Indice"] == "Nominal") & (df["Shock"] == "0")].copy()
    ois = df[(df["Indice"] == "OISfwd") & (df["Shock"] == "0")].copy()
    ref = df[(df["Indice"] == "RateRef") & (df["Shock"] == "0")].copy()

    if pnl.empty or nom.empty:
        return {"has_data": False, "kpis": {}, "jaws": {}, "by_currency": {}, "by_month": {}}

    # Filter to Total rows to avoid double-counting
    pnl = _filter_total(pnl)
    nom = _filter_total(nom)
    ois = _filter_total(ois)
    ref = _filter_total(ref)

    # --- Global NIM ---
    total_nii = pnl["Value"].sum()
    # Earning assets = average nominal for asset direction (L/B)
    if "Direction" in nom.columns:
        asset_nom = nom[nom["Direction"].isin(["L", "B"])]["Value"].sum()
    else:
        asset_nom = nom["Value"].abs().sum()

    # Annualize: if data covers N months, annualize
    months = sorted(pnl["Month"].unique()) if "Month" in pnl.columns else []
    n_months = max(len(months), 1)
    annual_factor = 12.0 / n_months

    nii_annual = total_nii * annual_factor
    avg_assets = asset_nom / n_months if n_months > 0 else 0
    nim_bps = (nii_annual / avg_assets * 10000) if avg_assets != 0 else 0

    # --- Jaws chart: asset yield vs funding cost by month ---
    jaws = {"months": [], "asset_yield": [], "funding_cost": [], "nim": []}

    # Use GrossCarry and FundingCost if available
    gc_rows = df[(df["Indice"] == "GrossCarry") & (df["Shock"] == "0")]
    fc_rows = df[(df["Indice"] == "FundingCost") & (df["Shock"] == "0")]
    has_coc = not gc_rows.empty and not fc_rows.empty

    if has_coc:
        gc = _filter_total(gc_rows)
        fc = _filter_total(fc_rows)
        for m in months:
            m_gc = gc[gc["Month"] == m]["Value"].sum()
            m_fc = fc[fc["Month"] == m]["Value"].sum()
            m_nom = nom[nom["Month"] == m]["Value"].abs().sum()
            # Annualized rates in bps
            if m_nom > 0:
                yield_bps = m_gc / m_nom * 12 * 10000
                cost_bps = m_fc / m_nom * 12 * 10000
            else:
                yield_bps = 0
                cost_bps = 0
            jaws["months"].append(str(m))
            jaws["asset_yield"].append(round(float(yield_bps), 1))
            jaws["funding_cost"].append(round(float(cost_bps), 1))
            jaws["nim"].append(round(float(yield_bps - cost_bps), 1))
    else:
        # Fallback: use weighted OIS as funding proxy, RateRef as asset yield
        for m in months:
            m_ois = ois[ois["Month"] == m]["Value"].mean() if not ois.empty else 0
            m_ref = ref[ref["Month"] == m]["Value"].mean() if not ref.empty else 0
            jaws["months"].append(str(m))
            jaws["asset_yield"].append(round(float(m_ref) * 10000, 1))
            jaws["funding_cost"].append(round(float(m_ois) * 10000, 1))
            jaws["nim"].append(round(float(m_ref - m_ois) * 10000, 1))

    # --- NIM by currency ---
    by_currency = {}
    if "Deal currency" in pnl.columns:
        for ccy in sorted(pnl["Deal currency"].unique()):
            ccy_pnl = pnl[pnl["Deal currency"] == ccy]["Value"].sum()
            if "Direction" in nom.columns:
                ccy_asset = nom[(nom["Deal currency"] == ccy) & (nom["Direction"].isin(["L", "B"]))]["Value"].sum()
            else:
                ccy_asset = nom[nom["Deal currency"] == ccy]["Value"].abs().sum()
            ccy_avg = ccy_asset / n_months if n_months > 0 else 0
            ccy_nii_a = ccy_pnl * annual_factor
            ccy_nim = (ccy_nii_a / ccy_avg * 10000) if ccy_avg != 0 else 0

            by_currency[str(ccy)] = {
                "nii": round(float(ccy_pnl), 0),
                "avg_assets": round(float(ccy_avg), 0),
                "nim_bps": round(float(ccy_nim), 1),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # --- NIM by perimeter ---
    by_perimeter = {}
    if "P\u00e9rim\u00e8tre TOTAL" in pnl.columns:
        for peri in sorted(pnl["P\u00e9rim\u00e8tre TOTAL"].unique()):
            p_pnl = pnl[pnl["P\u00e9rim\u00e8tre TOTAL"] == peri]["Value"].sum()
            if "Direction" in nom.columns:
                p_asset = nom[(nom["P\u00e9rim\u00e8tre TOTAL"] == peri) & (nom["Direction"].isin(["L", "B"]))]["Value"].sum()
            else:
                p_asset = nom[nom["P\u00e9rim\u00e8tre TOTAL"] == peri]["Value"].abs().sum()
            p_avg = p_asset / n_months if n_months > 0 else 0
            p_nii_a = p_pnl * annual_factor
            p_nim = (p_nii_a / p_avg * 10000) if p_avg != 0 else 0
            by_perimeter[str(peri)] = {
                "nii": round(float(p_pnl), 0),
                "avg_assets": round(float(p_avg), 0),
                "nim_bps": round(float(p_nim), 1),
            }

    kpis = {
        "nii_annual": round(float(nii_annual), 0),
        "avg_earning_assets": round(float(avg_assets), 0),
        "nim_bps": round(float(nim_bps), 1),
        "n_months": n_months,
    }

    return {
        "has_data": True,
        "kpis": kpis,
        "jaws": jaws,
        "by_currency": by_currency,
        "by_perimeter": by_perimeter,
    }
