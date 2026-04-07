"""Core chart data builders: Summary, CoC, P&L Series, Sensitivity, Strategy, BOOK2, Curves."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from cockpit.pnl_dashboard.charts.constants import (
    CURRENCY_COLORS,
    LEG_COLORS,
    PRODUCT_COLORS,
)
from cockpit.pnl_dashboard.charts.helpers import _filter_total, _month_labels

logger = logging.getLogger(__name__)


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
        return {"has_data": False, "kpis": {}, "donut": {}, "waterfall": {}, "top5": [], "dod_bridge": None}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty:
        return {"has_data": False, "kpis": {}, "donut": {}, "waterfall": {}, "top5": []}

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

    return {"has_data": True, "kpis": kpis, "donut": donut, "waterfall": waterfall, "top5": top5, "coc_ytd": coc_ytd, "dod_bridge": dod_bridge}


# ---------------------------------------------------------------------------
# Tab 2: CoC Decomposition (Hero)
# ---------------------------------------------------------------------------

def _build_coc(df: pd.DataFrame) -> dict:
    """CoC measures by currency \u00d7 month \u00d7 shock."""
    if df.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "table": []}

    coc_indices = {"GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate"}
    coc_rows = df[df["Indice"].isin(coc_indices)].copy()
    if coc_rows.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "table": []}

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

    return {"has_data": True, "months": month_labels, "by_currency": by_currency, "table": table, "carry_rolldown": carry_rolldown}


# ---------------------------------------------------------------------------
# Tab 3: P&L Time Series
# ---------------------------------------------------------------------------

def _build_pnl_series(df: pd.DataFrame, date_rates: datetime) -> dict:
    """Monthly P&L by currency \u00d7 shock, with realized/forecast split."""
    if df.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {}, "date_rates_month": ""}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty:
        return {"has_data": False, "months": [], "by_currency": {}, "by_product": {}, "date_rates_month": ""}

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
        "has_data": True,
        "months": month_labels,
        "by_currency": by_currency,
        "by_product": by_product,
        "date_rates_month": rates_month,
    }


# ---------------------------------------------------------------------------
# Tab 4: Shock Sensitivity
# ---------------------------------------------------------------------------

def _build_sensitivity(df: pd.DataFrame) -> dict:
    """Delta P&L heatmap: shock=50 minus shock=0, per currency \u00d7 product \u00d7 month."""
    if df.empty:
        return {"has_data": False, "months": [], "rows": [], "totals": {}}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty or "Shock" not in pnl_rows.columns:
        return {"has_data": False, "months": [], "rows": [], "totals": {}}

    # Filter to Total PnL_Type only to avoid double-counting with Realized+Forecast
    pnl_rows = _filter_total(pnl_rows)

    base = pnl_rows[pnl_rows["Shock"] == "0"]
    shock50 = pnl_rows[pnl_rows["Shock"] == "50"]
    wirp = pnl_rows[pnl_rows["Shock"] == "wirp"]

    months = sorted(pnl_rows["Month"].unique())[:12]  # 12-month window
    month_labels = _month_labels(months)

    def _delta_grid(df_a: pd.DataFrame, df_b: pd.DataFrame) -> list[dict]:
        """Compute df_a - df_b grouped by currency \u00d7 product \u00d7 month."""
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

        # Sanitize NaN -> 0 (log warning so users know data is missing)
        _nan_fields = []
        if np.isnan(nom_avg):
            nom_avg = 0.0
            _nan_fields.append("nominal")
        if np.isnan(rate_avg):
            rate_avg = 0.0
            _nan_fields.append("rate_ref")
        if np.isnan(ois_avg):
            ois_avg = 0.0
            _nan_fields.append("ois_fwd")
        if _nan_fields:
            logger.warning("Strategy IAS leg %s has NaN for %s — defaulting to 0.0 (missing data?)",
                           leg, ", ".join(_nan_fields))

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

    # Summary by currency x shock
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
