"""Parser for production_plan.xlsx — reinvestment assumptions for dynamic balance sheet."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pnl_engine.dynamic_balance_sheet import ProductionPlan


SUPPORTED_CURRENCIES = {"CHF", "EUR", "USD", "GBP"}


def parse_production_plan(path: Path | str) -> list[ProductionPlan]:
    """Parse production plan Excel file.

    Expected sheet: "ProductionPlan" (or first sheet) with columns:
        product, currency, direction, monthly_volume, tenor_years,
        [rate_spread_bps]

    Returns:
        List of ProductionPlan dataclass instances.
    """
    path = Path(path)
    try:
        df = pd.read_excel(path, sheet_name="ProductionPlan", engine="openpyxl")
    except ValueError:
        df = pd.read_excel(path, sheet_name=0, engine="openpyxl")

    # Normalize column names
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    required = {"product", "currency", "direction", "monthly_volume", "tenor_years"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"production_plan.xlsx must have columns {required}, missing: {missing}"
        )

    # Filter valid currencies
    df["currency"] = df["currency"].str.upper().str.strip()
    df = df[df["currency"].isin(SUPPORTED_CURRENCIES)].copy()

    if "rate_spread_bps" not in df.columns:
        df["rate_spread_bps"] = 0.0

    plans = []
    for _, row in df.iterrows():
        try:
            plans.append(ProductionPlan(
                product=str(row["product"]).strip(),
                currency=str(row["currency"]).strip(),
                direction=str(row["direction"]).strip().upper(),
                monthly_volume=float(pd.to_numeric(row["monthly_volume"], errors="coerce") or 0),
                tenor_years=float(pd.to_numeric(row["tenor_years"], errors="coerce") or 0),
                rate_spread_bps=float(pd.to_numeric(row.get("rate_spread_bps", 0.0), errors="coerce") or 0),
            ))
        except (ValueError, TypeError) as e:
            logging.getLogger(__name__).warning("Skipping invalid production plan row: %s", e)
            continue

    return plans
