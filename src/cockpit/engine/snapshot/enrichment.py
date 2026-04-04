"""Deal enrichment — join counterparty reference data onto deal positions."""
from __future__ import annotations

import pandas as pd


def enrich_deals(deals: pd.DataFrame, ref_table: pd.DataFrame) -> pd.DataFrame:
    """Left-join reference data (rating, HQLA, country) onto deals by Counterparty.

    Unmatched deals receive defaults: rating='NR', hqla_level='Non-HQLA', country='XX'.
    """
    merged = deals.merge(
        ref_table,
        left_on="Counterparty",
        right_on="counterparty",
        how="left",
    )
    if "counterparty" in merged.columns:
        merged = merged.drop(columns=["counterparty"])
    merged["rating"] = merged["rating"].fillna("NR")
    merged["hqla_level"] = merged["hqla_level"].fillna("Non-HQLA")
    merged["country"] = merged["country"].fillna("XX")
    return merged.reset_index(drop=True)
