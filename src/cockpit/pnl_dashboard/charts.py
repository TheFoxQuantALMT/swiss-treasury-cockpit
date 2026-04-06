"""Chart data builders for the P&L dashboard.

Transforms PnlEngine output (pnlAll / pnlAllS DataFrames) into Chart.js-ready
dicts that Jinja2 templates embed as inline JSON.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Currency color palette (consistent with cockpit)
CURRENCY_COLORS = {
    "CHF": "#d62828",
    "EUR": "#e67e22",
    "USD": "#002868",
    "GBP": "#6f42c1",
}

LEG_COLORS = {
    "IAM/LD-NHCD": "#58a6ff",
    "IAM/LD-HCD": "#3fb950",
    "BND-NHCD": "#d29922",
    "BND-HCD": "#f0883e",
}

PRODUCT_COLORS = {
    "IAM/LD": "#58a6ff",
    "BND": "#3fb950",
    "FXS": "#d29922",
    "IRS": "#f0883e",
    "IRS-MTM": "#a5d6ff",
    "HCD": "#8b949e",
}


def _safe_stacked(pnl_all_s: pd.DataFrame) -> pd.DataFrame:
    """Reset MultiIndex to flat columns for easier filtering."""
    if pnl_all_s is None or pnl_all_s.empty:
        return pd.DataFrame()
    df = pnl_all_s.copy()
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
    return df


def _month_labels(months) -> list[str]:
    """Convert Period/str months to display labels."""
    return [str(m) for m in months]


def _filter_total(df: pd.DataFrame) -> pd.DataFrame:
    """Filter for PnL_Type == 'Total', falling back to all rows if no Total rows exist."""
    if "PnL_Type" not in df.columns:
        return df
    total = df[df["PnL_Type"] == "Total"]
    return total if not total.empty else df


# ---------------------------------------------------------------------------
# Tab 1: Executive Summary
# ---------------------------------------------------------------------------

def _build_summary(
    df: pd.DataFrame,
    date_rates: datetime,
    prev_df: Optional[pd.DataFrame] = None,
) -> dict:
    """KPIs, currency donut, realized/forecast waterfall, top 5 contributors, DoD bridge."""
    if df.empty:
        return {"kpis": {}, "donut": {}, "waterfall": {}, "top5": [], "dod_bridge": None}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty:
        return {"kpis": {}, "donut": {}, "waterfall": {}, "top5": []}

    # KPI cards: total P&L per shock (12-month horizon)
    kpis = {}
    for shock in ("0", "50", "wirp"):
        shock_data = pnl_rows[pnl_rows["Shock"] == shock]
        if shock_data.empty:
            continue
        # Use "Total" PnL_Type to avoid triple-counting with Realized+Forecast
        total = _filter_total(shock_data)["Value"].sum()
        if "PnL_Type" in shock_data.columns:
            realized = float(shock_data[shock_data["PnL_Type"] == "Realized"]["Value"].sum())
            forecast = float(shock_data[shock_data["PnL_Type"] == "Forecast"]["Value"].sum())
        else:
            realized = 0.0
            forecast = 0.0
        kpis[f"shock_{shock}"] = {
            "total": round(float(total), 0),
            "realized": round(float(realized), 0),
            "forecast": round(float(forecast), 0),
        }

    # Delta: shock_50 - shock_0
    if "shock_50" in kpis and "shock_0" in kpis:
        kpis["delta_50_0"] = round(kpis["shock_50"]["total"] - kpis["shock_0"]["total"], 0)
    else:
        kpis["delta_50_0"] = 0

    # Currency donut (shock=0, Total PnL_Type only)
    base_all = pnl_rows[pnl_rows["Shock"] == "0"]
    base = _filter_total(base_all)
    if "Deal currency" in base.columns:
        ccy_totals = base.groupby("Deal currency")["Value"].sum()
        donut = {
            "labels": list(ccy_totals.index),
            "values": [round(float(v), 0) for v in ccy_totals.values],
            "colors": [CURRENCY_COLORS.get(c, "#8b949e") for c in ccy_totals.index],
        }
    else:
        donut = {"labels": [], "values": [], "colors": []}

    # Realized vs Forecast waterfall per currency (use base_all for the split)
    waterfall = {"labels": [], "realized": [], "forecast": []}
    if "PnL_Type" in base_all.columns and "Deal currency" in base_all.columns:
        for ccy in sorted(base_all["Deal currency"].unique()):
            ccy_data = base_all[base_all["Deal currency"] == ccy]
            r = float(ccy_data[ccy_data["PnL_Type"] == "Realized"]["Value"].sum())
            f = float(ccy_data[ccy_data["PnL_Type"] == "Forecast"]["Value"].sum())
            waterfall["labels"].append(ccy)
            waterfall["realized"].append(round(r, 0))
            waterfall["forecast"].append(round(f, 0))

    # Top 5 contributors (by |PnL|, shock=0)
    top5 = []
    if "Product2BuyBack" in base.columns and "Deal currency" in base.columns:
        grouped = base.groupby(["Deal currency", "Product2BuyBack"])["Value"].sum().reset_index()
        grouped["abs_val"] = grouped["Value"].abs()
        top = grouped.nlargest(5, "abs_val")
        for _, row in top.iterrows():
            top5.append({
                "currency": row["Deal currency"],
                "product": row["Product2BuyBack"],
                "pnl": round(float(row["Value"]), 0),
            })

    # CoC YTD: aggregate GrossCarry, FundingCost, CoC_Simple, CoC_Compound at shock=0
    coc_ytd = None
    coc_indices = {"GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound"}
    coc_rows = _filter_total(df[(df["Indice"].isin(coc_indices)) & (df["Shock"] == "0")])
    if not coc_rows.empty:
        coc_ytd = {
            "gross_carry": round(float(coc_rows.loc[coc_rows["Indice"] == "GrossCarry", "Value"].sum()), 0),
            "funding_cost": round(float(coc_rows.loc[coc_rows["Indice"] == "FundingCost", "Value"].sum()), 0),
            "coc_simple": round(float(coc_rows.loc[coc_rows["Indice"] == "CoC_Simple", "Value"].sum()), 0),
            "coc_compound": round(float(coc_rows.loc[coc_rows["Indice"] == "CoC_Compound", "Value"].sum()), 0),
        }

    # Day-over-day P&L bridge (requires prev_df)
    dod_bridge = None
    if prev_df is not None and not prev_df.empty and "Deal currency" in base.columns:
        prev_pnl = _filter_total(prev_df[(prev_df["Indice"] == "PnL") & (prev_df["Shock"] == "0")])
        if not prev_pnl.empty and "Deal currency" in prev_pnl.columns:
            curr_by_ccy = base.groupby("Deal currency")["Value"].sum()
            prev_by_ccy = prev_pnl.groupby("Deal currency")["Value"].sum()
            bridge_rows = []
            all_ccys = sorted(set(curr_by_ccy.index) | set(prev_by_ccy.index))
            total_prev = 0.0
            total_curr = 0.0
            for ccy in all_ccys:
                c = float(curr_by_ccy.get(ccy, 0))
                p = float(prev_by_ccy.get(ccy, 0))
                total_prev += p
                total_curr += c
                bridge_rows.append({
                    "currency": ccy,
                    "previous": round(p, 0),
                    "current": round(c, 0),
                    "delta": round(c - p, 0),
                    "color": CURRENCY_COLORS.get(ccy, "#8b949e"),
                })
            bridge_rows.append({
                "currency": "Total",
                "previous": round(total_prev, 0),
                "current": round(total_curr, 0),
                "delta": round(total_curr - total_prev, 0),
                "color": "#e6edf3",
            })
            dod_bridge = bridge_rows

    return {"kpis": kpis, "donut": donut, "waterfall": waterfall, "top5": top5, "coc_ytd": coc_ytd, "dod_bridge": dod_bridge}


# ---------------------------------------------------------------------------
# Tab 2: CoC Decomposition (Hero)
# ---------------------------------------------------------------------------

def _build_coc(df: pd.DataFrame) -> dict:
    """CoC measures by currency × month × shock."""
    if df.empty:
        return {"months": [], "by_currency": {}, "table": []}

    coc_indices = {"GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate"}
    coc_rows = df[df["Indice"].isin(coc_indices)].copy()
    if coc_rows.empty:
        return {"months": [], "by_currency": {}, "table": []}

    # Filter to Total PnL_Type to avoid double-counting with Realized+Forecast
    coc_rows = _filter_total(coc_rows)

    months = sorted(coc_rows["Month"].unique()) if "Month" in coc_rows.columns else []
    month_labels = _month_labels(months)

    by_currency = {}
    currencies = sorted(coc_rows["Deal currency"].unique()) if "Deal currency" in coc_rows.columns else []

    for ccy in currencies:
        ccy_data = coc_rows[coc_rows["Deal currency"] == ccy]
        by_shock = {}
        for shock in ccy_data["Shock"].unique() if "Shock" in ccy_data.columns else ["0"]:
            shock_data = ccy_data[ccy_data["Shock"] == shock]
            measures = {}
            for indice in coc_indices:
                idx_data = shock_data[shock_data["Indice"] == indice]
                if idx_data.empty:
                    measures[indice] = [0.0] * len(months)
                else:
                    # Sum by month (across products/directions)
                    by_month = idx_data.groupby("Month")["Value"].sum()
                    measures[indice] = [round(float(by_month.get(m, 0.0)), 2) for m in months]
            by_shock[f"shock_{shock}"] = measures
        by_currency[ccy] = by_shock

    # Aggregate "All" currencies
    all_by_shock = {}
    for shock_key in set().union(*(d.keys() for d in by_currency.values())) if by_currency else []:
        measures = {}
        for indice in coc_indices:
            vals = [0.0] * len(months)
            for ccy_data in by_currency.values():
                if shock_key in ccy_data and indice in ccy_data[shock_key]:
                    for i, v in enumerate(ccy_data[shock_key][indice]):
                        vals[i] += v
            measures[indice] = [round(v, 2) for v in vals]
        all_by_shock[shock_key] = measures
    by_currency["All"] = all_by_shock

    # Table data (shock=0, all currencies)
    table = []
    if "shock_0" in all_by_shock:
        for i, m in enumerate(month_labels):
            row = {"month": m}
            for indice in ["GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate"]:
                row[indice] = all_by_shock["shock_0"].get(indice, [0.0] * len(months))[i]
            table.append(row)

    # Carry vs Roll-down decomposition (shock=0)
    # Carry = CoC_Simple (spread income), Roll-down = Total PnL - Carry
    carry_rolldown = None
    pnl_base = _filter_total(df[(df["Indice"] == "PnL") & (df["Shock"] == "0")])
    if not pnl_base.empty and "shock_0" in all_by_shock:
        total_pnl_by_month = pnl_base.groupby("Month")["Value"].sum()
        pnl_vals = [round(float(total_pnl_by_month.get(m, 0)), 0) for m in months]
        carry = all_by_shock["shock_0"].get("CoC_Simple", [0.0] * len(months))
        rolldown = [round(p - c, 0) for p, c in zip(pnl_vals, carry)]
        carry_rolldown = {
            "months": month_labels,
            "total_pnl": pnl_vals,
            "carry": [round(c, 0) for c in carry],
            "rolldown": rolldown,
        }

    return {"months": month_labels, "by_currency": by_currency, "table": table, "carry_rolldown": carry_rolldown}


# ---------------------------------------------------------------------------
# Tab 3: P&L Time Series
# ---------------------------------------------------------------------------

def _build_pnl_series(df: pd.DataFrame, date_rates: datetime) -> dict:
    """Monthly P&L by currency × shock, with realized/forecast split."""
    if df.empty:
        return {"months": [], "by_currency": {}, "by_product": {}, "date_rates_month": ""}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty:
        return {"months": [], "by_currency": {}, "by_product": {}, "date_rates_month": ""}

    months = sorted(pnl_rows["Month"].unique()) if "Month" in pnl_rows.columns else []
    month_labels = _month_labels(months)
    rates_month = str(pd.Timestamp(date_rates).to_period("M"))

    by_currency = {}
    currencies = sorted(pnl_rows["Deal currency"].unique()) if "Deal currency" in pnl_rows.columns else []

    for ccy in currencies:
        ccy_data = pnl_rows[pnl_rows["Deal currency"] == ccy]
        by_shock = {}
        for shock in sorted(ccy_data["Shock"].unique()) if "Shock" in ccy_data.columns else ["0"]:
            shock_data = ccy_data[ccy_data["Shock"] == shock]

            # Use Total PnL_Type for the main series (avoid summing Total+Realized+Forecast)
            total = _filter_total(shock_data).groupby("Month")["Value"].sum()
            by_shock[f"shock_{shock}"] = [round(float(total.get(m, 0.0)), 0) for m in months]

            # Realized/forecast split for this shock
            if "PnL_Type" in shock_data.columns:
                realized = shock_data[shock_data["PnL_Type"] == "Realized"].groupby("Month")["Value"].sum()
                forecast_df = shock_data[shock_data["PnL_Type"] == "Forecast"]
                forecast = forecast_df.groupby("Month")["Value"].sum()
                by_shock[f"shock_{shock}_realized"] = [round(float(realized.get(m, 0.0)), 0) for m in months]
                by_shock[f"shock_{shock}_forecast"] = [round(float(forecast.get(m, 0.0)), 0) for m in months]

        by_currency[ccy] = by_shock

    # Product breakdown (shock=0 only, Total PnL_Type)
    by_product = {}
    base = pnl_rows[pnl_rows["Shock"] == "0"] if "Shock" in pnl_rows.columns else pnl_rows
    base = _filter_total(base)
    if "Product2BuyBack" in base.columns:
        for prod in sorted(base["Product2BuyBack"].unique()):
            prod_data = base[base["Product2BuyBack"] == prod]
            total = prod_data.groupby("Month")["Value"].sum()
            by_product[prod] = {
                "values": [round(float(total.get(m, 0.0)), 0) for m in months],
                "color": PRODUCT_COLORS.get(prod, "#8b949e"),
            }

    return {
        "months": month_labels,
        "by_currency": by_currency,
        "by_product": by_product,
        "date_rates_month": rates_month,
    }


# ---------------------------------------------------------------------------
# Tab 4: Shock Sensitivity
# ---------------------------------------------------------------------------

def _build_sensitivity(df: pd.DataFrame) -> dict:
    """Delta P&L heatmap: shock=50 minus shock=0, per currency × product × month."""
    if df.empty:
        return {"months": [], "rows": [], "totals": {}}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty or "Shock" not in pnl_rows.columns:
        return {"months": [], "rows": [], "totals": {}}

    # Filter to Total PnL_Type only to avoid double-counting with Realized+Forecast
    pnl_rows = _filter_total(pnl_rows)

    base = pnl_rows[pnl_rows["Shock"] == "0"]
    shock50 = pnl_rows[pnl_rows["Shock"] == "50"]
    wirp = pnl_rows[pnl_rows["Shock"] == "wirp"]

    months = sorted(pnl_rows["Month"].unique())[:12]  # 12-month window
    month_labels = _month_labels(months)

    def _delta_grid(df_a: pd.DataFrame, df_b: pd.DataFrame) -> list[dict]:
        """Compute df_a - df_b grouped by currency × product × month."""
        rows = []
        if "Deal currency" not in df_a.columns or "Product2BuyBack" not in df_a.columns:
            return rows

        a_dict = df_a.groupby(["Deal currency", "Product2BuyBack", "Month"])["Value"].sum().to_dict()
        b_dict = df_b.groupby(["Deal currency", "Product2BuyBack", "Month"])["Value"].sum().to_dict()

        keys = set(a_dict.keys()) | set(b_dict.keys())
        combos = sorted({(k[0], k[1]) for k in keys})

        for ccy, prod in combos:
            values = []
            for m in months:
                val_a = a_dict.get((ccy, prod, m), 0.0)
                val_b = b_dict.get((ccy, prod, m), 0.0)
                values.append(round(float(val_a - val_b), 0))
            rows.append({
                "currency": ccy,
                "product": prod,
                "values": values,
                "total": sum(values),
            })
        return rows

    rows_50 = _delta_grid(shock50, base)
    rows_wirp = _delta_grid(wirp, base)

    # Currency totals
    totals_50 = {}
    for row in rows_50:
        ccy = row["currency"]
        if ccy not in totals_50:
            totals_50[ccy] = [0.0] * len(months)
        for i, v in enumerate(row["values"]):
            totals_50[ccy][i] += v

    totals_wirp = {}
    for row in rows_wirp:
        ccy = row["currency"]
        if ccy not in totals_wirp:
            totals_wirp[ccy] = [0.0] * len(months)
        for i, v in enumerate(row["values"]):
            totals_wirp[ccy][i] += v

    return {
        "months": month_labels,
        "rows_50": rows_50,
        "rows_wirp": rows_wirp,
        "totals_50": {k: [round(v, 0) for v in vals] for k, vals in totals_50.items()},
        "totals_wirp": {k: [round(v, 0) for v in vals] for k, vals in totals_wirp.items()},
        "grand_total_50": round(sum(r["total"] for r in rows_50), 0),
        "grand_total_wirp": round(sum(r["total"] for r in rows_wirp), 0),
    }


# ---------------------------------------------------------------------------
# Tab 5: Strategy IAS Decomposition
# ---------------------------------------------------------------------------

def _build_strategy(df: pd.DataFrame) -> dict:
    """Strategy IAS 4-leg decomposition by month."""
    if df.empty:
        return {"has_data": False, "months": [], "legs": {}, "table": []}

    strategy_legs = {"IAM/LD-NHCD", "IAM/LD-HCD", "BND-NHCD", "BND-HCD"}
    if "Product2BuyBack" not in df.columns:
        return {"has_data": False, "months": [], "legs": {}, "table": []}

    strat_rows = df[(df["Product2BuyBack"].isin(strategy_legs)) & (df["Indice"] == "PnL")].copy()
    if strat_rows.empty:
        return {"has_data": False, "months": [], "legs": {}, "table": []}

    months = sorted(strat_rows["Month"].unique())
    month_labels = _month_labels(months)

    # Shock=0 only for the chart
    base = strat_rows[strat_rows["Shock"] == "0"] if "Shock" in strat_rows.columns else strat_rows

    legs = {}
    for leg in sorted(strategy_legs):
        leg_data = base[base["Product2BuyBack"] == leg]
        by_month = leg_data.groupby("Month")["Value"].sum()
        legs[leg] = {
            "values": [round(float(by_month.get(m, 0.0)), 0) for m in months],
            "color": LEG_COLORS.get(leg, "#8b949e"),
        }

    # Detail table
    table = []
    nom_rows = df[(df["Product2BuyBack"].isin(strategy_legs)) & (df["Indice"] == "Nominal") & (df["Shock"] == "0")]
    rate_rows = df[(df["Product2BuyBack"].isin(strategy_legs)) & (df["Indice"] == "RateRef") & (df["Shock"] == "0")]
    ois_rows = df[(df["Product2BuyBack"].isin(strategy_legs)) & (df["Indice"] == "OISfwd") & (df["Shock"] == "0")]

    for leg in sorted(strategy_legs):
        pnl_total = base[base["Product2BuyBack"] == leg]["Value"].sum()
        leg_nom = nom_rows[nom_rows["Product2BuyBack"] == leg]["Value"]
        leg_rate = rate_rows[rate_rows["Product2BuyBack"] == leg]
        leg_ois = ois_rows[ois_rows["Product2BuyBack"] == leg]

        # Nominal-weighted averages for rates (avoid NaN on empty groups)
        nom_avg = float(leg_nom.mean()) if not leg_nom.empty else 0.0
        if not leg_rate.empty and not leg_nom.empty and len(leg_rate) == len(leg_nom):
            weights = leg_nom.abs().values
            w_sum = weights.sum()
            rate_avg = float((leg_rate["Value"].values * weights).sum() / w_sum) if w_sum > 0 else 0.0
        else:
            rate_avg = float(leg_rate["Value"].mean()) if not leg_rate.empty else 0.0

        if not leg_ois.empty and not leg_nom.empty and len(leg_ois) == len(leg_nom):
            weights = leg_nom.abs().values
            w_sum = weights.sum()
            ois_avg = float((leg_ois["Value"].values * weights).sum() / w_sum) if w_sum > 0 else 0.0
        else:
            ois_avg = float(leg_ois["Value"].mean()) if not leg_ois.empty else 0.0

        # Sanitize NaN → 0
        if np.isnan(nom_avg):
            nom_avg = 0.0
        if np.isnan(rate_avg):
            rate_avg = 0.0
        if np.isnan(ois_avg):
            ois_avg = 0.0

        currencies = base[base["Product2BuyBack"] == leg]["Deal currency"].unique() if "Deal currency" in base.columns else []
        directions = base[base["Product2BuyBack"] == leg]["Direction"].unique() if "Direction" in base.columns else []

        table.append({
            "leg": leg,
            "currency": ", ".join(sorted(currencies)),
            "direction": ", ".join(sorted(directions)),
            "pnl": round(float(pnl_total), 0),
            "nominal": round(nom_avg, 0),
            "rate_ref": round(rate_avg, 6),
            "ois_fwd": round(ois_avg, 6),
        })

    return {"has_data": True, "months": month_labels, "legs": legs, "table": table}


# ---------------------------------------------------------------------------
# Tab 6: BOOK2 MTM
# ---------------------------------------------------------------------------

def _build_book2(
    df: pd.DataFrame,
    irs_stock: pd.DataFrame | None,
) -> dict:
    """BOOK2 IRS MTM summary and deal-level detail."""
    result: dict = {"has_data": False, "summary": {}, "deals": []}

    if df.empty:
        return result

    mtm_rows = df[(df["Product2BuyBack"] == "IRS-MTM") & (df["Indice"] == "PnL")].copy()
    if mtm_rows.empty:
        return result

    result["has_data"] = True

    # Summary by currency × shock
    summary = {}
    if "Deal currency" in mtm_rows.columns:
        for ccy in sorted(mtm_rows["Deal currency"].unique()):
            ccy_data = mtm_rows[mtm_rows["Deal currency"] == ccy]
            by_shock = {}
            for shock in sorted(ccy_data["Shock"].unique()) if "Shock" in ccy_data.columns else ["0"]:
                by_shock[f"shock_{shock}"] = round(float(ccy_data[ccy_data["Shock"] == shock]["Value"].sum()), 0)
            summary[ccy] = by_shock

    result["summary"] = summary

    # Deal-level detail from irs_stock
    if irs_stock is not None and not irs_stock.empty:
        deals = []
        for _, row in irs_stock.head(50).iterrows():  # cap at 50 rows
            deals.append({
                "deal": str(row.get("Deal", row.get("Dealid", ""))),
                "currency": str(row.get("Currency Code (ISO)", row.get("Currency", ""))),
                "direction": str(row.get("Buy / Sell", row.get("Direction", ""))),
                "maturity": str(row.get("Maturity Date", row.get("Maturitydate", ""))),
                "mtm": round(float(row.get("MTM", 0)), 0),
            })
        result["deals"] = deals

    return result


# ---------------------------------------------------------------------------
# Tab 7: Rate Curves
# ---------------------------------------------------------------------------

def _build_curves(
    ois_curves: pd.DataFrame | None,
    wirp_curves: pd.DataFrame | None,
) -> dict:
    """OIS forward curves and WIRP overlay."""
    if ois_curves is None or ois_curves.empty:
        return {"has_data": False, "series": {}, "wirp_points": []}

    result: dict = {"has_data": True, "series": {}, "wirp_points": []}

    # Group by Indice (CHFSON, EUREST, USSOFR, GBPOIS)
    indice_to_ccy = {"CHFSON": "CHF", "EUREST": "EUR", "USSOFR": "USD", "GBPOIS": "GBP"}

    for indice, ccy in indice_to_ccy.items():
        sub = ois_curves[ois_curves["Indice"] == indice].sort_values("Date")
        if sub.empty:
            continue
        # Downsample to monthly for chart readability
        sub_monthly = sub.set_index("Date").resample("ME").last().dropna(subset=["value"]).reset_index()
        result["series"][ccy] = {
            "dates": [str(d.date()) for d in sub_monthly["Date"]],
            "values": [round(float(v) * 100, 4) for v in sub_monthly["value"]],  # convert to %
            "color": CURRENCY_COLORS.get(ccy, "#8b949e"),
        }

    # WIRP meeting points
    if wirp_curves is not None and not wirp_curves.empty:
        wirp_points = []
        for indice, ccy in indice_to_ccy.items():
            sub = wirp_curves[wirp_curves["Indice"] == indice]
            if sub.empty:
                continue
            # WIRP curves have Meeting/Rate columns if they came from overlay
            if "Meeting" in sub.columns:
                meetings = sub.dropna(subset=["Meeting"]).drop_duplicates("Meeting")
                for _, row in meetings.iterrows():
                    wirp_points.append({
                        "date": str(row["Meeting"].date()) if hasattr(row["Meeting"], "date") else str(row["Meeting"]),
                        "currency": ccy,
                        "rate": round(float(row.get("Rate", row.get("value", 0))) * 100, 4),
                    })
        result["wirp_points"] = wirp_points

    return result


# ---------------------------------------------------------------------------
# Tab 8: Currency Mismatch (F9)
# ---------------------------------------------------------------------------

def _build_currency_mismatch(df: pd.DataFrame) -> dict:
    """Asset/liability gap by currency by month."""
    if df.empty:
        return {"has_data": False, "months": [], "by_currency": {}}

    nom_rows = df[(df["Indice"] == "Nominal") & (df["Shock"] == "0")].copy()
    if nom_rows.empty or "Direction" not in nom_rows.columns:
        return {"has_data": False, "months": [], "by_currency": {}}

    # Map direction to asset/liability: L(end)/B(uy) = asset, D(eposit)/S(ell) = liability
    nom_rows["_side"] = nom_rows["Direction"].map({"L": "asset", "B": "asset", "D": "liability", "S": "liability"})
    nom_rows["_side"] = nom_rows["_side"].fillna("asset")

    months = sorted(nom_rows["Month"].unique())
    month_labels = _month_labels(months)
    currencies = sorted(nom_rows["Deal currency"].unique()) if "Deal currency" in nom_rows.columns else []

    by_currency = {}
    for ccy in currencies:
        ccy_data = nom_rows[nom_rows["Deal currency"] == ccy]
        assets_by_month = ccy_data[ccy_data["_side"] == "asset"].groupby("Month")["Value"].sum()
        liab_by_month = ccy_data[ccy_data["_side"] == "liability"].groupby("Month")["Value"].sum()
        assets = [round(float(assets_by_month.get(m, 0)), 0) for m in months]
        liabs = [round(float(liab_by_month.get(m, 0)), 0) for m in months]
        gap = [a - l for a, l in zip(assets, liabs)]
        by_currency[ccy] = {"assets": assets, "liabilities": liabs, "gap": gap}

    # Net across all currencies
    all_assets = [sum(by_currency[c]["assets"][i] for c in currencies) for i in range(len(months))]
    all_liabs = [sum(by_currency[c]["liabilities"][i] for c in currencies) for i in range(len(months))]
    by_currency["All"] = {
        "assets": all_assets,
        "liabilities": all_liabs,
        "gap": [a - l for a, l in zip(all_assets, all_liabs)],
    }

    # Basis risk: OIS forward spread between currencies (e.g., EUR-CHF, USD-CHF)
    basis_risk = {}
    ois_rows = _filter_total(df[(df["Indice"] == "OISfwd") & (df["Shock"] == "0")])
    if not ois_rows.empty and "Deal currency" in ois_rows.columns:
        ois_by_ccy = {}
        for ccy in currencies:
            ccy_ois = ois_rows[ois_rows["Deal currency"] == ccy]
            # Nominal-weighted OIS per month
            nom_ccy = nom_rows[(nom_rows["Deal currency"] == ccy)]
            ois_monthly = ccy_ois.groupby("Month")["Value"].mean()
            ois_by_ccy[ccy] = {m: float(ois_monthly.get(m, 0)) for m in months}

        # Compute spreads relative to CHF (home currency)
        home = "CHF"
        if home in ois_by_ccy:
            for ccy in currencies:
                if ccy == home:
                    continue
                spread = []
                for m in months:
                    s = (ois_by_ccy.get(ccy, {}).get(m, 0) - ois_by_ccy[home].get(m, 0)) * 10_000
                    spread.append(round(s, 1))
                basis_risk[f"{ccy}-{home}"] = {
                    "values": spread,
                    "color": CURRENCY_COLORS.get(ccy, "#8b949e"),
                }

    return {"has_data": True, "months": month_labels, "by_currency": by_currency, "basis_risk": basis_risk}


# ---------------------------------------------------------------------------
# Tab 9: Repricing Gap (F3)
# ---------------------------------------------------------------------------

def _build_repricing_gap(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
) -> dict:
    """Repricing gap profile by bucket and currency."""
    if deals is None or deals.empty:
        return {"has_data": False, "buckets": [], "by_currency": {}}

    try:
        from pnl_engine.repricing import compute_repricing_gap
        gap_df = compute_repricing_gap(deals, pd.DataFrame(), date_run or datetime.now())
    except Exception as e:
        logger.warning(f"Repricing gap computation failed: {e}")
        return {"has_data": False, "buckets": [], "by_currency": {}}

    if gap_df.empty:
        return {"has_data": False, "buckets": [], "by_currency": {}}

    buckets = gap_df[gap_df["currency"] == gap_df["currency"].iloc[0]]["bucket"].tolist()

    by_currency = {}
    for ccy in sorted(gap_df["currency"].unique()):
        ccy_df = gap_df[gap_df["currency"] == ccy].sort_values("bucket_order")
        by_currency[ccy] = {
            "assets": [round(v, 0) for v in ccy_df["assets"].tolist()],
            "liabilities": [round(v, 0) for v in ccy_df["liabilities"].tolist()],
            "gap": [round(v, 0) for v in ccy_df["gap"].tolist()],
            "cumulative_gap": [round(v, 0) for v in ccy_df["cumulative_gap"].tolist()],
        }

    # Aggregate all currencies
    all_assets = [0.0] * len(buckets)
    all_liabs = [0.0] * len(buckets)
    for ccy_data in by_currency.values():
        for i in range(len(buckets)):
            all_assets[i] += ccy_data["assets"][i]
            all_liabs[i] += ccy_data["liabilities"][i]
    all_gap = [a - l for a, l in zip(all_assets, all_liabs)]
    cum = []
    running = 0
    for g in all_gap:
        running += g
        cum.append(round(running, 0))
    by_currency["All"] = {
        "assets": [round(v, 0) for v in all_assets],
        "liabilities": [round(v, 0) for v in all_liabs],
        "gap": [round(v, 0) for v in all_gap],
        "cumulative_gap": cum,
    }

    return {"has_data": True, "buckets": buckets, "by_currency": by_currency}


# ---------------------------------------------------------------------------
# Tab 10: Counterparty P&L Concentration (F8)
# ---------------------------------------------------------------------------

def _build_counterparty_pnl(df: pd.DataFrame, pnl_by_deal: Optional[pd.DataFrame] = None) -> dict:
    """P&L concentration by counterparty.

    Uses pnl_by_deal (deal-level summary) when available, since the aggregated
    pnlAllS drops Counterparty during pivot. Falls back to df if it has Counterparty.
    """
    empty = {"has_data": False, "top_10": [], "hhi": 0, "by_product": {}}

    # Prefer pnl_by_deal which preserves deal-level columns
    source = None
    if pnl_by_deal is not None and not pnl_by_deal.empty and "Counterparty" in pnl_by_deal.columns:
        source = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy()
        pnl_col = "PnL"
        cpty_col = "Counterparty"
        prod_col = "Product2BuyBack" if "Product2BuyBack" in source.columns else "Product"
    elif not df.empty and "Counterparty" in df.columns:
        source = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")].copy()
        pnl_col = "Value"
        cpty_col = "Counterparty"
        prod_col = "Product2BuyBack"
    else:
        return empty

    if source.empty:
        return empty

    # Group by counterparty
    cpty_pnl = source.groupby(cpty_col)[pnl_col].sum().reset_index()
    cpty_pnl.columns = ["Counterparty", "Value"]
    cpty_pnl["abs_val"] = cpty_pnl["Value"].abs()
    total = cpty_pnl["abs_val"].sum()

    if total == 0:
        return empty

    # HHI on PnL shares
    cpty_pnl["share_pct"] = (cpty_pnl["abs_val"] / total) * 100
    hhi = float((cpty_pnl["share_pct"] ** 2).sum())

    # Top 10
    top = cpty_pnl.nlargest(10, "abs_val")
    top_10 = []
    for _, row in top.iterrows():
        top_10.append({
            "counterparty": str(row["Counterparty"]),
            "pnl": round(float(row["Value"]), 0),
            "pct": round(float(row["share_pct"]), 1),
        })

    # Product breakdown
    by_product = {}
    if prod_col in source.columns:
        prod_pnl = source.groupby(prod_col)[pnl_col].sum()
        for prod, val in prod_pnl.items():
            by_product[str(prod)] = {
                "value": round(float(val), 0),
                "color": PRODUCT_COLORS.get(str(prod), "#8b949e"),
            }

    return {"has_data": True, "top_10": top_10, "hhi": round(hhi, 0), "by_product": by_product}


# ---------------------------------------------------------------------------
# Tab 11: P&L Alerts (F7)
# ---------------------------------------------------------------------------

def _build_pnl_alerts(df: pd.DataFrame, alert_thresholds: Optional[dict] = None) -> dict:
    """Generate P&L alerts from data."""
    if df.empty:
        return {"has_data": False, "alerts": [], "summary": {"critical": 0, "high": 0, "medium": 0}}

    from cockpit.engine.alerts.pnl_alerts import check_pnl_alerts

    # Build thresholds dict with per-currency support
    thresholds = None
    if alert_thresholds:
        thresholds = dict(alert_thresholds.get("ALL", {}))
        per_ccy = {k: v for k, v in alert_thresholds.items() if k != "ALL"}
        if per_ccy:
            thresholds["_per_currency"] = per_ccy

    alerts = check_pnl_alerts(df, thresholds)

    summary = {"critical": 0, "high": 0, "medium": 0}
    for a in alerts:
        sev = a.get("severity", "medium")
        if sev in summary:
            summary[sev] += 1

    return {"has_data": len(alerts) > 0, "alerts": alerts, "summary": summary}


# ---------------------------------------------------------------------------
# Tab 17: EVE (Economic Value of Equity)
# ---------------------------------------------------------------------------

def _build_eve(
    eve_results: Optional[pd.DataFrame] = None,
    eve_scenarios: Optional[pd.DataFrame] = None,
    eve_krd: Optional[pd.DataFrame] = None,
    limits: Optional[pd.DataFrame] = None,
) -> dict:
    """Build EVE dashboard data: base EVE, ΔEVE heatmap, duration, KRD, IRRBB outlier test."""
    if eve_results is None or eve_results.empty:
        return {"has_data": False, "total_eve": 0, "by_currency": {},
                "scenarios": {}, "krd": {}, "duration": {}}

    # --- Total EVE and by currency ---
    total_eve = round(float(eve_results["eve"].sum()), 0)
    ccy_col = "Currency" if "Currency" in eve_results.columns else None
    by_currency = {}
    if ccy_col:
        for ccy, grp in eve_results.groupby(ccy_col):
            by_currency[ccy] = {
                "eve": round(float(grp["eve"].sum()), 0),
                "duration": round(float(
                    (grp["duration"] * grp["notional_avg"]).sum() /
                    max(grp["notional_avg"].sum(), 1e-6)
                ), 2),
                "deal_count": len(grp),
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            }

    # --- Scenario ΔEVE heatmap ---
    scenarios_data = {}
    if eve_scenarios is not None and not eve_scenarios.empty:
        scenario_names = sorted(eve_scenarios["scenario"].unique())
        currencies = sorted(eve_scenarios["currency"].unique())
        heatmap = []
        for sc in scenario_names:
            row = {"scenario": sc}
            sc_data = eve_scenarios[eve_scenarios["scenario"] == sc]
            for ccy in currencies:
                ccy_row = sc_data[sc_data["currency"] == ccy]
                if not ccy_row.empty:
                    row[ccy] = round(float(ccy_row.iloc[0]["delta_eve"]), 0)
                else:
                    row[ccy] = 0
            row["total"] = sum(row.get(c, 0) for c in currencies)
            heatmap.append(row)

        # Worst case
        totals = {sc: sum(
            eve_scenarios.loc[eve_scenarios["scenario"] == sc, "delta_eve"]
        ) for sc in scenario_names}
        worst_sc = min(totals, key=totals.get) if totals else ""
        worst_delta = round(float(totals.get(worst_sc, 0)), 0)

        scenarios_data = {
            "scenario_names": scenario_names,
            "currencies": currencies,
            "heatmap": heatmap,
            "worst_scenario": worst_sc,
            "worst_delta": worst_delta,
            "eve_base_total": total_eve,
        }

    # --- KRD chart data ---
    krd_data = {}
    if eve_krd is not None and not eve_krd.empty:
        tenors = sorted(eve_krd["tenor_years"].unique())
        tenor_labels = []
        for _, row in eve_krd.drop_duplicates("tenor").sort_values("tenor_years").iterrows():
            tenor_labels.append(row["tenor"])
        currencies_krd = sorted(eve_krd["currency"].unique())
        datasets = []
        for ccy in currencies_krd:
            ccy_krd = eve_krd[eve_krd["currency"] == ccy].sort_values("tenor_years")
            datasets.append({
                "label": ccy,
                "data": [round(float(v), 4) for v in ccy_krd["krd"].values],
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            })
        krd_data = {
            "tenors": tenor_labels,
            "datasets": datasets,
        }

    # --- Duration profile ---
    duration_data = {}
    if ccy_col:
        dur_labels = []
        dur_values = []
        dur_colors = []
        for ccy in sorted(by_currency.keys()):
            dur_labels.append(str(ccy))
            dur_values.append(by_currency[ccy]["duration"])
            dur_colors.append(by_currency[ccy]["color"])
        duration_data = {"labels": dur_labels, "values": dur_values, "colors": dur_colors}

    # --- EVE Tenor Ladder (bucket by deal maturity into BCBS tenor bands) ---
    tenor_ladder = {}
    if ccy_col and "duration" in eve_results.columns:
        # BCBS tenor buckets based on modified duration as proxy for maturity
        tenor_buckets = [
            ("O/N", 0, 0.01),
            ("≤3M", 0.01, 0.25),
            ("3M-6M", 0.25, 0.5),
            ("6M-1Y", 0.5, 1.0),
            ("1Y-2Y", 1.0, 2.0),
            ("2Y-3Y", 2.0, 3.0),
            ("3Y-5Y", 3.0, 5.0),
            ("5Y-10Y", 5.0, 10.0),
            ("10Y-20Y", 10.0, 20.0),
            (">20Y", 20.0, 999.0),
        ]
        bucket_labels = [b[0] for b in tenor_buckets]
        currencies_in_eve = sorted(by_currency.keys())
        datasets = []
        for ccy in currencies_in_eve:
            ccy_deals = eve_results[eve_results[ccy_col] == ccy]
            bucket_values = []
            for _, lo, hi in tenor_buckets:
                mask = (ccy_deals["duration"] >= lo) & (ccy_deals["duration"] < hi)
                bucket_values.append(round(float(ccy_deals.loc[mask, "eve"].sum()), 0))
            datasets.append({
                "label": str(ccy),
                "data": bucket_values,
                "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
            })
        tenor_ladder = {"buckets": bucket_labels, "datasets": datasets}

    # --- IRRBB Outlier Test (BCBS 368: ΔEVE / Tier1 > 15% = outlier) ---
    outlier_test = None
    tier1 = None
    if limits is not None and not limits.empty:
        t1_rows = limits[limits["metric"].str.strip() == "tier1_capital"]
        if not t1_rows.empty:
            tier1 = float(t1_rows.iloc[0]["limit_value"])

    if tier1 and tier1 > 0 and scenarios_data:
        outlier_rows = []
        worst_pct = 0.0
        is_outlier = False
        for row in scenarios_data.get("heatmap", []):
            delta = abs(float(row.get("total", 0)))
            pct_of_t1 = (delta / tier1) * 100
            passed = pct_of_t1 <= 15.0
            if pct_of_t1 > worst_pct:
                worst_pct = pct_of_t1
            if not passed:
                is_outlier = True
            outlier_rows.append({
                "scenario": row["scenario"],
                "delta_eve": round(float(row.get("total", 0)), 0),
                "pct_of_tier1": round(pct_of_t1, 2),
                "passed": passed,
            })
        outlier_test = {
            "tier1_capital": round(tier1, 0),
            "threshold_pct": 15.0,
            "is_outlier": is_outlier,
            "worst_pct": round(worst_pct, 2),
            "scenarios": outlier_rows,
        }

    # --- Convexity / Gamma measurement from parallel scenarios ---
    convexity = None
    if scenarios_data and scenarios_data.get("heatmap"):
        hm = scenarios_data["heatmap"]
        # Find parallel_up and parallel_down scenarios
        up_row = next((r for r in hm if "parallel" in r["scenario"].lower() and "up" in r["scenario"].lower()), None)
        down_row = next((r for r in hm if "parallel" in r["scenario"].lower() and "down" in r["scenario"].lower()), None)
        if up_row and down_row and total_eve != 0:
            delta_r = 0.02  # 200bp standard parallel shock
            delta_eve_up = float(up_row.get("total", 0))
            delta_eve_down = float(down_row.get("total", 0))
            # Duration ≈ -ΔEVE / (EVE × Δr), using average of up/down
            eff_duration = -(delta_eve_up - delta_eve_down) / (2 * total_eve * delta_r)
            # Convexity = (ΔEVE_up + ΔEVE_down) / (EVE × Δr²)
            eff_convexity = (delta_eve_up + delta_eve_down) / (total_eve * delta_r ** 2)
            # Per-currency convexity
            ccy_convexity = []
            currencies_sc = scenarios_data.get("currencies", [])
            for ccy in currencies_sc:
                ccy_eve = by_currency.get(ccy, {}).get("eve", 0)
                if ccy_eve == 0:
                    continue
                ccy_up = float(up_row.get(ccy, 0))
                ccy_down = float(down_row.get(ccy, 0))
                ccy_dur = -(ccy_up - ccy_down) / (2 * ccy_eve * delta_r)
                ccy_conv = (ccy_up + ccy_down) / (ccy_eve * delta_r ** 2)
                ccy_convexity.append({
                    "currency": ccy,
                    "eve": round(ccy_eve, 0),
                    "delta_eve_up": round(ccy_up, 0),
                    "delta_eve_down": round(ccy_down, 0),
                    "effective_duration": round(ccy_dur, 2),
                    "convexity": round(ccy_conv, 2),
                    "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
                })
            convexity = {
                "delta_eve_up": round(delta_eve_up, 0),
                "delta_eve_down": round(delta_eve_down, 0),
                "effective_duration": round(eff_duration, 2),
                "convexity": round(eff_convexity, 2),
                "by_currency": ccy_convexity,
            }

    # --- DV01/PV01 Ladder (sensitivity per 1bp per tenor bucket) ---
    dv01 = None
    if convexity and total_eve != 0:
        # DV01 = ΔEVE per 1bp ≈ Effective Duration × EVE × 0.0001
        total_dv01 = abs(convexity["effective_duration"]) * abs(total_eve) * 0.0001
        dv01_by_ccy = []
        for cc in (convexity.get("by_currency") or []):
            ccy_dv01 = abs(cc["effective_duration"]) * abs(cc["eve"]) * 0.0001
            dv01_by_ccy.append({
                "currency": cc["currency"],
                "eve": cc["eve"],
                "duration": cc["effective_duration"],
                "dv01": round(ccy_dv01, 0),
                "color": cc.get("color", "#8b949e"),
            })
        dv01 = {
            "total_dv01": round(total_dv01, 0),
            "by_currency": dv01_by_ccy,
        }

    return {
        "has_data": True,
        "total_eve": total_eve,
        "by_currency": by_currency,
        "scenarios": scenarios_data,
        "krd": krd_data,
        "duration": duration_data,
        "outlier_test": outlier_test,
        "tenor_ladder": tenor_ladder,
        "convexity": convexity,
        "dv01": dv01,
    }


# ---------------------------------------------------------------------------
# Limit Utilization
# ---------------------------------------------------------------------------

def _build_limit_utilization(
    df: pd.DataFrame,
    limits: Optional[pd.DataFrame] = None,
    eve_data: Optional[dict] = None,
    nii_at_risk_data: Optional[dict] = None,
) -> dict:
    """Compute limit utilization bars for dashboard display.

    Matches actual metric values against board-approved limits.
    """
    if limits is None or limits.empty:
        return {"has_data": False, "limit_items": []}

    items = []

    for _, lim in limits.iterrows():
        metric = str(lim["metric"]).strip()
        currency = str(lim.get("currency", "ALL")).strip().upper()
        limit_value = float(lim["limit_value"]) if pd.notna(lim["limit_value"]) else None
        warning_pct = float(lim.get("warning_pct", 80.0))

        if limit_value is None or limit_value == 0:
            continue

        actual = None
        label = metric.replace("_", " ").title()

        # Calculate actual values based on metric type
        if metric == "nii_sensitivity_50bp" and not df.empty:
            pnl_0 = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")]
            pnl_50 = df[(df["Indice"] == "PnL") & (df["Shock"] == "50")]
            if currency != "ALL":
                pnl_0 = pnl_0[pnl_0["Deal currency"] == currency]
                pnl_50 = pnl_50[pnl_50["Deal currency"] == currency]
            nii_0 = pnl_0["Value"].sum() if not pnl_0.empty else 0
            nii_50 = pnl_50["Value"].sum() if not pnl_50.empty else 0
            actual = abs(nii_50 - nii_0)
            label = f"NII Sensitivity +50bp" + (f" ({currency})" if currency != "ALL" else "")

        elif metric == "nii_at_risk_worst" and nii_at_risk_data:
            wc = nii_at_risk_data.get("worst_case", {})
            actual = abs(float(wc.get("delta", 0)))
            label = "NII-at-Risk (Worst)"

        elif metric == "eve_change_200bp" and eve_data:
            sc = eve_data.get("scenarios", {})
            if sc:
                for row in sc.get("heatmap", []):
                    if "parallel_up" in row.get("scenario", ""):
                        actual = abs(float(row.get("total", 0)))
                        break
            label = "EVE Change +200bp"

        elif metric == "eve_change_worst" and eve_data:
            sc = eve_data.get("scenarios", {})
            actual = abs(float(sc.get("worst_delta", 0))) if sc else None
            label = "EVE Change (Worst)"

        if actual is None:
            continue

        utilization_pct = (actual / abs(limit_value)) * 100
        status = "green"
        if utilization_pct >= 100:
            status = "red"
        elif utilization_pct >= warning_pct:
            status = "yellow"

        items.append({
            "metric": metric,
            "label": label,
            "currency": currency,
            "actual": round(float(actual), 0),
            "limit": round(float(limit_value), 0),
            "utilization_pct": round(float(utilization_pct), 1),
            "warning_pct": warning_pct,
            "status": status,
        })

    # Build breach log: items currently breaching or in warning zone
    breaches = [it for it in items if it["status"] == "red"]
    warnings = [it for it in items if it["status"] == "yellow"]
    breach_log = {
        "breach_count": len(breaches),
        "warning_count": len(warnings),
        "breaches": breaches,
        "warnings": warnings,
    }

    return {"has_data": len(items) > 0, "limit_items": items, "breach_log": breach_log}


# ---------------------------------------------------------------------------
# FTP & Business Unit P&L
# ---------------------------------------------------------------------------

PERIMETER_COLORS = {
    "CC": "#58a6ff",
    "WM": "#3fb950",
    "CIB": "#d29922",
}


def _build_ftp(
    df: pd.DataFrame,
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
) -> dict:
    """FTP margin decomposition by perimeter and currency.

    3-way split: Client Margin (ClientRate - FTP), ALM Margin (FTP - OIS),
    Total NII (ClientRate - OIS).
    """
    if deals is None or deals.empty or "FTP" not in deals.columns:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    ftp_deals = deals[deals["FTP"].notna() & (deals["FTP"] != 0)].copy()
    if ftp_deals.empty:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    # Use pnl_by_deal for deal-level P&L if available
    source = None
    if pnl_by_deal is not None and not pnl_by_deal.empty and "Dealid" in pnl_by_deal.columns:
        source = pnl_by_deal[pnl_by_deal["Shock"] == "0"].copy()

    # Compute per-deal FTP metrics
    records = []
    for _, deal in ftp_deals.iterrows():
        deal_id = deal.get("Dealid")
        ccy = str(deal.get("Currency", ""))
        perimeter = str(deal.get("Périmètre TOTAL", "CC"))
        product = str(deal.get("Product", ""))
        counterparty = str(deal.get("Counterparty", ""))
        client_rate = float(deal.get("Clientrate", 0) or 0)
        ftp_rate = float(deal.get("FTP", 0) or 0)
        eq_ois = float(deal.get("EqOisRate", 0) or 0)
        ytm = float(deal.get("YTM", 0) or 0)
        amount = float(deal.get("Amount", 0) or 0)

        # Rate used for OIS comparison depends on product
        ref_rate = ytm if product == "BND" else eq_ois

        # Margins in bps
        client_margin_bps = (client_rate - ftp_rate) * 10_000
        alm_margin_bps = (ftp_rate - ref_rate) * 10_000

        # Remaining maturity fraction (cap at 1.0 for annualized view)
        year_frac = 1.0
        mat_raw = deal.get("Maturity Date", deal.get("Maturitydate"))
        if mat_raw is not None and date_run is not None:
            try:
                mat_dt = pd.Timestamp(mat_raw)
                if pd.notna(mat_dt):
                    remaining = (mat_dt - pd.Timestamp(date_run)).days
                    year_frac = min(max(remaining / 365.0, 0.0), 1.0)
            except Exception:
                pass

        # P&L contribution pro-rated by remaining maturity (capped at 12 months)
        client_margin_pnl = amount * (client_rate - ftp_rate) * year_frac
        alm_margin_pnl = amount * (ftp_rate - ref_rate) * year_frac
        total_nii = client_margin_pnl + alm_margin_pnl

        # Get actual P&L from engine if available
        actual_pnl = 0.0
        if source is not None:
            match = source[source["Dealid"] == deal_id]
            if not match.empty:
                actual_pnl = float(match["PnL"].sum())

        records.append({
            "deal_id": str(int(deal_id)) if pd.notna(deal_id) else "",
            "currency": ccy,
            "perimeter": perimeter,
            "product": product,
            "counterparty": counterparty,
            "amount": round(amount, 0),
            "client_rate": round(client_rate * 100, 4),
            "ftp_rate": round(ftp_rate * 100, 4),
            "ref_rate": round(ref_rate * 100, 4),
            "client_margin_bps": round(client_margin_bps, 1),
            "alm_margin_bps": round(alm_margin_bps, 1),
            "client_margin_pnl": round(client_margin_pnl, 0),
            "alm_margin_pnl": round(alm_margin_pnl, 0),
            "total_nii": round(total_nii, 0),
            "actual_pnl": round(actual_pnl, 0),
        })

    if not records:
        return {"has_data": False, "perimeters": {}, "by_currency": {}, "top_deals": []}

    rdf = pd.DataFrame(records)

    # Aggregate by perimeter
    perimeters = {}
    for peri, grp in rdf.groupby("perimeter"):
        perimeters[str(peri)] = {
            "client_margin": round(float(grp["client_margin_pnl"].sum()), 0),
            "alm_margin": round(float(grp["alm_margin_pnl"].sum()), 0),
            "total_nii": round(float(grp["total_nii"].sum()), 0),
            "deal_count": len(grp),
            "avg_client_margin_bps": round(float(grp["client_margin_bps"].mean()), 1),
            "avg_alm_margin_bps": round(float(grp["alm_margin_bps"].mean()), 1),
            "color": PERIMETER_COLORS.get(str(peri), "#8b949e"),
        }

    # Aggregate by currency
    by_currency = {}
    for ccy, grp in rdf.groupby("currency"):
        by_currency[str(ccy)] = {
            "client_margin": round(float(grp["client_margin_pnl"].sum()), 0),
            "alm_margin": round(float(grp["alm_margin_pnl"].sum()), 0),
            "total_nii": round(float(grp["total_nii"].sum()), 0),
            "deal_count": len(grp),
            "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
        }

    # Top 10 deals by absolute FTP margin (contributors + detractors)
    rdf["abs_alm_margin"] = rdf["alm_margin_pnl"].abs()
    top = rdf.nlargest(10, "abs_alm_margin").drop(columns=["abs_alm_margin"])
    top_deals = top.to_dict("records")

    # Totals
    total_client = round(float(rdf["client_margin_pnl"].sum()), 0)
    total_alm = round(float(rdf["alm_margin_pnl"].sum()), 0)
    total_nii = round(float(rdf["total_nii"].sum()), 0)

    return {
        "has_data": True,
        "totals": {
            "client_margin": total_client,
            "alm_margin": total_alm,
            "total_nii": total_nii,
            "deal_count": len(rdf),
        },
        "perimeters": perimeters,
        "by_currency": by_currency,
        "top_deals": top_deals,
    }


# ---------------------------------------------------------------------------
# Liquidity Forecast
# ---------------------------------------------------------------------------

def _build_liquidity(
    liquidity_schedule: Optional[pd.DataFrame] = None,
    deals: Optional[pd.DataFrame] = None,
) -> dict:
    """Liquidity forecast from daily/monthly cash flow schedule.

    Input: wide DataFrame with Dealid, Direction, Currency, and date columns
    (YYYY/MM or YYYY/MM/DD) containing cash flow amounts.
    """
    import re

    if liquidity_schedule is None or liquidity_schedule.empty:
        return {"has_data": False, "by_currency": {}, "summary": {}, "top_maturities": []}

    df = liquidity_schedule.copy()
    date_col_re = re.compile(r"^\d{4}/\d{2}(/\d{2})?$")
    date_cols = [c for c in df.columns if isinstance(c, str) and date_col_re.match(c)]

    if not date_cols:
        return {"has_data": False, "by_currency": {}, "summary": {}, "top_maturities": []}

    # Parse date columns to timestamps for aggregation
    def _parse_col(c):
        parts = c.split("/")
        if len(parts) == 3:
            return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
        return pd.Timestamp(int(parts[0]), int(parts[1]), 1)

    col_dates = {c: _parse_col(c) for c in date_cols}
    sorted_cols = sorted(date_cols, key=lambda c: col_dates[c])

    # Identify asset vs liability by direction
    # L(end)/B(uy) = asset (inflow at maturity), D(eposit)/S(ell) = liability (outflow)
    if "Direction" in df.columns:
        df["_is_asset"] = df["Direction"].isin(["L", "B"])
    else:
        df["_is_asset"] = True  # default

    currencies = sorted(df["Currency"].unique()) if "Currency" in df.columns else ["ALL"]

    # Build per-currency time series
    by_currency = {}
    for ccy in currencies:
        ccy_df = df[df["Currency"] == ccy] if "Currency" in df.columns else df

        labels = []
        inflows = []
        outflows = []
        net = []
        cumulative = []
        cum = 0.0

        for col in sorted_cols:
            dt = col_dates[col]
            labels.append(dt.strftime("%Y-%m-%d") if "/" in col and col.count("/") == 2 else dt.strftime("%Y-%m"))

            # Assets (L/B): principal returning = inflow; Liabilities (D/S): repayment = outflow
            inflow = float(ccy_df.loc[ccy_df["_is_asset"], col].sum())
            outflow = float(-ccy_df.loc[~ccy_df["_is_asset"], col].sum())  # negate: unsigned → negative

            inflows.append(round(float(inflow), 0))
            outflows.append(round(float(outflow), 0))
            n = round(float(inflow + outflow), 0)
            net.append(n)
            cum += n
            cumulative.append(round(float(cum), 0))

        by_currency[ccy] = {
            "labels": labels,
            "inflows": inflows,
            "outflows": outflows,
            "net": net,
            "cumulative": cumulative,
            "color": CURRENCY_COLORS.get(str(ccy), "#8b949e"),
        }

    # Summary KPIs: aggregate across all currencies
    all_labels = []
    all_net = []
    cum = 0.0
    all_cumulative = []
    for col in sorted_cols:
        dt = col_dates[col]
        all_labels.append(dt)
        n = float(df[col].sum())
        all_net.append(n)
        cum += n
        all_cumulative.append(cum)

    # Net outflows for 7d, 30d, 90d windows
    now = pd.Timestamp.now()
    net_7d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=7))
    net_30d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=30))
    net_90d = sum(n for dt, n in zip(all_labels, all_net) if dt <= now + pd.Timedelta(days=90))

    # Survival days: first date where cumulative goes negative
    survival_days = None
    for dt, c in zip(all_labels, all_cumulative):
        if c < 0:
            survival_days = max(0, (dt - now).days)
            break

    # Top 10 largest single-date cash flows (maturities) in next 30 days
    top_maturities = []
    for _, row in df.iterrows():
        for col in sorted_cols:
            dt = col_dates[col]
            if dt > now + pd.Timedelta(days=30):
                break
            val = float(row[col])
            if abs(val) > 0:
                top_maturities.append({
                    "deal_id": str(int(row["Dealid"])) if pd.notna(row.get("Dealid")) else "",
                    "currency": str(row.get("Currency", "")),
                    "direction": str(row.get("Direction", "")),
                    "date": dt.strftime("%Y-%m-%d"),
                    "amount": round(val, 0),
                })

    # Sort by absolute amount descending, keep top 10
    top_maturities.sort(key=lambda x: abs(x["amount"]), reverse=True)
    top_maturities = top_maturities[:10]

    # Reinvestment what-if: maturing assets in 30/90d, book rate vs current OIS
    reinvestment = []
    if deals is not None and not deals.empty and "Currency" in deals.columns:
        ois_col = "EqOisRate"
        rate_col = "Clientrate"
        for _ois in [ois_col, "EqOISRate", "eqoisrate"]:
            if _ois in deals.columns:
                ois_col = _ois
                break
        if ois_col in deals.columns and rate_col in deals.columns:
            asset_mask = deals.get("Direction", pd.Series()).isin(["L", "B"])
            asset_deals = deals[asset_mask].copy()
            for ccy in currencies:
                ccy_deals = asset_deals[asset_deals["Currency"] == ccy]
                if ccy_deals.empty:
                    continue
                avg_book = float(ccy_deals[rate_col].mean()) if not ccy_deals[rate_col].isna().all() else 0
                avg_ois = float(ccy_deals[ois_col].mean()) if not ccy_deals[ois_col].isna().all() else 0
                # Volume maturing in 30d/90d (from top_maturities)
                vol_30d = sum(abs(m["amount"]) for m in top_maturities if m["currency"] == ccy and m["direction"] in ("L", "B"))
                if vol_30d > 0 and avg_ois != 0:
                    spread_bps = (avg_ois - avg_book) * 10_000
                    nii_impact = vol_30d * (avg_ois - avg_book)
                    reinvestment.append({
                        "currency": ccy,
                        "maturing_volume": round(vol_30d, 0),
                        "book_rate_pct": round(avg_book * 100, 4),
                        "market_rate_pct": round(avg_ois * 100, 4),
                        "spread_bps": round(spread_bps, 1),
                        "nii_impact": round(nii_impact, 0),
                    })

    return {
        "has_data": True,
        "by_currency": by_currency,
        "all_currencies": currencies,
        "summary": {
            "net_7d": round(float(net_7d), 0),
            "net_30d": round(float(net_30d), 0),
            "net_90d": round(float(net_90d), 0),
            "survival_days": survival_days,
        },
        "top_maturities": top_maturities,
        "reinvestment": reinvestment,
    }


# ---------------------------------------------------------------------------
# NMD Audit Trail
# ---------------------------------------------------------------------------

def _build_nmd_audit(
    deals: Optional[pd.DataFrame],
    nmd_profiles: Optional[pd.DataFrame],
) -> dict:
    """Build NMD matching audit trail for dashboard display.

    Shows which deals matched which NMD profile tier, with key parameters.
    """
    if deals is None or nmd_profiles is None or nmd_profiles.empty:
        return {"has_data": False}

    profiles = nmd_profiles.copy()
    for col in ["product", "currency", "direction"]:
        if col in profiles.columns:
            profiles[col] = profiles[col].str.strip().str.upper()

    match_log = []
    for i in range(len(deals)):
        deal = deals.iloc[i]
        deal_id = str(deal.get("Dealid", f"idx_{i}"))
        product = str(deal.get("Product", "")).strip().upper()
        currency = str(deal.get("Currency", "")).strip().upper()
        direction = str(deal.get("Direction", "")).strip().upper()
        nominal = float(deal.get("Nominal", 0))

        mask = pd.Series([True] * len(profiles))
        if "product" in profiles.columns:
            mask &= profiles["product"] == product
        if "currency" in profiles.columns:
            mask &= profiles["currency"] == currency
        if "direction" in profiles.columns:
            mask &= profiles["direction"] == direction

        matched = profiles[mask]
        if matched.empty:
            continue

        profile = matched.iloc[0]
        tier = str(profile.get("tier", "unknown"))
        decay_rate = float(profile.get("decay_rate", 0.0))
        deposit_beta = float(profile.get("deposit_beta", 1.0))
        floor_rate = float(profile.get("floor_rate", 0.0))
        behavioral_maturity = float(profile.get("behavioral_maturity_years", 0.0))

        match_log.append({
            "deal_id": deal_id,
            "product": product,
            "currency": currency,
            "direction": direction,
            "nominal": nominal,
            "tier": tier,
            "decay_rate": decay_rate,
            "deposit_beta": deposit_beta,
            "floor_rate": floor_rate,
            "behavioral_maturity_years": behavioral_maturity,
        })

    if not match_log:
        return {"has_data": False}

    match_df = pd.DataFrame(match_log)

    # Summary by tier
    tier_summary = []
    for tier, grp in match_df.groupby("tier"):
        tier_summary.append({
            "tier": tier,
            "deal_count": len(grp),
            "total_nominal": float(grp["nominal"].sum()),
            "avg_decay_rate": float(grp["decay_rate"].mean()),
            "avg_beta": float(grp["deposit_beta"].mean()),
            "avg_behavioral_maturity": float(grp["behavioral_maturity_years"].mean()),
        })

    # Summary by currency × tier
    ccy_tier_summary = []
    for (ccy, tier), grp in match_df.groupby(["currency", "tier"]):
        ccy_tier_summary.append({
            "currency": ccy,
            "tier": tier,
            "deal_count": len(grp),
            "total_nominal": float(grp["nominal"].sum()),
            "avg_beta": float(grp["deposit_beta"].mean()),
        })

    # Chart data: stacked bar by currency, colored by tier
    tier_colors = {
        "CORE": "#3fb950",
        "VOLATILE": "#d29922",
        "TERM": "#58a6ff",
    }
    currencies = sorted(match_df["currency"].unique())
    tiers = sorted(match_df["tier"].unique())
    chart_datasets = []
    for tier in tiers:
        data = []
        for ccy in currencies:
            sub = match_df[(match_df["currency"] == ccy) & (match_df["tier"] == tier)]
            data.append(float(sub["nominal"].sum()))
        chart_datasets.append({
            "label": tier.title(),
            "data": data,
            "color": tier_colors.get(tier, "#8b949e"),
        })

    # Unmatched deals count
    total_deals = len(deals)
    matched_deals = len(match_log)
    unmatched_deals = total_deals - matched_deals

    # Deal-level detail (first 50 for display)
    deal_details = match_log[:50]

    return {
        "has_data": True,
        "total_deals": total_deals,
        "matched_deals": matched_deals,
        "unmatched_deals": unmatched_deals,
        "tier_summary": tier_summary,
        "ccy_tier_summary": ccy_tier_summary,
        "chart": {
            "currencies": currencies,
            "datasets": chart_datasets,
        },
        "deal_details": deal_details,
        "profiles": [
            {
                "product": str(r.get("product", "")),
                "currency": str(r.get("currency", "")),
                "direction": str(r.get("direction", "")),
                "tier": str(r.get("tier", "")),
                "decay_rate": float(r.get("decay_rate", 0)),
                "deposit_beta": float(r.get("deposit_beta", 1)),
                "floor_rate": float(r.get("floor_rate", 0)),
                "behavioral_maturity_years": float(r.get("behavioral_maturity_years", 0)),
            }
            for _, r in nmd_profiles.iterrows()
        ],
    }


# ---------------------------------------------------------------------------
# ALCO Risk Summary (reads from all other tabs)
# ---------------------------------------------------------------------------

def _build_alco(result: dict) -> dict:
    """Single-screen ALCO risk dashboard consolidating all key metrics.

    This runs AFTER all other tab builders, reading from the result dict.
    """
    metrics = []
    lim_items = result.get("limits", {}).get("limit_items", [])

    # 1. Total NII (base)
    summary = result.get("summary", {})
    kpis = summary.get("kpis", {})
    shock_0 = kpis.get("shock_0", {})
    if shock_0:
        dod = summary.get("dod_bridge", [])
        total_row = next((r for r in (dod or []) if r["currency"] == "Total"), None)
        metrics.append({
            "metric": "Total NII (Base)",
            "value": shock_0.get("total", 0),
            "delta_1d": total_row["delta"] if total_row else None,
            "limit": None,
            "utilization": None,
            "status": "neutral",
        })

    # 2. NII Sensitivity (+50bp)
    delta_50 = kpis.get("delta_50_0", 0)
    if delta_50 != 0:
        nii_sens_lim = next((i for i in lim_items if i["metric"] == "nii_sensitivity_50bp"), None)
        metrics.append({
            "metric": "NII Sensitivity (+50bp)",
            "value": delta_50,
            "delta_1d": None,
            "limit": nii_sens_lim["limit"] if nii_sens_lim else None,
            "utilization": nii_sens_lim["utilization_pct"] if nii_sens_lim else None,
            "status": nii_sens_lim["status"] if nii_sens_lim else "neutral",
        })

    # 3. Worst ΔNII (BCBS scenarios)
    nii_risk = result.get("nii_at_risk", {})
    if nii_risk.get("has_data"):
        wc = nii_risk.get("worst_case", {})
        nii_risk_lim = next((i for i in lim_items if i["metric"] == "nii_at_risk_worst"), None)
        metrics.append({
            "metric": f"Worst ΔNII ({wc.get('scenario', '')})",
            "value": wc.get("delta", 0),
            "delta_1d": None,
            "limit": nii_risk_lim["limit"] if nii_risk_lim else None,
            "utilization": nii_risk_lim["utilization_pct"] if nii_risk_lim else None,
            "status": nii_risk_lim["status"] if nii_risk_lim else "neutral",
        })

    # 4. Worst ΔEVE (BCBS scenarios)
    eve = result.get("eve", {})
    if eve.get("has_data"):
        sc = eve.get("scenarios", {})
        if sc:
            eve_lim = next((i for i in lim_items if i["metric"] == "eve_change_worst"), None)
            metrics.append({
                "metric": f"Worst ΔEVE ({sc.get('worst_scenario', '')})",
                "value": sc.get("worst_delta", 0),
                "delta_1d": None,
                "limit": eve_lim["limit"] if eve_lim else None,
                "utilization": eve_lim["utilization_pct"] if eve_lim else None,
                "status": eve_lim["status"] if eve_lim else "neutral",
            })

        # 5. Effective Duration & DGAP
        by_ccy = eve.get("by_currency", {})
        conv = eve.get("convexity", {})
        if conv:
            eff_dur = conv.get("effective_duration", 0)
            metrics.append({
                "metric": "Effective Duration",
                "value": eff_dur,
                "delta_1d": None,
                "limit": None,
                "utilization": None,
                "status": "green" if abs(eff_dur) < 3 else "yellow" if abs(eff_dur) < 5 else "red",
                "unit": "Y",
            })
            # DGAP approximation: ΔEVE per 100bp / Total EVE gives duration sensitivity
            total_eve = eve.get("total_eve", 0)
            if total_eve and sc:
                delta_eve_up = sc.get("parallel_up_delta", sc.get("worst_delta", 0))
                dgap = abs(delta_eve_up) / abs(total_eve) / 0.02 if total_eve != 0 else 0
                dgap_lim = next((i for i in lim_items if i["metric"] == "dgap"), None)
                metrics.append({
                    "metric": "DGAP (Duration Gap)",
                    "value": round(dgap, 2),
                    "delta_1d": None,
                    "limit": dgap_lim["limit"] if dgap_lim else None,
                    "utilization": dgap_lim["utilization_pct"] if dgap_lim else None,
                    "status": dgap_lim["status"] if dgap_lim else ("green" if dgap < 2 else "yellow" if dgap < 4 else "red"),
                    "unit": "Y",
                })
        elif by_ccy:
            total_dur = sum(d["duration"] * abs(d["eve"]) for d in by_ccy.values()) / max(sum(abs(d["eve"]) for d in by_ccy.values()), 1e-6)
            metrics.append({
                "metric": "Portfolio Duration",
                "value": round(total_dur, 2),
                "delta_1d": None,
                "limit": None,
                "utilization": None,
                "status": "neutral",
                "unit": "Y",
            })

    # 6. HHI (counterparty concentration)
    cpty = result.get("counterparty_pnl", {})
    if cpty.get("has_data"):
        metrics.append({
            "metric": "Counterparty HHI",
            "value": cpty.get("hhi", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "green" if cpty.get("hhi", 0) < 1500 else "yellow" if cpty.get("hhi", 0) < 2500 else "red",
        })

    # 7. Hedge effectiveness
    hedge = result.get("hedge", {})
    if hedge.get("has_data"):
        h_sum = hedge.get("summary", {})
        failing = h_sum.get("fail", 0)
        total_pairs = h_sum.get("total", 0)
        metrics.append({
            "metric": "Hedge Pairs Failing",
            "value": failing,
            "delta_1d": None,
            "limit": 0,
            "utilization": None,
            "status": "red" if failing > 0 else "green",
            "display": f"{failing}/{total_pairs}",
        })

    # 8. Liquidity 30d
    liq = result.get("liquidity", {})
    if liq.get("has_data"):
        liq_sum = liq.get("summary", {})
        metrics.append({
            "metric": "Liquidity Net 30d",
            "value": liq_sum.get("net_30d", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if liq_sum.get("net_30d", 0) < 0 else "green",
        })

    # 9. FTP ALM Margin
    ftp = result.get("ftp", {})
    if ftp.get("has_data"):
        metrics.append({
            "metric": "ALM Margin (FTP)",
            "value": ftp["totals"].get("alm_margin", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if ftp["totals"].get("alm_margin", 0) < 0 else "green",
        })

    # 10. Alert counts
    alerts = result.get("pnl_alerts", {})
    if alerts.get("has_data"):
        a_sum = alerts.get("summary", {})
        metrics.append({
            "metric": "Active Alerts",
            "value": a_sum.get("critical", 0) + a_sum.get("high", 0) + a_sum.get("medium", 0),
            "delta_1d": None,
            "limit": None,
            "utilization": None,
            "status": "red" if a_sum.get("critical", 0) > 0 else "yellow" if a_sum.get("high", 0) > 0 else "green",
            "display": f"{a_sum.get('critical', 0)}C / {a_sum.get('high', 0)}H / {a_sum.get('medium', 0)}M",
        })

    return {"has_data": len(metrics) > 0, "metrics": metrics}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_pnl_dashboard_data(
    pnl_all: pd.DataFrame,
    pnl_all_s: pd.DataFrame,
    ois_curves: Optional[pd.DataFrame] = None,
    wirp_curves: Optional[pd.DataFrame] = None,
    irs_stock: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
    date_rates: Optional[datetime] = None,
    # Wave 1 optional inputs
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    # Wave 2 optional inputs
    budget: Optional[pd.DataFrame] = None,
    hedge_pairs: Optional[pd.DataFrame] = None,
    # Wave 3 optional inputs
    prev_pnl_all_s: Optional[pd.DataFrame] = None,
    forecast_history: Optional[pd.DataFrame] = None,
    scenarios_data: Optional[pd.DataFrame] = None,
    # Configuration
    alert_thresholds: Optional[dict] = None,
    # EVE data
    eve_results: Optional[pd.DataFrame] = None,
    eve_scenarios: Optional[pd.DataFrame] = None,
    eve_krd: Optional[pd.DataFrame] = None,
    # Limits
    limits: Optional[pd.DataFrame] = None,
    # P&L Explain
    pnl_explain: Optional[dict] = None,
    # Liquidity & FTP
    liquidity_schedule: Optional[pd.DataFrame] = None,
    # NMD profiles (for audit trail)
    nmd_profiles: Optional[pd.DataFrame] = None,
) -> dict:
    """Build all chart data for the P&L dashboard."""
    df = _safe_stacked(pnl_all_s)
    dr = date_rates or date_run or datetime.now()

    result = {
        # Original 7 tabs
        "summary": _build_summary(df, dr, _safe_stacked(prev_pnl_all_s) if prev_pnl_all_s is not None else None),
        "coc": _build_coc(df),
        "pnl_series": _build_pnl_series(df, dr),
        "sensitivity": _build_sensitivity(df),
        "strategy": _build_strategy(df),
        "book2": _build_book2(df, irs_stock),
        "curves": _build_curves(ois_curves, wirp_curves),
        # Wave 1
        "currency_mismatch": _build_currency_mismatch(df),
        "repricing_gap": _build_repricing_gap(df, deals, date_run),
        "counterparty_pnl": _build_counterparty_pnl(df, pnl_by_deal),
        "pnl_alerts": _build_pnl_alerts(df, alert_thresholds),
        # Wave 2
        "budget": _build_budget(df, budget),
        "hedge": _build_hedge_effectiveness(df, hedge_pairs, pnl_by_deal, scenarios_data),
        # Wave 3 (placeholders)
        "nii_at_risk": _build_nii_at_risk(df, scenarios_data),
        "forecast_tracking": _build_forecast_tracking(forecast_history),
        "attribution": _build_attribution(df, prev_pnl_all_s, pnl_explain),
        # EVE (Phase 2)
        "eve": _build_eve(eve_results, eve_scenarios, eve_krd, limits),
        # FTP & Liquidity
        "ftp": _build_ftp(df, deals, pnl_by_deal, date_run=date_run),
        "liquidity": _build_liquidity(liquidity_schedule, deals),
        # NMD audit trail
        "nmd_audit": _build_nmd_audit(deals, nmd_profiles),
    }

    # Limit utilization (needs eve + nii_at_risk computed first)
    result["limits"] = _build_limit_utilization(
        df, limits, result["eve"], result["nii_at_risk"],
    )

    # Inject FTP & liquidity alerts into existing alerts tab
    extra_alerts = []
    if result["liquidity"].get("has_data"):
        liq_sum = result["liquidity"]["summary"]
        if liq_sum.get("survival_days") is not None:
            extra_alerts.append({
                "type": "liquidity_deficit",
                "severity": "critical",
                "metric": "Liquidity Survival",
                "current": liq_sum["survival_days"],
                "threshold": 0,
                "message": f"Cumulative liquidity deficit in {liq_sum['survival_days']} days",
                "recommendation": "Review funding maturities and arrange contingent liquidity",
            })
        if liq_sum.get("net_30d", 0) < 0:
            extra_alerts.append({
                "type": "liquidity_30d",
                "severity": "high",
                "metric": "30-Day Net Outflow",
                "current": round(float(liq_sum["net_30d"]), 0),
                "threshold": 0,
                "message": f"Net cash outflow of {liq_sum['net_30d']:,.0f} in next 30 days",
                "recommendation": "Secure funding to cover upcoming maturities",
            })

    if result["ftp"].get("has_data"):
        ftp_totals = result["ftp"]["totals"]
        if ftp_totals.get("alm_margin", 0) < 0:
            extra_alerts.append({
                "type": "ftp_alm_negative",
                "severity": "high",
                "metric": "ALM Margin (FTP - OIS)",
                "current": round(float(ftp_totals["alm_margin"]), 0),
                "threshold": 0,
                "message": f"ALM margin is negative ({ftp_totals['alm_margin']:,.0f}): FTP below market funding cost",
                "recommendation": "Review FTP methodology or adjust transfer pricing rates",
            })

    if extra_alerts:
        alerts_data = result["pnl_alerts"]
        alerts_data["alerts"].extend(extra_alerts)
        alerts_data["has_data"] = True
        for a in extra_alerts:
            sev = a.get("severity", "medium")
            if sev in alerts_data["summary"]:
                alerts_data["summary"][sev] += 1

    # ALCO risk summary (reads from all other computed results)
    result["alco"] = _build_alco(result)

    return result


# ---------------------------------------------------------------------------
# Wave 2 & 3 stubs (will be implemented in subsequent steps)
# ---------------------------------------------------------------------------

def _build_budget(df: pd.DataFrame, budget: Optional[pd.DataFrame] = None) -> dict:
    """Budget vs actual comparison."""
    if budget is None or budget.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "ytd": {}}

    pnl = df[(df["Indice"] == "PnL") & (df["Shock"] == "0")] if not df.empty else pd.DataFrame()
    if pnl.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "ytd": {}}

    # Actual by currency × month
    actual_by_cm = pnl.groupby(["Deal currency", "Month"])["Value"].sum()

    months = sorted(budget["month"].unique()) if "month" in budget.columns else []
    currencies = sorted(budget["currency"].unique()) if "currency" in budget.columns else []
    month_labels = _month_labels(months)

    by_currency = {}
    ytd_actual = 0.0
    ytd_budget = 0.0

    for ccy in currencies:
        ccy_budget = budget[budget["currency"] == ccy]
        actuals = []
        budgets = []
        variances = []
        for m in months:
            bgt = ccy_budget[ccy_budget["month"] == m]["budget_nii"].sum()
            # Try to match month format
            act = 0.0
            for key_m in actual_by_cm.index:
                if key_m[0] == ccy and str(key_m[1]) == str(m):
                    act = actual_by_cm[key_m]
                    break
            actuals.append(round(float(act), 0))
            budgets.append(round(float(bgt), 0))
            variances.append(round(float(act - bgt), 0))
            ytd_actual += act
            ytd_budget += bgt

        by_currency[ccy] = {
            "actual": actuals,
            "budget": budgets,
            "variance": variances,
        }

    ytd = {
        "actual": round(float(ytd_actual), 0),
        "budget": round(float(ytd_budget), 0),
        "variance": round(float(ytd_actual - ytd_budget), 0),
        "variance_pct": round(float((ytd_actual - ytd_budget) / abs(ytd_budget) * 100), 1) if ytd_budget != 0 else 0,
    }

    return {"has_data": True, "months": month_labels, "by_currency": by_currency, "ytd": ytd}


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
        else:  # IFRS9 — economic relationship
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

    # Heatmap: scenario × currency → NII
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


def _build_forecast_tracking(forecast_history: Optional[pd.DataFrame] = None) -> dict:
    """Historical NII forecast evolution."""
    if forecast_history is None or (isinstance(forecast_history, pd.DataFrame) and forecast_history.empty):
        return {"has_data": False, "dates": [], "by_currency": {}, "total": []}

    dates = sorted(forecast_history["date"].unique()) if "date" in forecast_history.columns else []
    date_labels = [str(d) for d in dates]

    by_currency = {}
    if "currency" in forecast_history.columns:
        for ccy in sorted(forecast_history["currency"].unique()):
            ccy_data = forecast_history[forecast_history["currency"] == ccy].sort_values("date")
            by_currency[ccy] = [round(float(v), 0) for v in ccy_data["nii_forecast"].tolist()]

    totals = []
    for d in dates:
        d_data = forecast_history[forecast_history["date"] == d]
        totals.append(round(float(d_data["nii_forecast"].sum()), 0))

    return {"has_data": len(dates) > 0, "dates": date_labels, "by_currency": by_currency, "total": totals}


def _build_attribution(
    df: pd.DataFrame,
    prev_pnl_all_s: Optional[pd.DataFrame] = None,
    pnl_explain: Optional[dict] = None,
) -> dict:
    """P&L attribution / explain waterfall.

    If pnl_explain is provided (from compute_pnl_explain), uses the full
    waterfall decomposition. Otherwise falls back to basic rate×volume.
    """
    # Use full explain if available
    if pnl_explain is not None and pnl_explain.get("has_data"):
        return pnl_explain

    # Fallback: basic rate × volume decomposition (needs prev_pnl_all_s)
    if prev_pnl_all_s is None or (isinstance(prev_pnl_all_s, pd.DataFrame) and prev_pnl_all_s.empty):
        return {"has_data": False, "by_currency": {}, "waterfall": [], "summary": {}}

    prev = _safe_stacked(prev_pnl_all_s)
    if df.empty or prev.empty:
        return {"has_data": False, "by_currency": {}, "waterfall": [], "summary": {}}

    def _extract(frame, indice):
        rows = frame[(frame["Indice"] == indice) & (frame["Shock"] == "0")]
        if "Deal currency" in rows.columns:
            return rows.groupby("Deal currency")["Value"].sum()
        return pd.Series(dtype=float)

    curr_pnl = _extract(df, "PnL")
    prev_pnl = _extract(prev, "PnL")
    curr_nom = _extract(df, "Nominal")
    prev_nom = _extract(prev, "Nominal")
    curr_ois = _extract(df, "OISfwd")
    prev_ois = _extract(prev, "OISfwd")

    currencies = sorted(set(curr_pnl.index) | set(prev_pnl.index))
    by_currency = {}
    total_rate = 0
    total_volume = 0
    total_cross = 0

    for ccy in currencies:
        nom_old = prev_nom.get(ccy, 0)
        rate_old = prev_ois.get(ccy, 0)
        nom_new = curr_nom.get(ccy, 0)
        rate_new = curr_ois.get(ccy, 0)

        rate_effect = nom_old * (rate_new - rate_old)
        volume_effect = (nom_new - nom_old) * rate_old
        cross_term = (nom_new - nom_old) * (rate_new - rate_old)

        by_currency[ccy] = {
            "ois_prev": round(float(rate_old) * 10000, 1),
            "ois_curr": round(float(rate_new) * 10000, 1),
            "nominal_prev": round(float(nom_old), 0),
            "nominal_curr": round(float(nom_new), 0),
        }
        total_rate += rate_effect
        total_volume += volume_effect
        total_cross += cross_term

    prev_total = float(prev_pnl.sum())
    curr_total = float(curr_pnl.sum())
    residual = (curr_total - prev_total) - total_rate - total_volume - total_cross

    waterfall = [
        {"label": "Prev NII", "value": round(prev_total, 0), "type": "base"},
        {"label": "Rate Effect", "value": round(float(total_rate), 0), "type": "effect"},
        {"label": "Volume Effect", "value": round(float(total_volume), 0), "type": "effect"},
        {"label": "Rate\u00d7Volume", "value": round(float(total_cross), 0), "type": "effect"},
        {"label": "Residual", "value": round(float(residual), 0), "type": "effect"},
        {"label": "Current NII", "value": round(curr_total, 0), "type": "total"},
    ]

    return {
        "has_data": len(by_currency) > 0,
        "by_currency": by_currency,
        "waterfall": waterfall,
        "new_deals": [],
        "matured_deals": [],
        "summary": {
            "prev_nii": round(prev_total, 0),
            "curr_nii": round(curr_total, 0),
            "delta": round(curr_total - prev_total, 0),
            "rate_effect": round(float(total_rate), 0),
            "time_effect": 0,
            "new_deal_effect": 0,
            "matured_deal_effect": 0,
            "spread_effect": 0,
            "n_new": 0, "n_matured": 0, "n_existing": 0,
        },
    }
