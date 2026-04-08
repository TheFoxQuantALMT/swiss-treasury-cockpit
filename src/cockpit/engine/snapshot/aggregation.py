"""Currency-driven position aggregation views."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from cockpit.config import CURRENCY_CLASSES, LIQUIDITY_BUCKETS, SUPPORTED_CURRENCIES
from cockpit.engine.snapshot.exposure import _assign_bucket


def _classify_direction(direction: str) -> str:
    """Map deal direction to asset or liability.

    L (loan) and B (bond) are assets. D (deposit) and S (sell bond) are liabilities.
    """
    from pnl_engine.config import ASSET_DIRECTIONS
    if direction in ASSET_DIRECTIONS:
        return "asset"
    return "liability"


def _compute_one_currency(
    deals: pd.DataFrame,
    ref_date: date,
) -> dict:
    """Compute position metrics for a set of deals (assumed same currency or converted)."""
    if deals.empty:
        return {
            "assets": 0.0,
            "liabilities": 0.0,
            "net": 0.0,
            "by_product": {},
            "by_maturity": [{"bucket": b[0], "amount": 0.0} for b in LIQUIDITY_BUCKETS],
            "avg_rate": 0.0,
        }

    deals = deals.copy()
    deals["abs_amount"] = deals["Amount"].abs()
    deals["side"] = deals["Direction"].apply(_classify_direction)

    assets = deals.loc[deals["side"] == "asset", "abs_amount"].sum()
    liabilities = deals.loc[deals["side"] == "liability", "abs_amount"].sum()

    by_product = deals.groupby("Product")["abs_amount"].sum().to_dict()

    ref_ts = pd.Timestamp(ref_date)
    mat = pd.to_datetime(deals["Maturitydate"], errors="coerce", dayfirst=False)
    deals["_days_to_mat"] = (mat - ref_ts).dt.days.fillna(-1).astype(int)
    deals["_bucket"] = deals["_days_to_mat"].apply(_assign_bucket)
    bucket_agg = deals.groupby("_bucket")["abs_amount"].sum().to_dict()
    by_maturity = []
    for label, _, _ in LIQUIDITY_BUCKETS:
        by_maturity.append({"bucket": label, "amount": bucket_agg.get(label, 0.0)})

    if "Clientrate" in deals.columns:
        weights = deals["abs_amount"]
        rates = deals["Clientrate"].fillna(0.0)
        total_weight = weights.sum()
        avg_rate = float((rates * weights).sum() / total_weight) if total_weight > 0 else 0.0
    else:
        avg_rate = 0.0

    return {
        "assets": float(assets),
        "liabilities": float(liabilities),
        "net": float(assets - liabilities),
        "by_product": {k: float(v) for k, v in by_product.items()},
        "by_maturity": by_maturity,
        "avg_rate": round(avg_rate, 6),
    }


def compute_positions(
    deals: pd.DataFrame,
    fx_rates: dict[str, float],
    ref_date: date | None = None,
) -> dict:
    """Compute currency-driven position views.

    Currency classes: Total (CHF-equiv), CHF, USD, EUR, GBP, Others.
    """
    if ref_date is None:
        ref_date = date.today()

    named_currencies = {"CHF", "USD", "EUR", "GBP"}
    deals = deals.copy()

    deal_currencies = set(deals["Currency"].unique())
    non_chf = deal_currencies - {"CHF"}
    missing_fx = [c for c in non_chf if c not in fx_rates and c not in named_currencies]

    def _fx(ccy: str) -> float:
        if ccy == "CHF":
            return 1.0
        return fx_rates.get(ccy, 1.0)

    currencies_out = {}

    for ccy in ["CHF", "USD", "EUR", "GBP"]:
        ccy_deals = deals[deals["Currency"] == ccy]
        currencies_out[ccy] = _compute_one_currency(ccy_deals, ref_date)

    others_mask = ~deals["Currency"].isin(named_currencies)
    others_deals = deals[others_mask].copy()
    if not others_deals.empty:
        others_deals["Amount"] = others_deals.apply(
            lambda r: r["Amount"] * _fx(r["Currency"]), axis=1
        )
    currencies_out["Others"] = _compute_one_currency(others_deals, ref_date)

    total_deals = deals.copy()
    total_deals["Amount"] = total_deals.apply(
        lambda r: r["Amount"] * _fx(r["Currency"]), axis=1
    )
    currencies_out["Total"] = _compute_one_currency(total_deals, ref_date)

    return {
        "ref_date": ref_date.isoformat(),
        "fx_rates_used": {k: v for k, v in fx_rates.items()},
        "missing_fx": sorted(missing_fx),
        "currencies": currencies_out,
    }
