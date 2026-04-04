"""Liquidity ladder and gap analysis from Echeancier balance schedules."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from cockpit.config import LIQUIDITY_BUCKETS


def _assign_bucket(days_from_ref: int) -> str:
    """Map a number of days from reference date to a liquidity bucket label."""
    if days_from_ref < 0:
        return "Undefined"
    for label, start, end in LIQUIDITY_BUCKETS:
        if start is None:
            continue
        if end is None:
            if days_from_ref >= start:
                return label
        elif start <= days_from_ref <= end:
            return label
    return "Undefined"


def _column_type(col: str) -> str:
    """Classify a column name as 'daily' (YYYY/MM/DD), 'monthly' (YYYY/MM), or 'other'."""
    if not isinstance(col, str):
        return "other"
    parts = col.split("/")
    if len(parts) == 3 and parts[0][:4].isdigit():
        return "daily"
    if len(parts) == 2 and parts[0][:4].isdigit():
        return "monthly"
    return "other"


def _daily_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM/DD' date strings."""
    return [c for c in df.columns if _column_type(c) == "daily"]


def _monthly_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM' date strings."""
    return [c for c in df.columns if _column_type(c) == "monthly"]


def _direction_sign(direction: str) -> int:
    """Return the multiplier applied to -delta to produce the signed cash flow.

    Convention: cash_flow = -delta * sign(direction).

    D (deposit placed by bank, shown as negative balance):
        Balance rises toward 0 on maturity (delta > 0).
        sign = -1 so that cash_flow = -delta * -1 = delta > 0 → inflow.
    L (loan received / funding, shown as positive balance):
        Balance falls to 0 on maturity (delta < 0).
        sign = -1 so that cash_flow = -delta * -1 = delta < 0 → outflow.
    B (bond / asset, shown as positive balance):
        Balance falls to 0 on maturity (delta < 0).
        sign = +1 so that cash_flow = -delta * 1 = -delta > 0 → inflow.
    """
    if direction == "D":
        return -1
    elif direction in ("L",):
        return -1
    elif direction == "B":
        return 1
    return 0


def compute_liquidity_ladder(
    echeancier: pd.DataFrame,
    deals: pd.DataFrame,
    ref_date: date,
) -> dict:
    """Compute liquidity gap by Basel buckets from Echeancier balance schedules.

    1. Diff consecutive balance columns to extract cash flows.
    2. Map each cash flow to a bucket based on days from ref_date.
    3. Split into inflows/outflows by Direction.
    4. Compute net and cumulative gap.
    """
    bucket_labels = [b[0] for b in LIQUIDITY_BUCKETS]
    inflows = {label: 0.0 for label in bucket_labels}
    outflows = {label: 0.0 for label in bucket_labels}

    if "Direction" in echeancier.columns:
        directions = echeancier["Direction"].values
    else:
        dir_map = deals.set_index("Dealid")["Direction"].to_dict()
        echeancier_ids = pd.to_numeric(echeancier.get("Dealid", pd.Series(dtype=float)), errors="coerce")
        directions = echeancier_ids.map(dir_map).fillna("").values

    ref_ts = pd.Timestamp(ref_date)

    daily_cols = _daily_columns(echeancier)
    for i in range(1, len(daily_cols)):
        prev_col = daily_cols[i - 1]
        curr_col = daily_cols[i]
        try:
            col_date = pd.Timestamp(curr_col.replace("/", "-"))
        except Exception:
            continue
        days_from_ref = (col_date - ref_ts).days
        bucket = _assign_bucket(days_from_ref)

        for deal_idx in range(len(echeancier)):
            prev_val = float(echeancier.iloc[deal_idx].get(prev_col, 0) or 0)
            curr_val = float(echeancier.iloc[deal_idx].get(curr_col, 0) or 0)
            delta = curr_val - prev_val
            if delta == 0:
                continue
            sign = _direction_sign(directions[deal_idx])
            cash_flow = -delta * sign
            if cash_flow > 0:
                inflows[bucket] += cash_flow
            elif cash_flow < 0:
                outflows[bucket] += abs(cash_flow)

    monthly_cols = _monthly_columns(echeancier)
    for i in range(1, len(monthly_cols)):
        prev_col = monthly_cols[i - 1]
        curr_col = monthly_cols[i]
        try:
            col_date = pd.Timestamp(curr_col.replace("/", "-") + "-15")
        except Exception:
            continue
        days_from_ref = (col_date - ref_ts).days
        bucket = _assign_bucket(days_from_ref)

        for deal_idx in range(len(echeancier)):
            prev_val = float(echeancier.iloc[deal_idx].get(prev_col, 0) or 0)
            curr_val = float(echeancier.iloc[deal_idx].get(curr_col, 0) or 0)
            delta = curr_val - prev_val
            if delta == 0:
                continue
            sign = _direction_sign(directions[deal_idx])
            cash_flow = -delta * sign
            if cash_flow > 0:
                inflows[bucket] += cash_flow
            elif cash_flow < 0:
                outflows[bucket] += abs(cash_flow)

    buckets_out = []
    cumulative = 0.0
    for label in bucket_labels:
        net = inflows[label] - outflows[label]
        cumulative += net
        buckets_out.append({
            "label": label,
            "inflows": inflows[label],
            "outflows": outflows[label],
            "net": net,
            "cumulative": cumulative,
        })

    survival_days = None
    for b in buckets_out:
        if b["cumulative"] < 0:
            label = b["label"]
            for bl, start, end in LIQUIDITY_BUCKETS:
                if bl == label and start is not None:
                    survival_days = start
                    break
            break

    return {
        "ref_date": ref_date.isoformat(),
        "buckets": buckets_out,
        "survival_days": survival_days,
        "total_inflows": sum(inflows.values()),
        "total_outflows": sum(outflows.values()),
    }
