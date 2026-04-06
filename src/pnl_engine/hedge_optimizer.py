"""Optimal hedge sizing — DV01-based notional recommendation.

Given current portfolio DV01 and target sensitivity limits,
recommends IRS notional by currency to bring exposure within bounds.
"""
from __future__ import annotations

from typing import Optional


def recommend_hedge(
    portfolio_dv01: dict[str, float],
    target_dv01: dict[str, float] | None = None,
    max_dv01: dict[str, float] | None = None,
    irs_dv01_per_million: dict[str, float] | None = None,
) -> dict:
    """Recommend hedge notionals to bring DV01 within target range.

    Args:
        portfolio_dv01: Current DV01 by currency (e.g. {"CHF": 15000, "EUR": 8000}).
        target_dv01: Target DV01 by currency (default: 0 per currency → fully hedge).
        max_dv01: Maximum acceptable DV01 (if current < max, no hedge needed).
        irs_dv01_per_million: DV01 per 1M notional of a 3Y payer IRS by currency.
            Default: ~3Y duration → ~300 per 1M for CHF/EUR, ~280 for USD/GBP.

    Returns:
        Dict with recommendations per currency.
    """
    if not portfolio_dv01:
        return {"has_data": False, "recommendations": []}

    default_irs_dv01 = {
        "CHF": 300.0,  # ~3Y mod. duration × 1M / 10000
        "EUR": 300.0,
        "USD": 280.0,
        "GBP": 270.0,
    }
    irs_dv01 = {**default_irs_dv01, **(irs_dv01_per_million or {})}
    target = target_dv01 or {}
    limits = max_dv01 or {}

    recommendations = []
    for ccy, current_dv01 in portfolio_dv01.items():
        target_val = target.get(ccy, 0.0)
        max_val = limits.get(ccy, float("inf"))
        excess = abs(current_dv01) - max_val

        if excess <= 0 and abs(current_dv01 - target_val) < abs(current_dv01) * 0.1:
            recommendations.append({
                "currency": ccy,
                "current_dv01": round(current_dv01, 0),
                "action": "none",
                "reason": "Within acceptable range",
                "notional": 0,
                "instrument": "—",
                "tenor": "—",
                "rationale": "Within acceptable range",
            })
            continue

        # How much DV01 to remove
        dv01_to_hedge = current_dv01 - target_val
        ccy_irs_dv01 = irs_dv01.get(ccy, 300.0)

        if ccy_irs_dv01 <= 0:
            continue

        # Notional = DV01_to_hedge / DV01_per_million × 1M
        notional = (dv01_to_hedge / ccy_irs_dv01) * 1_000_000
        direction = "payer" if dv01_to_hedge > 0 else "receiver"
        tenor = "3Y"  # Standard hedge tenor

        recommendations.append({
            "currency": ccy,
            "current_dv01": round(current_dv01, 0),
            "target_dv01": round(target_val, 0),
            "excess_dv01": round(dv01_to_hedge, 0),
            "action": f"Add {abs(notional):,.0f} {ccy} {tenor} {direction} IRS",
            "notional": round(abs(notional), 0),
            "direction": direction,
            "tenor": tenor,
            "instrument": f"{ccy} {tenor} {direction} IRS",
            "rationale": f"Reduce DV01 by {abs(dv01_to_hedge):,.0f} (current: {current_dv01:,.0f}, target: {target_val:,.0f})",
        })

    return {
        "has_data": True,
        "recommendations": recommendations,
        "total_notional": sum(r["notional"] for r in recommendations),
    }
