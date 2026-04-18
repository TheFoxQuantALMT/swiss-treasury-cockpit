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
    by_currency: bool = False,
) -> pd.DataFrame:
    """Roll per-deal monthly P&L up to the ``(IAS Book, Category2)`` grid.

    Parameters
    ----------
    pnl_by_deal
        Long-format engine output: one row per ``(Dealid, Shock, Month)`` with
        a ``PnL_Simple`` column. Only rows matching ``shock`` are kept.
    deals
        Canonical deals DataFrame carrying ``Dealid``, ``IAS Book`` and
        ``Category2`` (and ``Currency`` when ``by_currency=True``).
    shock
        Shock label to filter on (e.g. ``"0"`` for unshocked, ``"50"`` for
        +50bp). Required — passing the wrong value silently returns empty.
    by_currency
        When True, adds ``Currency`` as a third row dimension (one row per
        bucket × currency combination, plus one ``FVH All`` row per currency).

    Returns
    -------
    pd.DataFrame
        Wide DataFrame with ``IAS Book``, ``Category2`` (and optionally
        ``Currency``) as the first columns, followed by one ``YYYY/MM``
        column per forecast month. Trailing rows are the derived ``FVH All``
        aggregate(s).
    """
    header_cols = ["IAS Book", "Category2"] + (["Currency"] if by_currency else [])

    if pnl_by_deal is None or pnl_by_deal.empty:
        logger.warning("build_synthesis: pnl_by_deal is empty — returning empty Synthesis")
        return pd.DataFrame(columns=header_cols)

    required = {"Dealid", "Month", "PnL_Simple"}
    missing = required - set(pnl_by_deal.columns)
    if missing:
        raise ValueError(f"build_synthesis: pnl_by_deal missing columns {sorted(missing)}")
    if not {"Dealid", "IAS Book", "Category2"}.issubset(deals.columns):
        raise ValueError("build_synthesis: deals must carry Dealid, IAS Book, Category2")
    if by_currency and "Currency" not in deals.columns:
        raise ValueError("build_synthesis: by_currency=True requires 'Currency' in deals")

    df = pnl_by_deal
    if "Shock" in df.columns:
        df = df[df["Shock"].astype(str) == str(shock)]
        if df.empty:
            logger.warning("build_synthesis: no rows for shock=%s", shock)
            return pd.DataFrame(columns=header_cols)

    tax_cols = ["Dealid", "IAS Book", "Category2"] + (["Currency"] if by_currency else [])
    taxonomy = (
        deals[tax_cols]
        .drop_duplicates(subset=["Dealid"])
        .assign(Dealid=lambda d: d["Dealid"].astype(str))
    )
    # Drop any taxonomy columns already present on the left to avoid _x/_y
    # suffix collisions (pnl_by_deal carries Currency in deal-level exports).
    df_for_merge = df.drop(
        columns=[c for c in tax_cols if c != "Dealid" and c in df.columns]
    ).assign(Dealid=lambda d: d["Dealid"].astype(str))
    joined = df_for_merge.merge(taxonomy, on="Dealid", how="left")

    dropna_cols = ["IAS Book", "Category2"] + (["Currency"] if by_currency else [])
    orphans = joined[dropna_cols].isna().any(axis=1).sum()
    if orphans:
        logger.warning("build_synthesis: %d deal-month rows without %s (dropped)",
                       orphans, "/".join(dropna_cols))
        joined = joined.dropna(subset=dropna_cols)

    joined["Month_Label"] = joined["Month"].dt.strftime("%Y/%m")
    index_cols = ["IAS Book", "Category2"] + (["Currency"] if by_currency else [])
    grid = joined.pivot_table(
        index=index_cols,
        columns="Month_Label",
        values="PnL_Simple",
        aggfunc="sum",
        fill_value=0.0,
    )
    grid.columns.name = None
    month_cols = sorted(grid.columns)  # YYYY/MM format sorts chronologically

    if by_currency:
        currencies = sorted(joined["Currency"].dropna().unique().tolist())
        full_index = pd.MultiIndex.from_tuples(
            [(b, c, ccy) for b, c in _BUCKET_ORDER for ccy in currencies],
            names=index_cols,
        )
    else:
        full_index = pd.MultiIndex.from_tuples(_BUCKET_ORDER, names=index_cols)

    ordered = (
        grid.reindex(full_index, fill_value=0.0)
        .reindex(columns=month_cols, fill_value=0.0)
        .reset_index()
    )

    fvh_mask = ordered["Category2"].isin(CATEGORY2_FVH_ALL)
    if by_currency:
        fvh_rows = (
            ordered.loc[fvh_mask]
            .groupby("Currency", as_index=False)[month_cols].sum()
            .assign(**{"IAS Book": "", "Category2": FVH_ALL_LABEL})
        )
        ordered = pd.concat([ordered, fvh_rows], ignore_index=True)
    else:
        fvh_row = ordered.loc[fvh_mask, month_cols].sum().to_dict()
        fvh_row["IAS Book"] = ""
        fvh_row["Category2"] = FVH_ALL_LABEL
        ordered = pd.concat([ordered, pd.DataFrame([fvh_row])], ignore_index=True)

    return ordered[[*index_cols, *month_cols]]


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
