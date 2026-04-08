"""Dynamic balance sheet — reinvestment of maturing deals.

Projects future balance sheet by replacing maturing deals with new
production according to a configurable production plan. This enables
forward-looking NII projection under constant-balance assumptions.

Without a production plan, the engine treats the balance sheet as static:
deals mature and disappear, reducing total NII over time. With a plan,
maturing volumes are reinvested at prevailing OIS + spread, maintaining
the balance sheet size.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ProductionPlan:
    """Reinvestment assumption for a product/currency/direction combination.

    Attributes:
        product: Product type (e.g., "IAM/LD").
        currency: Currency code (e.g., "CHF").
        direction: Deal direction (e.g., "D" for deposit).
        monthly_volume: New production notional per month.
        tenor_years: Maturity of new production deals.
        rate_spread_bps: Spread over OIS for pricing new deals (basis points).
    """
    product: str
    currency: str
    direction: str
    monthly_volume: float
    tenor_years: float
    rate_spread_bps: float = 0.0


def project_balance_sheet(
    deals: pd.DataFrame,
    nominal_daily: np.ndarray,
    days: pd.DatetimeIndex,
    month_cols: list[str],
    production_plans: list[ProductionPlan],
    date_run: datetime,
    ois_curve: Optional[dict[str, float]] = None,
) -> tuple[np.ndarray, pd.DataFrame, list[dict]]:
    """Project nominal schedule with reinvestment of maturing volumes.

    For each month in the projection horizon, identifies deals that mature
    and generates replacement deals from the production plan. New deals
    are priced at OIS + spread and have the plan's tenor.

    Args:
        deals: Original deal metadata DataFrame (n_deals rows).
        nominal_daily: (n_deals, n_days) original nominal schedule.
        days: DatetimeIndex of the full date grid.
        month_cols: Month column names (e.g., ["2026/04", ...]).
        production_plans: List of reinvestment assumptions.
        date_run: Reference date (new deals start after this).
        ois_curve: Optional OIS rate by currency for pricing new deals
            (e.g., {"CHF": 0.015}). If None, uses 0.0.

    Returns:
        Tuple of:
          - projected_nominal: (n_deals + n_new, n_days) extended nominal array
          - projected_deals: Extended deals DataFrame with synthetic rows
          - projection_log: Audit trail of synthetic deals created
    """
    if not production_plans:
        return nominal_daily, deals, []

    ois_rates = ois_curve or {}
    date_run_ts = pd.Timestamp(date_run)

    # Index production plans for fast lookup
    plan_index: dict[tuple[str, str, str], ProductionPlan] = {}
    for plan in production_plans:
        key = (plan.product.strip().upper(), plan.currency.strip().upper(), plan.direction.strip().upper())
        plan_index[key] = plan

    # Identify maturing volume per month per (product, currency, direction)
    maturing_by_month: dict[str, dict[tuple, float]] = {}
    mat_col = "Maturitydate"
    if mat_col not in deals.columns:
        logger.warning("project_balance_sheet: no Maturitydate column, skipping")
        return nominal_daily, deals, []

    for i, deal in deals.iterrows():
        mat_raw = deal.get(mat_col)
        if pd.isna(mat_raw):
            continue
        mat_dt = pd.Timestamp(mat_raw)
        if mat_dt <= date_run_ts:
            continue  # already matured

        mat_month = mat_dt.to_period("M").strftime("%Y/%m")
        product = str(deal.get("Product", "")).strip().upper()
        currency = str(deal.get("Currency", "")).strip().upper()
        direction = str(deal.get("Direction", "")).strip().upper()
        amount = abs(float(deal.get("Amount", 0) or 0))

        key = (product, currency, direction)
        if key not in plan_index:
            continue  # no plan for this combination

        if mat_month not in maturing_by_month:
            maturing_by_month[mat_month] = {}
        if key not in maturing_by_month[mat_month]:
            maturing_by_month[mat_month][key] = 0.0
        maturing_by_month[mat_month][key] += amount

    if not maturing_by_month:
        logger.info("project_balance_sheet: no deals match production plans")
        return nominal_daily, deals, []

    # Generate synthetic deals for each maturing month
    synthetic_deals = []
    synthetic_nominals = []
    projection_log = []
    next_deal_id = 900000

    # Convert month_cols to period format for matching
    day_periods = days.to_period("M").astype(str)  # "YYYY-MM"

    for mat_month in sorted(maturing_by_month.keys()):
        for (product, currency, direction), maturing_amount in maturing_by_month[mat_month].items():
            plan = plan_index[(product, currency, direction)]

            # New deal volume: plan monthly_volume (capped at maturing amount if desired)
            new_volume = plan.monthly_volume

            # Pricing: OIS + spread
            ois_rate = ois_rates.get(currency, 0.0)
            client_rate = ois_rate + plan.rate_spread_bps / 10_000

            # Start date: 1st of maturing month
            mat_month_norm = mat_month.replace("/", "-")
            start_date = pd.Timestamp(f"{mat_month_norm}-01")
            maturity_date = start_date + pd.DateOffset(years=int(plan.tenor_years))

            # Build nominal schedule for new deal
            new_nominal = np.zeros(len(days))
            from pnl_engine.config import ASSET_DIRECTIONS
            # Assets (L/B) = negative nominal, Liabilities (D/S) = positive nominal
            sign = -1.0 if direction in ASSET_DIRECTIONS else 1.0

            for d_idx, day in enumerate(days):
                if start_date <= day < maturity_date:
                    new_nominal[d_idx] = sign * new_volume

            if np.all(new_nominal == 0):
                continue

            next_deal_id += 1
            deal_id = next_deal_id

            synthetic_deals.append({
                "Dealid": deal_id,
                "Product": product,
                "Currency": currency,
                "Direction": direction,
                "Amount": sign * new_volume,
                "Clientrate": client_rate,
                "EqOisRate": ois_rate,
                "YTM": 0.0,
                "CocRate": ois_rate,
                "Spread": plan.rate_spread_bps / 10_000,
                "Valuedate": start_date,
                "Maturitydate": maturity_date,
                "IAS Book": "BOOK1",
                "Périmètre TOTAL": "CC",
                "is_floating": False,
                "RateRef": client_rate,
                "ref_index": "",
                "Floating Rates Short Name": "",
                "Strategy IAS": np.nan,
                "Counterparty": "PRODUCTION_PLAN",
                "is_synthetic": True,
            })
            synthetic_nominals.append(new_nominal)

            projection_log.append({
                "deal_id": deal_id,
                "product": product,
                "currency": currency,
                "direction": direction,
                "maturing_month": mat_month,
                "maturing_amount": round(maturing_amount, 0),
                "new_volume": round(new_volume, 0),
                "tenor_years": plan.tenor_years,
                "client_rate": round(client_rate, 6),
                "ois_rate": round(ois_rate, 6),
                "spread_bps": plan.rate_spread_bps,
                "start_date": str(start_date.date()),
                "maturity_date": str(maturity_date.date()),
            })

    if not synthetic_deals:
        return nominal_daily, deals, projection_log

    # Extend deals DataFrame
    synthetic_df = pd.DataFrame(synthetic_deals)
    # Ensure month columns exist in synthetic_df (filled with 0)
    for mc in month_cols:
        if mc not in synthetic_df.columns:
            synthetic_df[mc] = 0.0

    projected_deals = pd.concat([deals, synthetic_df], ignore_index=True)

    # Extend nominal_daily matrix
    synthetic_nominal_array = np.array(synthetic_nominals)  # (n_new, n_days)
    projected_nominal = np.vstack([nominal_daily, synthetic_nominal_array])

    logger.info(
        "project_balance_sheet: added %d synthetic deals across %d months",
        len(synthetic_deals), len(maturing_by_month),
    )
    return projected_nominal, projected_deals, projection_log
