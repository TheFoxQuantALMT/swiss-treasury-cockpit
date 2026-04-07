"""Derive hedge pairs from strategy_ias grouping in deals.

Deals sharing the same ``Strategy IAS`` value form a hedge relationship.
Hedged items (IAM/LD, BND, FXS) vs hedging instruments (IRS, IRS-MTM, HCD)
are determined by product type.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

_HEDGED_PRODUCTS = {"IAM/LD", "BND", "FXS"}
_INSTRUMENT_PRODUCTS = {"IRS", "IRS-MTM", "HCD"}


def derive_hedge_pairs(deals: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Build hedge pairs DataFrame from deals with Strategy IAS.

    Groups deals by ``Strategy IAS`` and splits each group into hedged items
    (IAM/LD, BND, FXS) and hedging instruments (IRS, IRS-MTM, HCD).

    Returns DataFrame with columns: pair_id, pair_name, hedged_item_deal_ids,
    hedging_instrument_deal_ids, hedge_type, ias_standard.
    Returns None if no deals have Strategy IAS set.
    """
    if deals is None or deals.empty:
        return None

    strat_col = "Strategy IAS"
    if strat_col not in deals.columns:
        return None

    strat_deals = deals[deals[strat_col].notna() & (deals[strat_col].astype(str).str.strip() != "")].copy()
    if strat_deals.empty:
        return None

    product_col = "Product"
    dealid_col = "Dealid" if "Dealid" in strat_deals.columns else "deal_id"
    ccy_col = "Currency" if "Currency" in strat_deals.columns else "currency"

    pairs = []
    for strat_name, group in strat_deals.groupby(strat_col):
        hedged_mask = group[product_col].isin(_HEDGED_PRODUCTS)
        instrument_mask = group[product_col].isin(_INSTRUMENT_PRODUCTS)

        hedged_ids = group.loc[hedged_mask, dealid_col].astype(str).tolist()
        instrument_ids = group.loc[instrument_mask, dealid_col].astype(str).tolist()

        if not hedged_ids or not instrument_ids:
            continue

        # Currency from hedged items for pair name
        currencies = group.loc[hedged_mask, ccy_col].unique() if ccy_col in group.columns else []
        ccy_label = "/".join(sorted(currencies)) if len(currencies) > 0 else ""

        # Hedge metadata — take from first deal in group (all should be identical)
        hedge_type = group["hedge_type"].dropna().iloc[0] if "hedge_type" in group.columns and group["hedge_type"].notna().any() else "cash_flow"
        ias_standard = group["ias_standard"].dropna().iloc[0] if "ias_standard" in group.columns and group["ias_standard"].notna().any() else "IFRS9"

        pairs.append({
            "pair_id": str(strat_name),
            "pair_name": f"{ccy_label} {strat_name}".strip(),
            "hedged_item_deal_ids": ",".join(hedged_ids),
            "hedging_instrument_deal_ids": ",".join(instrument_ids),
            "hedge_type": str(hedge_type),
            "ias_standard": str(ias_standard),
        })

    if not pairs:
        return None

    return pd.DataFrame(pairs)
