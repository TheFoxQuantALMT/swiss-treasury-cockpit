"""What-If deal simulator — incremental NII + EVE without full re-run.

Allows quick estimation of P&L impact from adding/removing a hypothetical
deal to the existing portfolio. Uses linear approximation via DV01 and
spread for fast computation.
"""
from __future__ import annotations

import numpy as np


def simulate_deal(
    notional: float,
    client_rate: float,
    ois_rate: float,
    maturity_years: float,
    direction: str = "B",
    mm: int = 360,
    is_floating: bool = False,
    deposit_beta: float = 1.0,
) -> dict:
    """Simulate the P&L impact of a hypothetical deal.

    Args:
        notional: Deal notional amount.
        client_rate: Client lending/borrowing rate (decimal).
        ois_rate: Current OIS rate for the currency (decimal).
        maturity_years: Time to maturity in years.
        direction: "B" (bond/asset) or "L" (lend/liability).
        mm: Day count basis (360 for CHF/EUR, 365 for GBP).
        is_floating: Whether the deal is floating-rate.
        deposit_beta: Rate passthrough for floating-rate (1.0 = full passthrough).

    Returns:
        Dict with annual NII, total NII, EVE impact, DV01 contribution.
    """
    from pnl_engine.config import ASSET_DIRECTIONS
    sign = 1.0 if direction.upper() in ASSET_DIRECTIONS else -1.0
    effective_notional = sign * abs(notional)

    # Effective client rate for floating (NMD model: floor + β × max(0, OIS - floor))
    if is_floating and deposit_beta < 1.0:
        floor_rate = client_rate  # client_rate serves as floor for floating deposits
        effective_rate = floor_rate + deposit_beta * max(0.0, ois_rate - floor_rate)
    else:
        effective_rate = client_rate

    # Annual NII = Notional × (OIS - ClientRate) / MM × 365
    spread = ois_rate - effective_rate
    annual_nii = effective_notional * spread / mm * 365

    # Total NII over life
    total_nii = annual_nii * maturity_years

    # EVE impact = PV of future spread income, compound discounting
    # PV = Notional × spread × annuity_factor, where annuity = (1 - DF) / r
    discount = (1.0 + ois_rate) ** maturity_years if ois_rate > -1.0 else 1.0
    if abs(ois_rate) > 1e-8 and discount != 0:
        annuity = (1.0 - 1.0 / discount) / ois_rate
        eve_impact = effective_notional * spread * annuity
    elif discount != 0:
        # Near-zero rates: annuity ≈ maturity
        eve_impact = effective_notional * spread * maturity_years / discount
    else:
        eve_impact = 0.0

    # DV01 = |Notional × modified_duration| / 10000
    # Approximation: uses zero-coupon modified duration; overstates duration
    # for coupon-bearing instruments.
    mod_duration = maturity_years / (1.0 + ois_rate) if ois_rate > -1.0 else maturity_years
    dv01 = abs(notional) * mod_duration / 10_000

    return {
        "notional": notional,
        "direction": direction.upper(),
        "client_rate_pct": round(client_rate * 100, 4),
        "ois_rate_pct": round(ois_rate * 100, 4),
        "spread_bp": round(spread * 10_000, 1),
        "maturity_years": maturity_years,
        "annual_nii": round(annual_nii, 0),
        "total_nii": round(total_nii, 0),
        "eve_impact": round(eve_impact, 0),
        "dv01_contribution": round(dv01, 0),
        "is_floating": is_floating,
    }


def simulate_batch(deals: list[dict], ois_rates: dict[str, float]) -> dict:
    """Simulate multiple hypothetical deals and aggregate impacts.

    Args:
        deals: List of deal dicts with keys: notional, client_rate,
            maturity_years, direction, currency, and optional is_floating, deposit_beta.
        ois_rates: OIS rate by currency {"CHF": 0.015, ...}.

    Returns:
        Dict with per-deal results and aggregated totals.
    """
    results = []
    total_annual_nii = 0.0
    total_eve = 0.0
    total_dv01 = 0.0

    for deal in deals:
        ccy = deal.get("currency", "CHF")
        ois = ois_rates.get(ccy, 0.0)
        r = simulate_deal(
            notional=deal["notional"],
            client_rate=deal["client_rate"],
            ois_rate=ois,
            maturity_years=deal["maturity_years"],
            direction=deal.get("direction", "B"),
            is_floating=deal.get("is_floating", False),
            deposit_beta=deal.get("deposit_beta", 1.0),
        )
        r["currency"] = ccy
        results.append(r)
        total_annual_nii += r["annual_nii"]
        total_eve += r["eve_impact"]
        total_dv01 += r["dv01_contribution"]

    return {
        "has_data": True,
        "deals": results,
        "total_annual_nii": round(total_annual_nii, 0),
        "total_eve_impact": round(total_eve, 0),
        "total_dv01": round(total_dv01, 0),
        "n_deals": len(results),
    }
