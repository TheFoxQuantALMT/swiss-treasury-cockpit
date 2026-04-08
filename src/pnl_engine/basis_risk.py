"""Basis risk analysis — NII sensitivity to spread compression per product.

Basis risk arises when the funding rate (OIS) and the lending rate move
by different magnitudes. This module estimates NII impact of spread
compression by product and currency.

A spread shock of -X bp means the client rate narrows toward OIS by X bp.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from pnl_engine.matrices import broadcast_mm


def compute_basis_risk(
    deals: pd.DataFrame,
    nominal_daily: np.ndarray,
    rate_matrix: np.ndarray,
    ois_matrix: np.ndarray,
    mm_vector: np.ndarray,
    spread_shocks_bp: list[int] | None = None,
) -> dict:
    """Compute NII sensitivity to spread compression by product and currency.

    Args:
        deals: Deal metadata DataFrame with Product, Currency, Direction.
        nominal_daily: (n_deals, n_days) nominal schedule.
        rate_matrix: (n_deals, n_days) client rate matrix.
        ois_matrix: (n_deals, n_days) OIS rate matrix.
        mm_vector: (n_deals,) day-count divisor per deal.
        spread_shocks_bp: List of spread shock sizes in basis points.
            Default: [-50, -25, -10, 0, 10, 25, 50].

    Returns:
        Dict with "by_product", "by_currency", "shocks", "has_data".
    """
    if deals is None or deals.empty or nominal_daily is None:
        return {"has_data": False}

    if spread_shocks_bp is None:
        spread_shocks_bp = [-50, -25, -10, 0, 10, 25, 50]

    mm_2d = broadcast_mm(mm_vector)

    # Base NII by deal
    base_daily = nominal_daily * (ois_matrix - rate_matrix) / mm_2d
    base_by_deal = np.nansum(base_daily, axis=1)

    products = deals["Product"].str.strip().values if "Product" in deals.columns else np.array(["Unknown"] * len(deals))
    currencies = deals["Currency"].str.strip().str.upper().values if "Currency" in deals.columns else np.array(["CHF"] * len(deals))

    # Direction sign: for spread compression, assets and liabilities are
    # shocked in opposite directions.  A positive spread shock widens the
    # spread (client rate moves away from OIS):
    #   Assets  (D/B): client rate rises  → shocked_rate = rate + shock
    #   Liabilities (L/S): client rate falls → shocked_rate = rate - shock
    # We store a (n_deals, 1) sign array: +1 for assets, -1 for liabilities.
    if "Direction" in deals.columns:
        dirs = deals["Direction"].str.strip().str.upper().values
        dir_sign = np.where(np.isin(dirs, ["D", "B"]), 1.0, -1.0)[:, np.newaxis]
    else:
        dir_sign = np.ones((len(deals), 1))

    # Compute shocked NII for each spread shock
    by_product: dict[str, dict] = {}
    by_currency: dict[str, dict] = {}

    unique_products = sorted(set(products))
    unique_currencies = sorted(set(currencies))

    for shock_bp in spread_shocks_bp:
        shock_rate = shock_bp / 10_000.0
        # Spread compression: client rate moves toward OIS.
        # Apply direction-aware shock so both sides of the balance sheet
        # are affected correctly.
        shocked_rate = rate_matrix + shock_rate * dir_sign
        shocked_daily = nominal_daily * (ois_matrix - shocked_rate) / mm_2d
        shocked_by_deal = np.nansum(shocked_daily, axis=1)
        delta_by_deal = shocked_by_deal - base_by_deal

        shock_label = f"{shock_bp:+d}bp"

        for prod in unique_products:
            mask = products == prod
            if prod not in by_product:
                by_product[prod] = {"base_nii": round(float(base_by_deal[mask].sum()), 0)}
            by_product[prod][shock_label] = round(float(delta_by_deal[mask].sum()), 0)

        for ccy in unique_currencies:
            mask = currencies == ccy
            if ccy not in by_currency:
                by_currency[ccy] = {"base_nii": round(float(base_by_deal[mask].sum()), 0)}
            by_currency[ccy][shock_label] = round(float(delta_by_deal[mask].sum()), 0)

    return {
        "has_data": True,
        "shocks": [f"{s:+d}bp" for s in spread_shocks_bp],
        "shock_values_bp": spread_shocks_bp,
        "by_product": by_product,
        "by_currency": by_currency,
    }
