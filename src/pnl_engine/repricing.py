"""Repricing gap analysis.

Classifies deals by their repricing date (maturity for fixed, next fixing
for floating) and computes the gap between assets and liabilities per
time bucket per currency.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Calendar-day boundaries for repricing gap buckets (not day count convention)
REPRICING_BUCKETS = [
    ("O/N", 1),
    ("1W", 7),
    ("1M", 30),
    ("3M", 90),
    ("6M", 180),
    ("1Y", 365),
    ("2Y", 730),
    ("3Y", 1095),
    ("5Y", 1825),
    (">5Y", float("inf")),
]


def _repricing_days(row: pd.Series, ref_date: datetime) -> float:
    """Days until repricing from ref_date."""
    is_floating = row.get("is_floating", False)
    if is_floating:
        nfd = row.get("next_fixing_date")
        if pd.notna(nfd):
            try:
                dt = pd.Timestamp(nfd)
                return max((dt - pd.Timestamp(ref_date)).days, 0)
            except Exception:
                pass
        # Floating with no next_fixing_date → reprices overnight
        return 0

    # Fixed → maturity
    mat = row.get("Maturitydate")
    if pd.notna(mat):
        try:
            dt = pd.Timestamp(mat)
            return max((dt - pd.Timestamp(ref_date)).days, 0)
        except Exception:
            pass
    return float("inf")


def _assign_bucket(days: float) -> str:
    """Assign a bucket label based on days to repricing."""
    for label, upper in REPRICING_BUCKETS:
        if days <= upper:
            return label
    return ">5Y"


def compute_repricing_gap(
    deals: pd.DataFrame,
    schedule_wide: pd.DataFrame,
    date_run: datetime,
) -> pd.DataFrame:
    """Compute repricing gap by currency and bucket.

    Args:
        deals: Parsed deals DataFrame with Maturitydate, is_floating, etc.
        schedule_wide: Wide schedule with monthly nominal columns.
        date_run: Reference date for bucket assignment.

    Returns:
        DataFrame with columns: currency, bucket, bucket_order, assets,
        liabilities, gap, cumulative_gap.
    """
    if deals is None or deals.empty:
        return pd.DataFrame(columns=[
            "currency", "bucket", "bucket_order", "assets",
            "liabilities", "gap", "cumulative_gap",
        ])

    df = deals.copy()

    # Compute repricing days and bucket
    df["_reprice_days"] = df.apply(lambda r: _repricing_days(r, date_run), axis=1)
    df["_bucket"] = df["_reprice_days"].apply(_assign_bucket)

    # Determine asset/liability from Direction
    direction_col = "Direction" if "Direction" in df.columns else None
    if direction_col is None:
        return pd.DataFrame(columns=[
            "currency", "bucket", "bucket_order", "assets",
            "liabilities", "gap", "cumulative_gap",
        ])

    # Use Amount as nominal (absolute value)
    amount_col = "Amount" if "Amount" in df.columns else "amount" if "amount" in df.columns else None
    if amount_col is None:
        return pd.DataFrame(columns=[
            "currency", "bucket", "bucket_order", "assets",
            "liabilities", "gap", "cumulative_gap",
        ])

    ccy_col = "Currency" if "Currency" in df.columns else "Deal currency" if "Deal currency" in df.columns else None
    if ccy_col is None:
        return pd.DataFrame(columns=[
            "currency", "bucket", "bucket_order", "assets",
            "liabilities", "gap", "cumulative_gap",
        ])

    df["_nominal"] = df[amount_col].abs()
    from pnl_engine.config import DIRECTION_SIDE
    df["_side"] = df[direction_col].map(DIRECTION_SIDE)
    unmapped = df["_side"].isna()
    if unmapped.any():
        bad_dirs = df.loc[unmapped, direction_col].unique().tolist()
        logger.warning(
            "repricing_gap: unknown Direction values %s defaulting to 'asset'", bad_dirs,
        )
    df["_side"] = df["_side"].fillna("asset")

    rows = []
    bucket_order = {b[0]: i for i, b in enumerate(REPRICING_BUCKETS)}

    for ccy in sorted(df[ccy_col].unique()):
        ccy_df = df[df[ccy_col] == ccy]
        for bucket_label, _ in REPRICING_BUCKETS:
            bucket_df = ccy_df[ccy_df["_bucket"] == bucket_label]
            assets = bucket_df[bucket_df["_side"] == "asset"]["_nominal"].sum()
            liabs = bucket_df[bucket_df["_side"] == "liability"]["_nominal"].sum()
            rows.append({
                "currency": ccy,
                "bucket": bucket_label,
                "bucket_order": bucket_order[bucket_label],
                "assets": float(assets),
                "liabilities": float(liabs),
                "gap": float(assets - liabs),
            })

    result = pd.DataFrame(rows)
    if result.empty:
        result["cumulative_gap"] = []
        return result

    # Cumulative gap per currency
    cum_gaps = []
    for ccy in result["currency"].unique():
        mask = result["currency"] == ccy
        ccy_df = result[mask].sort_values("bucket_order")
        cum = ccy_df["gap"].cumsum()
        cum_gaps.extend(cum.tolist())
    result = result.sort_values(["currency", "bucket_order"]).reset_index(drop=True)
    result["cumulative_gap"] = cum_gaps

    return result
