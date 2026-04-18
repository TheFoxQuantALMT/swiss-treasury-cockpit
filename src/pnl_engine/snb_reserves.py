"""SNB minimum reserve compliance calculation.

Swiss banks must hold minimum reserves of 2.5% on sight liabilities
(Art. 12 NBA / SNB Ordinance). This module computes reserve requirements,
HQLA deductions, and the opportunity cost of holding reserves vs OIS.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from pnl_engine.config import (
    HQLA_DEDUCTION,
    LIABILITY_DIRECTIONS,
    SNB_RESERVE_RATIO,
    SNB_SIGHT_PRODUCTS,
)


def compute_snb_reserves(
    deals: Optional[pd.DataFrame],
    ois_rate: float = 0.0,
    reserve_ratio: float = SNB_RESERVE_RATIO,
    hqla_deduction: float = HQLA_DEDUCTION,
    hqla_amount: float = 0.0,
    tier1_capital: float = 0.0,
    actual_reserves: float | None = None,
) -> dict:
    """Compute SNB minimum reserve requirements and opportunity cost.

    Args:
        deals: Deal metadata DataFrame with Direction, Currency, Product, Amount.
        ois_rate: Current CHF OIS rate (annualized, decimal).
        reserve_ratio: Minimum reserve ratio (default 2.5%).
        hqla_deduction: HQLA offset percentage (default 20%).
        hqla_amount: Total HQLA holdings.
        tier1_capital: Tier 1 capital (for ratio reporting).

    Returns:
        Dict with reserve requirement, excess/shortfall, opportunity cost.
    """
    if deals is None or deals.empty:
        return {"has_data": False}

    # Sight liabilities: Direction D (deposit) = bank receives funds
    sight_mask = pd.Series([False] * len(deals))
    if "Direction" in deals.columns:
        sight_mask = deals["Direction"].str.strip().str.upper().isin(LIABILITY_DIRECTIONS)
    if "Currency" in deals.columns:
        sight_mask &= deals["Currency"].str.strip().str.upper() == "CHF"

    if "Product" in deals.columns:
        product_mask = deals["Product"].str.strip().str.upper().isin(SNB_SIGHT_PRODUCTS)
        sight_mask &= product_mask

    if "Amount" in deals.columns:
        sight_liabilities = float(deals.loc[sight_mask, "Amount"].sum())
    else:
        sight_liabilities = 0.0

    # Minimum reserve requirement
    gross_requirement = sight_liabilities * reserve_ratio
    hqla_offset = hqla_amount * hqla_deduction
    net_requirement = max(0, gross_requirement - hqla_offset)

    # Opportunity cost: reserves earn 0 (or SNB sight deposit rate)
    # Cost = reserve_amount × max(0, OIS_rate). Using max(0, …) keeps the cost
    # non-negative under negative-rate regimes (2015–2022 CHF), where deploying
    # funds at a negative OIS would destroy value — reserves have zero or
    # beneficial opportunity cost in that case.
    opportunity_cost = net_requirement * max(0.0, ois_rate)

    # Coverage ratio
    coverage_pct = (hqla_offset / gross_requirement * 100) if gross_requirement > 0 else 100.0

    return {
        "has_data": True,
        "sight_liabilities": round(sight_liabilities, 0),
        "reserve_ratio": reserve_ratio,
        "gross_requirement": round(gross_requirement, 0),
        "hqla_amount": round(hqla_amount, 0),
        "hqla_deduction": hqla_deduction,
        "hqla_offset": round(hqla_offset, 0),
        "net_requirement": round(net_requirement, 0),
        "ois_rate": round(ois_rate, 6),
        "opportunity_cost_annual": round(opportunity_cost, 0),
        "coverage_pct": round(coverage_pct, 1),
        "actual_reserves": round(actual_reserves, 0) if actual_reserves is not None else None,
        "compliant": actual_reserves >= net_requirement if actual_reserves is not None else None,
    }
