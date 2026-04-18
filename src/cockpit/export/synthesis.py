"""Bank-native Synthesis exporter.

Produces the monthly ``Synthesis`` sheet expected by the bank: one row per
``(IAS Book, Category2)`` bucket plus a derived ``FVH All`` row (union of the
three FVH-flavoured buckets across both books), with one column per month in
the 5-year forecast horizon.

For Phase 4 the sheet is pure engine-forecast output. The realized/forecast
stitch for the current month (Σ realized days + Σ forecast remaining days)
will be layered on in Phase 5 when daily reconciliation lands.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from pnl_engine.config import (
    CATEGORY2_FVH_ALL,
    VALID_CATEGORY2_BOOK1,
    VALID_CATEGORY2_BOOK2,
)

logger = logging.getLogger(__name__)

SYNTHESIS_SHEET_NAME = "Synthesis"
FVH_ALL_LABEL = "FVH All"

# Canonical (Book, Category2) ordering for the Synthesis sheet. The tuples are
# hand-ordered (config uses sets, which are unordered); the asserts guard
# against silent drift if the config taxonomy changes.
_BUCKET_ORDER: tuple[tuple[str, str], ...] = (
    ("BOOK1", "OPP_CASH"),
    ("BOOK1", "OPP_Bond_ASW"),
    ("BOOK1", "OPP_Bond_nASW"),
    ("BOOK1", "OPR_FVH"),
    ("BOOK1", "OPR_nFVH"),
    ("BOOK1", "Other"),
    ("BOOK2", "OPP_Bond_ASW"),
    ("BOOK2", "OPR_FVH"),
    ("BOOK2", "IRS_FVH"),
    ("BOOK2", "IRS_FVO"),
)
assert {c for b, c in _BUCKET_ORDER if b == "BOOK1"} == VALID_CATEGORY2_BOOK1, \
    "_BUCKET_ORDER drift vs VALID_CATEGORY2_BOOK1"
assert {c for b, c in _BUCKET_ORDER if b == "BOOK2"} == VALID_CATEGORY2_BOOK2, \
    "_BUCKET_ORDER drift vs VALID_CATEGORY2_BOOK2"


def build_synthesis(
    pnl_by_deal: pd.DataFrame,
    deals: pd.DataFrame,
    *,
    shock: str,
) -> pd.DataFrame:
    """Roll per-deal monthly P&L up to the ``(IAS Book, Category2)`` grid.

    Parameters
    ----------
    pnl_by_deal
        Long-format engine output: one row per ``(Dealid, Shock, Month)`` with
        a ``PnL`` column. Only rows matching ``shock`` are kept.
    deals
        Canonical deals DataFrame carrying ``Dealid``, ``IAS Book`` and
        ``Category2``. Supplies the Book/Category2 lookup since engine output
        does not carry the bank-native taxonomy.
    shock
        Shock label to filter on (e.g. ``"0"`` for unshocked, ``"50"`` for
        +50bp). Required — passing the wrong value silently returns empty.

    Returns
    -------
    pd.DataFrame
        Wide DataFrame with ``IAS Book`` and ``Category2`` as the first two
        columns, followed by one ``YYYY/MM`` column per forecast month. The
        last row is the derived ``FVH All`` aggregate across both books.
    """
    if pnl_by_deal is None or pnl_by_deal.empty:
        logger.warning("build_synthesis: pnl_by_deal is empty — returning empty Synthesis")
        return pd.DataFrame(columns=["IAS Book", "Category2"])

    required = {"Dealid", "Month", "PnL"}
    missing = required - set(pnl_by_deal.columns)
    if missing:
        raise ValueError(f"build_synthesis: pnl_by_deal missing columns {sorted(missing)}")
    if not {"Dealid", "IAS Book", "Category2"}.issubset(deals.columns):
        raise ValueError("build_synthesis: deals must carry Dealid, IAS Book, Category2")

    df = pnl_by_deal
    if "Shock" in df.columns:
        df = df[df["Shock"].astype(str) == str(shock)]
        if df.empty:
            logger.warning("build_synthesis: no rows for shock=%s", shock)
            return pd.DataFrame(columns=["IAS Book", "Category2"])

    taxonomy = (
        deals[["Dealid", "IAS Book", "Category2"]]
        .drop_duplicates(subset=["Dealid"])
        .assign(Dealid=lambda d: d["Dealid"].astype(str))
    )
    joined = df.assign(Dealid=lambda d: d["Dealid"].astype(str)).merge(
        taxonomy, on="Dealid", how="left"
    )

    orphans = joined["IAS Book"].isna().sum()
    if orphans:
        logger.warning("build_synthesis: %d deal-month rows without book/category (dropped)", orphans)
        joined = joined.dropna(subset=["IAS Book", "Category2"])

    joined["Month_Label"] = joined["Month"].dt.strftime("%Y/%m")
    grid = joined.pivot_table(
        index=["IAS Book", "Category2"],
        columns="Month_Label",
        values="PnL",
        aggfunc="sum",
        fill_value=0.0,
    )
    grid.columns.name = None

    month_cols = sorted(grid.columns)  # YYYY/MM format sorts chronologically
    ordered = (
        grid.reindex(pd.MultiIndex.from_tuples(_BUCKET_ORDER, names=["IAS Book", "Category2"]),
                     fill_value=0.0)
        .reindex(columns=month_cols, fill_value=0.0)
        .reset_index()
    )

    fvh_mask = ordered["Category2"].isin(CATEGORY2_FVH_ALL)
    fvh_row = ordered.loc[fvh_mask, month_cols].sum().to_dict()
    fvh_row["IAS Book"] = ""
    fvh_row["Category2"] = FVH_ALL_LABEL
    ordered = pd.concat([ordered, pd.DataFrame([fvh_row])], ignore_index=True)

    return ordered[["IAS Book", "Category2", *month_cols]]


def export_synthesis_to_excel(synthesis: pd.DataFrame, path: Path) -> Path:
    """Write a Synthesis DataFrame to ``path`` under sheet ``Synthesis``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        synthesis.to_excel(writer, sheet_name=SYNTHESIS_SHEET_NAME, index=False)
    logger.info("Synthesis written to %s (%d rows, %d months)",
                path, len(synthesis), len(synthesis.columns) - 2)
    return path


__all__ = [
    "SYNTHESIS_SHEET_NAME",
    "FVH_ALL_LABEL",
    "build_synthesis",
    "export_synthesis_to_excel",
]
