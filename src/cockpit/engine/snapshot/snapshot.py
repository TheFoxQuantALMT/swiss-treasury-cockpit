"""Portfolio snapshot assembler — orchestrates exposure, aggregation, counterparty modules."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from cockpit.engine.snapshot.aggregation import compute_positions
from cockpit.engine.snapshot.counterparty import compute_counterparty
from cockpit.engine.snapshot.enrichment import enrich_deals
from cockpit.engine.snapshot.exposure import compute_liquidity_ladder


def build_portfolio_snapshot(
    echeancier: pd.DataFrame,
    deals: pd.DataFrame,
    ref_table: pd.DataFrame,
    fx_rates: dict[str, float],
    cds_spreads: dict | None = None,
    ref_date: date | None = None,
) -> dict[str, Any]:
    """Build the complete portfolio snapshot from parsed data.

    Orchestration:
    1. enrich_deals() — join reference data onto deals
    2. compute_liquidity_ladder() — exposure section
    3. compute_positions() — positions section
    4. compute_counterparty() — counterparty section
    5. Assemble into final dict

    Returns:
        Dict ready for JSON serialization as portfolio_snapshot.json.
    """
    if ref_date is None:
        ref_date = date.today()

    enriched = enrich_deals(deals, ref_table)

    exposure = compute_liquidity_ladder(echeancier, enriched, ref_date)
    positions = compute_positions(enriched, fx_rates, ref_date)
    counterparty = compute_counterparty(enriched, cds_spreads, ref_date)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ref_date": ref_date.isoformat(),
        "exposure": exposure,
        "positions": positions,
        "counterparty": counterparty,
    }


def write_snapshot(snapshot: dict[str, Any], path: Path) -> Path:
    """Write portfolio snapshot dict to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2, default=str)
    return path
