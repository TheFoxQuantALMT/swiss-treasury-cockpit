"""Chart data builders for cockpit HTML templates.

Each function takes raw data dicts (from JSON intermediates) and returns
structured dicts that Jinja2 templates embed as inline JSON for Chart.js.
"""

from __future__ import annotations

from cockpit.config import FX_ALERT_BANDS, SCENARIOS


def build_macro_charts(data: dict) -> dict:
    """Build data for Tab 1: Macro Overview.

    Returns dict with keys: score_cards, alerts, cb_rates, key_dates.
    """
    scores = data.get("scores", {})
    alerts = data.get("alerts", [])

    score_cards = {}
    for ccy in ("USD", "EUR", "CHF", "GBP"):
        s = scores.get(ccy, {})
        score_cards[ccy] = {
            "composite": s.get("composite", 0),
            "label": s.get("label", "N/A"),
            "driver": s.get("driver", ""),
            "families": s.get("families", {}),
        }

    cb_rates = {}
    rates = data.get("rates", {})
    if "fed_rates" in rates:
        cb_rates["Fed"] = {"rate": rates["fed_rates"].get("mid"), "name": "Fed Funds"}
    if "ecb_rates" in rates:
        cb_rates["ECB"] = {"rate": rates["ecb_rates"].get("deposit_facility"), "name": "Deposit Facility"}
    snb = rates.get("snb_rate")
    if snb is not None:
        cb_rates["BNS"] = {"rate": snb, "name": "Policy Rate"}

    return {
        "score_cards": score_cards,
        "alerts": alerts,
        "cb_rates": cb_rates,
        "key_dates": data.get("key_dates", []),
    }


def build_fx_energy_charts(data: dict) -> dict:
    """Build data for Tab 2: FX & Energy.

    Returns dict with keys: fx_series, energy_series, deltas, scenario_bands.
    """
    fx_series = {}
    for pair in ("usd_chf", "eur_chf", "gbp_chf"):
        history = data.get(f"{pair}_history", [])
        fx_series[pair] = {
            "dates": [p["date"] for p in history],
            "values": [p["value"] for p in history],
        }

    energy = data.get("energy", {})
    energy_series = {}
    for fuel in ("brent", "eu_gas"):
        history = energy.get(f"{fuel}_history", [])
        energy_series[fuel] = {
            "dates": [p["date"] for p in history],
            "values": [p["value"] for p in history],
        }

    return {
        "fx_series": fx_series,
        "energy_series": energy_series,
        "deltas": data.get("deltas", {}),
        "scenario_bands": SCENARIOS,
        "fx_bands": FX_ALERT_BANDS,
    }


def build_pnl_charts(data: dict) -> dict:
    """Build data for Tab 3: P&L Projection.

    Returns dict with keys: monthly_pnl, shock_comparison, book2_mtm, strategy_decomposition.
    """
    months = data.get("months", [])
    by_currency = data.get("by_currency", {})

    datasets = {}
    for ccy, shocks in by_currency.items():
        datasets[ccy] = {
            "shock_0": shocks.get("shock_0", []),
            "shock_50": shocks.get("shock_50", []),
            "shock_wirp": shocks.get("shock_wirp", []),
        }

    return {
        "monthly_pnl": {
            "labels": months,
            "datasets": datasets,
        },
        "shock_comparison": data.get("shock_comparison", {}),
        "book2_mtm": data.get("book2_mtm", []),
        "strategy_decomposition": data.get("strategy_decomposition", {}),
    }


def build_portfolio_charts(data: dict) -> dict:
    """Build data for Tab 4: Portfolio Snapshot.

    Returns dict with keys: liquidity_ladder, positions, concentration, rating, hqla.
    """
    exposure = data.get("exposure", {})
    buckets = exposure.get("buckets", [])

    liquidity_ladder = {
        "labels": [b["label"] for b in buckets],
        "inflows": [b["inflows"] for b in buckets],
        "outflows": [b["outflows"] for b in buckets],
        "net": [b["net"] for b in buckets],
        "cumulative": [b["cumulative"] for b in buckets],
        "survival_days": exposure.get("survival_days"),
    }

    positions = data.get("positions", {}).get("currencies", {})

    cpty = data.get("counterparty", {})
    concentration = cpty.get("concentration", {})
    rating = cpty.get("rating", {})
    hqla = cpty.get("hqla", {})

    return {
        "liquidity_ladder": liquidity_ladder,
        "positions": positions,
        "concentration": concentration,
        "rating": rating,
        "hqla": hqla,
    }
