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


# ---------------------------------------------------------------------------
# Tab 1: Executive Summary
# ---------------------------------------------------------------------------

def _build_summary(df: pd.DataFrame, date_rates: datetime) -> dict:
    """KPIs, currency donut, realized/forecast waterfall, top 5 contributors."""
    if df.empty:
        return {"kpis": {}, "donut": {}, "waterfall": {}, "top5": []}

    pnl_rows = df[df["Indice"] == "PnL"].copy()
    if pnl_rows.empty:
        return {"kpis": {}, "donut": {}, "waterfall": {}, "top5": []}

    # KPI cards: total P&L per shock (12-month horizon)
    kpis = {}
    for shock in ("0", "50", "wirp"):
        shock_data = pnl_rows[pnl_rows["Shock"] == shock]
        if shock_data.empty:
            continue
        total = shock_data["Value"].sum()
        realized = 0.0
        forecast = 0.0
        if "PnL_Type" in shock_data.columns:
            realized = shock_data[shock_data["PnL_Type"] == "Realized"]["Value"].sum()
            forecast = shock_data[shock_data["PnL_Type"].isin(["Forecast", "Total"])]["Value"].sum() - realized
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

    # Currency donut (shock=0)
    base = pnl_rows[pnl_rows["Shock"] == "0"]
    if "Deal currency" in base.columns:
        ccy_totals = base.groupby("Deal currency")["Value"].sum()
        donut = {
            "labels": list(ccy_totals.index),
            "values": [round(float(v), 0) for v in ccy_totals.values],
            "colors": [CURRENCY_COLORS.get(c, "#8b949e") for c in ccy_totals.index],
        }
    else:
        donut = {"labels": [], "values": [], "colors": []}

    # Realized vs Forecast waterfall per currency
    waterfall = {"labels": [], "realized": [], "forecast": []}
    if "PnL_Type" in base.columns and "Deal currency" in base.columns:
        for ccy in sorted(base["Deal currency"].unique()):
            ccy_data = base[base["Deal currency"] == ccy]
            r = ccy_data[ccy_data["PnL_Type"] == "Realized"]["Value"].sum()
            f = ccy_data[ccy_data["PnL_Type"].isin(["Forecast", "Total"])]["Value"].sum() - r
            waterfall["labels"].append(ccy)
            waterfall["realized"].append(round(float(r), 0))
            waterfall["forecast"].append(round(float(f), 0))

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

    return {"kpis": kpis, "donut": donut, "waterfall": waterfall, "top5": top5}


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

    return {"months": month_labels, "by_currency": by_currency, "table": table}


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
            total = shock_data.groupby("Month")["Value"].sum()
            by_shock[f"shock_{shock}"] = [round(float(total.get(m, 0.0)), 0) for m in months]

            # Realized/forecast split for this shock
            if "PnL_Type" in shock_data.columns:
                realized = shock_data[shock_data["PnL_Type"] == "Realized"].groupby("Month")["Value"].sum()
                forecast_df = shock_data[shock_data["PnL_Type"] == "Forecast"]
                forecast = forecast_df.groupby("Month")["Value"].sum()
                by_shock[f"shock_{shock}_realized"] = [round(float(realized.get(m, 0.0)), 0) for m in months]
                by_shock[f"shock_{shock}_forecast"] = [round(float(forecast.get(m, 0.0)), 0) for m in months]

        by_currency[ccy] = by_shock

    # Product breakdown (shock=0 only)
    by_product = {}
    base = pnl_rows[pnl_rows["Shock"] == "0"] if "Shock" in pnl_rows.columns else pnl_rows
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

        a_grouped = df_a.groupby(["Deal currency", "Product2BuyBack", "Month"])["Value"].sum()
        b_grouped = df_b.groupby(["Deal currency", "Product2BuyBack", "Month"])["Value"].sum()

        keys = set(a_grouped.index) | set(b_grouped.index)
        combos = sorted({(k[0], k[1]) for k in keys})

        for ccy, prod in combos:
            values = []
            for m in months:
                val_a = a_grouped.get((ccy, prod, m), 0.0)
                val_b = b_grouped.get((ccy, prod, m), 0.0)
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
        nom_total = nom_rows[nom_rows["Product2BuyBack"] == leg]["Value"].mean() if not nom_rows.empty else 0
        rate_avg = rate_rows[rate_rows["Product2BuyBack"] == leg]["Value"].mean() if not rate_rows.empty else 0
        ois_avg = ois_rows[ois_rows["Product2BuyBack"] == leg]["Value"].mean() if not ois_rows.empty else 0

        currencies = base[base["Product2BuyBack"] == leg]["Deal currency"].unique() if "Deal currency" in base.columns else []
        directions = base[base["Product2BuyBack"] == leg]["Direction"].unique() if "Direction" in base.columns else []

        table.append({
            "leg": leg,
            "currency": ", ".join(sorted(currencies)),
            "direction": ", ".join(sorted(directions)),
            "pnl": round(float(pnl_total), 0),
            "nominal": round(float(nom_total), 0),
            "rate_ref": round(float(rate_avg), 6),
            "ois_fwd": round(float(ois_avg), 6),
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

    # Map direction to asset/liability
    nom_rows["_side"] = nom_rows["Direction"].map({"B": "asset", "D": "asset", "L": "liability", "S": "liability"})
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

    return {"has_data": True, "months": month_labels, "by_currency": by_currency}


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
) -> dict:
    """Build EVE dashboard data: base EVE, ΔEVE heatmap, duration, KRD."""
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

    return {
        "has_data": True,
        "total_eve": total_eve,
        "by_currency": by_currency,
        "scenarios": scenarios_data,
        "krd": krd_data,
        "duration": duration_data,
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
        return {"has_data": False, "items": []}

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

    return {"has_data": len(items) > 0, "items": items}


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
) -> dict:
    """Build all chart data for the P&L dashboard."""
    df = _safe_stacked(pnl_all_s)
    dr = date_rates or date_run or datetime.now()

    result = {
        # Original 7 tabs
        "summary": _build_summary(df, dr),
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
        "hedge": _build_hedge_effectiveness(df, hedge_pairs, pnl_by_deal),
        # Wave 3 (placeholders)
        "nii_at_risk": _build_nii_at_risk(df, scenarios_data),
        "forecast_tracking": _build_forecast_tracking(forecast_history),
        "attribution": _build_attribution(df, prev_pnl_all_s, pnl_explain),
        # EVE (Phase 2)
        "eve": _build_eve(eve_results, eve_scenarios, eve_krd),
    }

    # Limit utilization (needs eve + nii_at_risk computed first)
    result["limits"] = _build_limit_utilization(
        df, limits, result["eve"], result["nii_at_risk"],
    )

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

    return {
        "has_data": len(pairs) > 0,
        "pairs": pairs,
        "summary": {"pass": n_pass, "fail": n_fail, "total": n_pass + n_fail},
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

    return {
        "has_data": True,
        "scenarios": scenarios,
        "by_currency": by_currency,
        "heatmap": heatmap,
        "tornado": tornado,
        "worst_case": worst,
        "base_total": round(base_total, 0),
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

    for ccy in currencies:
        nom_old = prev_nom.get(ccy, 0)
        rate_old = prev_ois.get(ccy, 0)
        nom_new = curr_nom.get(ccy, 0)
        rate_new = curr_ois.get(ccy, 0)

        rate_effect = nom_old * (rate_new - rate_old)
        volume_effect = (nom_new - nom_old) * rate_old

        by_currency[ccy] = {
            "ois_prev": round(float(rate_old) * 10000, 1),
            "ois_curr": round(float(rate_new) * 10000, 1),
            "nominal_prev": round(float(nom_old), 0),
            "nominal_curr": round(float(nom_new), 0),
        }
        total_rate += rate_effect
        total_volume += volume_effect

    prev_total = float(prev_pnl.sum())
    curr_total = float(curr_pnl.sum())
    residual = (curr_total - prev_total) - total_rate - total_volume

    waterfall = [
        {"label": "Prev NII", "value": round(prev_total, 0), "type": "base"},
        {"label": "Rate Effect", "value": round(float(total_rate), 0), "type": "effect"},
        {"label": "Volume Effect", "value": round(float(total_volume), 0), "type": "effect"},
        {"label": "Other", "value": round(float(residual), 0), "type": "effect"},
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
