"""Optimal hedge sizing — DV01-based notional recommendation.

Given current portfolio DV01 and target sensitivity limits,
recommends IRS notional by currency to bring exposure within bounds.

Supports multi-tenor hedge strategies (1Y, 2Y, 3Y, 5Y, 10Y) with
curve-aware and KRD-based tenor selection.
"""
from __future__ import annotations

from typing import Optional


# DV01 per 1M notional by tenor and currency (approximate mid-market values)
DV01_PER_MILLION_BY_TENOR: dict[str, dict[str, float]] = {
    "1Y": {"CHF": 95, "EUR": 95, "USD": 90, "GBP": 85},
    "2Y": {"CHF": 190, "EUR": 190, "USD": 180, "GBP": 170},
    "3Y": {"CHF": 280, "EUR": 280, "USD": 265, "GBP": 255},
    "5Y": {"CHF": 450, "EUR": 450, "USD": 430, "GBP": 410},
    "10Y": {"CHF": 850, "EUR": 850, "USD": 810, "GBP": 780},
}

DEFAULT_TENORS = ["1Y", "2Y", "3Y", "5Y", "10Y"]


def select_optimal_tenor(
    dv01_to_hedge: float,
    currency: str,
    krd_profile: dict[str, float] | None = None,
    curve_slope: float | None = None,
    available_tenors: list[str] | None = None,
) -> str:
    """Select the optimal hedge tenor based on portfolio characteristics.

    Selection logic (in priority order):
    1. **KRD-based**: If KRD profile provided, hedge at the tenor with the
       largest absolute KRD contribution (matching the risk source).
    2. **Curve-aware**: If curve slope provided, prefer shorter tenors for
       steep curves (>50bp 2s10s, cost efficient) and longer tenors for
       flat/inverted curves (more DV01 per notional).
    3. **Default**: 3Y (balanced cost vs. DV01 efficiency).

    Args:
        dv01_to_hedge: DV01 amount to hedge (sign indicates direction).
        currency: Currency code.
        krd_profile: KRD by tenor point {"1Y": 500, "2Y": 3000, ...}.
        curve_slope: 2s10s slope in basis points (positive = steep).
        available_tenors: Allowed tenors (default: all).

    Returns:
        Optimal tenor string (e.g., "5Y").
    """
    tenors = available_tenors or DEFAULT_TENORS

    # 1. KRD-based: pick tenor with largest absolute KRD
    if krd_profile:
        best_tenor = None
        best_krd = 0.0
        for t in tenors:
            krd_val = abs(krd_profile.get(t, 0.0))
            if krd_val > best_krd:
                best_krd = krd_val
                best_tenor = t
        if best_tenor:
            return best_tenor

    # 2. Curve-aware
    if curve_slope is not None:
        if curve_slope > 50:
            # Steep curve: shorter tenor is cheaper (lower carry cost)
            return tenors[0] if tenors else "3Y"
        elif curve_slope < -20:
            # Inverted curve: longer tenor captures more DV01 per notional
            return tenors[-1] if tenors else "10Y"
        # Moderate slope: pick middle tenor for balance
        mid = len(tenors) // 2
        return tenors[mid] if tenors else "3Y"

    # 3. Default: 3Y
    return "3Y" if "3Y" in tenors else tenors[len(tenors) // 2]


def recommend_hedge(
    portfolio_dv01: dict[str, float],
    target_dv01: dict[str, float] | None = None,
    max_dv01: dict[str, float] | None = None,
    irs_dv01_per_million: dict[str, float] | None = None,
    curve_slopes: dict[str, float] | None = None,
    portfolio_krd: dict[str, dict[str, float]] | None = None,
    available_tenors: list[str] | None = None,
) -> dict:
    """Recommend hedge notionals to bring DV01 within target range.

    Supports multi-tenor strategies when ``curve_slopes`` or
    ``portfolio_krd`` are provided. Otherwise defaults to 3Y tenor
    for backward compatibility.

    Args:
        portfolio_dv01: Current DV01 by currency (e.g. {"CHF": 15000, "EUR": 8000}).
        target_dv01: Target DV01 by currency (default: 0 per currency → fully hedge).
        max_dv01: Maximum acceptable DV01 (if current < max, no hedge needed).
        irs_dv01_per_million: Legacy single-tenor DV01/M override (flat across tenors).
            Kept for backward compatibility. When provided, used as the 3Y value.
        curve_slopes: 2s10s slope by currency in basis points (positive = steep).
        portfolio_krd: Key rate durations by currency × tenor.
            E.g. {"CHF": {"1Y": 500, "3Y": 3000, "5Y": 8000, "10Y": 2000}}.
        available_tenors: Restrict recommendations to these tenors.

    Returns:
        Dict with recommendations per currency including optimal tenor.
    """
    if not portfolio_dv01:
        return {"has_data": False, "recommendations": []}

    # Build DV01 lookup: use per-tenor table, with legacy override merged in
    tenors = available_tenors or DEFAULT_TENORS
    slopes = curve_slopes or {}
    krd = portfolio_krd or {}
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

        dv01_to_hedge = current_dv01 - target_val

        # Select optimal tenor
        ccy_krd = krd.get(ccy)
        ccy_slope = slopes.get(ccy)
        tenor = select_optimal_tenor(
            dv01_to_hedge, ccy,
            krd_profile=ccy_krd,
            curve_slope=ccy_slope,
            available_tenors=tenors,
        )

        # Get DV01 per million for selected tenor
        if irs_dv01_per_million and ccy in irs_dv01_per_million:
            # Legacy override: use provided value regardless of tenor
            ccy_irs_dv01 = irs_dv01_per_million[ccy]
        else:
            tenor_dv01 = DV01_PER_MILLION_BY_TENOR.get(tenor, {})
            ccy_irs_dv01 = tenor_dv01.get(ccy, 300.0)

        if ccy_irs_dv01 <= 0:
            continue

        notional = (dv01_to_hedge / ccy_irs_dv01) * 1_000_000
        direction = "payer" if dv01_to_hedge > 0 else "receiver"

        # Build tenor selection rationale
        if ccy_krd:
            tenor_reason = f"KRD-matched (largest exposure at {tenor})"
        elif ccy_slope is not None:
            if ccy_slope > 50:
                tenor_reason = f"Steep curve ({ccy_slope:.0f}bp 2s10s) → shorter tenor"
            elif ccy_slope < -20:
                tenor_reason = f"Inverted curve ({ccy_slope:.0f}bp 2s10s) → longer tenor"
            else:
                tenor_reason = f"Moderate curve ({ccy_slope:.0f}bp 2s10s) → balanced tenor"
        else:
            tenor_reason = "Default tenor"

        recommendations.append({
            "currency": ccy,
            "current_dv01": round(current_dv01, 0),
            "target_dv01": round(target_val, 0),
            "excess_dv01": round(dv01_to_hedge, 0),
            "action": f"Add {abs(notional):,.0f} {ccy} {tenor} {direction} IRS",
            "notional": round(abs(notional), 0),
            "direction": direction,
            "tenor": tenor,
            "dv01_per_million": round(ccy_irs_dv01, 0),
            "instrument": f"{ccy} {tenor} {direction} IRS",
            "tenor_rationale": tenor_reason,
            "rationale": f"Reduce DV01 by {abs(dv01_to_hedge):,.0f} (current: {current_dv01:,.0f}, target: {target_val:,.0f})",
        })

    return {
        "has_data": True,
        "recommendations": recommendations,
        "total_notional": sum(r["notional"] for r in recommendations),
    }
