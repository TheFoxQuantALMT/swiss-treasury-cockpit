"""Strategy IAS consolidated view — cross-book hedge effectiveness.

One row per ``Strategy IAS`` value, joining:

  * Book1 hedged-item clean-price FV change (from ``Clean Price`` × ``Amount``)
  * Book2 IRS ΔMtM (from :func:`pnl_engine.engine.compute_book2_mtm`)

into an effectiveness ratio ``−Δhedging / Δhedged_item`` with the IFRS 9
``[80%, 125%]`` corridor flag. Rows with no prior snapshot return NaN
for delta-dependent fields (first run after go-live, missing yesterday, etc.).

The module makes no WASP calls — it consumes already-computed MtM frames,
so it is safe on dev machines.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


EFFECTIVE_LOW = 0.80
EFFECTIVE_HIGH = 1.25

_HEDGED_PRODUCTS = {"IAM/LD", "BND", "FXS"}
_INSTRUMENT_PRODUCTS = {"IRS", "IRS-MTM", "HCD"}

# @Category2 → hedge-relationship type. Priority inside a strategy is
# FVH > FVO > CFH — a strategy with any FVH bucket is classified as FVH.
_HEDGE_TYPE_FROM_CATEGORY2 = {
    "OPP_Bond_ASW": "FVH",
    "OPR_FVH": "FVH",
    "IRS_FVH": "FVH",
    "IRS_FVO": "FVO",
    "IRS_ORC": "CFH",
    "OPR_ORC": "CFH",
    "OPR_nFVH": "CFH",
}


def _hedge_type(group_cat2: pd.Series) -> str:
    """Collapse @Category2 values within a strategy to a single hedge-type label."""
    cats = set(group_cat2.dropna().astype(str).unique())
    seen = {_HEDGE_TYPE_FROM_CATEGORY2.get(c) for c in cats}
    seen.discard(None)
    for t in ("FVH", "FVO", "CFH"):
        if t in seen:
            return t
    return "unknown"


def _corridor_flag(ratio: float, multi_ccy: bool) -> str:
    if multi_ccy:
        return "multi_ccy"
    if pd.isna(ratio):
        return "na"
    if ratio < EFFECTIVE_LOW:
        return "under"
    if ratio > EFFECTIVE_HIGH:
        return "over"
    return "ok"


def _dedup_bonds_per_strategy(deals: pd.DataFrame) -> pd.DataFrame:
    """Keep one BND row per (Strategy IAS, ISIN) — BOOK2 preferred over BOOK1.

    For an ASW bond the same underlying position is often mirrored across
    BOOK1 (accrual carrying value) and BOOK2 (MtM). Summing both double-counts
    the FV. BOOK2 is preferred because its Clean Price is the FV mark; where
    only BOOK1 exists (e.g. OPR_FVH bonds) the BOOK1 row is kept.
    """
    if "ISIN" not in deals.columns or "IAS Book" not in deals.columns:
        return deals.copy()
    bnd = deals[deals["Product"] == "BND"].copy()
    if bnd.empty:
        return bnd
    # Rank BOOK2 > BOOK1 so drop_duplicates(keep="first") retains BOOK2 when both exist
    bnd["_book_rank"] = bnd["IAS Book"].map({"BOOK2": 0, "BOOK1": 1}).fillna(2)
    bnd = bnd.sort_values("_book_rank")
    # If ISIN is blank (shouldn't be for bonds, but be defensive), fall back to Dealid
    key_cols = ["Strategy IAS", "ISIN"]
    dedup = bnd.drop_duplicates(subset=key_cols, keep="first").drop(columns="_book_rank")
    return dedup


def _bond_clean_delta(
    deals_today: pd.DataFrame,
    deals_prev: Optional[pd.DataFrame],
) -> pd.Series:
    """Per-strategy Σ |Amount_today| × (CleanPrice_today − CleanPrice_prev) / 100.

    Uses today's nominal as the exposure — new trades or liquidations between
    t-1 and t contribute zero because they have no counterpart on one side.
    Bonds are deduplicated per (Strategy IAS, ISIN) so ASW positions mirrored
    across both books are only counted once.
    """
    if deals_prev is None or deals_prev.empty:
        return pd.Series(dtype=float)
    needed = {"Dealid", "Strategy IAS", "Product", "Amount", "Clean Price"}
    if not needed.issubset(deals_today.columns) or not needed.issubset(deals_prev.columns):
        return pd.Series(dtype=float)

    t = _dedup_bonds_per_strategy(deals_today)[
        ["Dealid", "Strategy IAS", "Amount", "Clean Price"]
    ].rename(columns={"Clean Price": "cp_today", "Amount": "amt_today"})
    p = (deals_prev[deals_prev["Product"] == "BND"]
         [["Dealid", "Clean Price"]]
         .rename(columns={"Clean Price": "cp_prev"}))
    m = t.merge(p, on="Dealid", how="inner")
    m = m[m["cp_today"].notna() & m["cp_prev"].notna()]
    if m.empty:
        return pd.Series(dtype=float)

    m["dFV"] = m["amt_today"].abs() * (m["cp_today"] - m["cp_prev"]) / 100.0
    has_strat = m["Strategy IAS"].notna() & (m["Strategy IAS"].astype(str).str.strip() != "")
    return m[has_strat].groupby("Strategy IAS")["dFV"].sum()


def compute_book2_mtm_delta_by_currency(
    mtm_today: Optional[pd.DataFrame],
    mtm_prev: Optional[pd.DataFrame],
    irs_today: Optional[pd.DataFrame] = None,
    deals_prev: Optional[pd.DataFrame] = None,
    prev_date: Optional[str] = None,
) -> dict:
    """ΔMTM on BOOK2 IRS between two snapshots, aggregated by currency.

    Returns ``{"has_data", "rows": [...], "totals": {...}, "prev_date"}``.
    Each row: ``currency, n_deals, mtm_today, mtm_prev, delta``.

    Currency is resolved from whichever frame carries it:
      * today's MTM frame (Currency / "Currency Code (ISO)" column),
      * or ``irs_today`` joined on Dealid,
      * or ``deals_prev`` joined on Dealid for the prev leg.
    """
    if (
        mtm_today is None or mtm_today.empty
        or mtm_prev is None or mtm_prev.empty
        or "MTM" not in mtm_today.columns or "MTM" not in mtm_prev.columns
    ):
        return {"has_data": False}

    def _with_dealid(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if "Dealid" not in out.columns and "Deal" in out.columns:
            out["Dealid"] = out["Deal"]
        out["Dealid"] = pd.to_numeric(out["Dealid"], errors="coerce")
        return out.dropna(subset=["Dealid"])

    today = _with_dealid(mtm_today)
    prev = _with_dealid(mtm_prev)

    ccy_col_today = next(
        (c for c in ("Currency", "Currency Code (ISO)") if c in today.columns), None,
    )
    if ccy_col_today is None and irs_today is not None and not irs_today.empty:
        irs = irs_today.copy()
        deal_col = "Deal" if "Deal" in irs.columns else ("Dealid" if "Dealid" in irs.columns else None)
        ccy_src = next(
            (c for c in ("Currency Code (ISO)", "Currency") if c in irs.columns), None,
        )
        if deal_col and ccy_src:
            irs[deal_col] = pd.to_numeric(irs[deal_col], errors="coerce")
            today = today.merge(
                irs[[deal_col, ccy_src]].drop_duplicates(deal_col).rename(
                    columns={deal_col: "Dealid", ccy_src: "Currency"}),
                on="Dealid", how="left",
            )
            ccy_col_today = "Currency"
    if ccy_col_today is None:
        return {"has_data": False}
    if ccy_col_today != "Currency":
        today = today.rename(columns={ccy_col_today: "Currency"})

    if "Currency" not in prev.columns and deals_prev is not None and not deals_prev.empty:
        dp = deals_prev.copy()
        if "Dealid" in dp.columns and "Currency" in dp.columns:
            dp["Dealid"] = pd.to_numeric(dp["Dealid"], errors="coerce")
            prev = prev.merge(
                dp[["Dealid", "Currency"]].drop_duplicates("Dealid"),
                on="Dealid", how="left",
            )
    if "Currency" not in prev.columns:
        return {"has_data": False}

    t_agg = today.dropna(subset=["Currency"]).groupby("Currency")["MTM"].agg(
        mtm_today="sum", n_deals="size",
    )
    p_agg = prev.dropna(subset=["Currency"]).groupby("Currency")["MTM"].sum().rename(
        "mtm_prev",
    )
    merged = t_agg.join(p_agg, how="outer").fillna(0.0)
    merged["delta"] = merged["mtm_today"] - merged["mtm_prev"]

    rows = [
        {
            "currency": str(ccy),
            "n_deals": int(r["n_deals"]) if not np.isnan(r["n_deals"]) else 0,
            "mtm_today": float(r["mtm_today"]),
            "mtm_prev": float(r["mtm_prev"]),
            "delta": float(r["delta"]),
        }
        for ccy, r in merged.iterrows()
    ]
    totals = {
        "mtm_today": float(merged["mtm_today"].sum()),
        "mtm_prev": float(merged["mtm_prev"].sum()),
        "delta": float(merged["delta"].sum()),
    }
    return {"has_data": True, "rows": rows, "totals": totals, "prev_date": prev_date}


def _mtm_by_strategy(book2_mtm: Optional[pd.DataFrame]) -> pd.Series:
    """Sum MTM per strategy for today's Book2 IRS frame."""
    if book2_mtm is None or book2_mtm.empty or "MTM" not in book2_mtm.columns:
        return pd.Series(dtype=float)
    strat_col = next(
        (c for c in ("Strategy (Agapes IAS)", "Strategy IAS") if c in book2_mtm.columns),
        None,
    )
    if strat_col is None:
        return pd.Series(dtype=float)
    mask = book2_mtm[strat_col].notna() & (book2_mtm[strat_col].astype(str).str.strip() != "")
    return book2_mtm[mask].groupby(strat_col)["MTM"].sum()


def _mtm_delta_by_strategy(
    today: Optional[pd.DataFrame],
    prev: Optional[pd.DataFrame],
) -> pd.Series:
    """Per-strategy Σ (MTM_today − MTM_prev) via per-deal join."""
    if today is None or prev is None or today.empty or prev.empty:
        return pd.Series(dtype=float)
    if "MTM" not in today.columns or "MTM" not in prev.columns:
        return pd.Series(dtype=float)

    deal_col_t = "Deal" if "Deal" in today.columns else ("Dealid" if "Dealid" in today.columns else None)
    deal_col_p = "Deal" if "Deal" in prev.columns else ("Dealid" if "Dealid" in prev.columns else None)
    strat_col = next(
        (c for c in ("Strategy (Agapes IAS)", "Strategy IAS") if c in today.columns),
        None,
    )
    if deal_col_t is None or deal_col_p is None or strat_col is None:
        return pd.Series(dtype=float)

    t = today[[deal_col_t, strat_col, "MTM"]].rename(
        columns={deal_col_t: "Deal", strat_col: "Strategy", "MTM": "mtm_today"},
    )
    p = prev[[deal_col_p, "MTM"]].rename(
        columns={deal_col_p: "Deal", "MTM": "mtm_prev"},
    )
    m = t.merge(p, on="Deal", how="inner")
    if m.empty:
        return pd.Series(dtype=float)

    m["dMTM"] = m["mtm_today"] - m["mtm_prev"]
    mask = m["Strategy"].notna() & (m["Strategy"].astype(str).str.strip() != "")
    return m[mask].groupby("Strategy")["dMTM"].sum()


def compute_strategy_consolidated(
    deals_today: pd.DataFrame,
    book2_mtm_today: Optional[pd.DataFrame] = None,
    deals_prev: Optional[pd.DataFrame] = None,
    book2_mtm_prev: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Build one row per Strategy IAS with hedge-effectiveness metrics.

    Parameters
    ----------
    deals_today : DataFrame
        Today's deals (output of :func:`parse_bank_native_deals`). Must carry
        ``Strategy IAS``, ``Product``, ``Amount``, ``Currency``, ``Clean Price``,
        ``Category2``.
    book2_mtm_today : DataFrame | None
        Today's Book2 IRS MTM (output of :func:`compute_book2_mtm`). None when
        WASP is unavailable — instrument side becomes NaN.
    deals_prev : DataFrame | None
        Yesterday's deals. Required for hedged-item ΔFV; None → NaN.
    book2_mtm_prev : DataFrame | None
        Yesterday's Book2 MTM. Required for hedging-instrument ΔMtM; None → NaN.

    Returns
    -------
    DataFrame with columns:
        strategy_ias, hedge_type, currencies, multi_currency,
        n_hedged, n_hedging, n_hedging_book2,
        hedged_clean_fv_today, hedged_clean_dFV,
        hedging_irs_mtm_today, hedging_irs_dMtM,
        effectiveness_ratio, corridor_flag
    """
    if deals_today is None or deals_today.empty or "Strategy IAS" not in deals_today.columns:
        return pd.DataFrame()

    strat_col = "Strategy IAS"
    strat_deals = deals_today[
        deals_today[strat_col].notna() & (deals_today[strat_col].astype(str).str.strip() != "")
    ].copy()
    if strat_deals.empty:
        return pd.DataFrame()

    # Today's hedged-item clean FV (a stock, positive per bank long position).
    # Dedup ASW bonds mirrored across BOOK1 (accrual) and BOOK2 (MtM) — count once.
    fv_today = pd.Series(dtype=float)
    bnd_dedup_today = _dedup_bonds_per_strategy(deals_today)
    if not bnd_dedup_today.empty and "Clean Price" in bnd_dedup_today.columns:
        bnd_t = bnd_dedup_today[bnd_dedup_today["Clean Price"].notna()].copy()
        if not bnd_t.empty:
            bnd_t["_fv"] = bnd_t["Amount"].abs() * bnd_t["Clean Price"] / 100.0
            mask = bnd_t[strat_col].notna() & (bnd_t[strat_col].astype(str).str.strip() != "")
            fv_today = bnd_t[mask].groupby(strat_col)["_fv"].sum()

    dfv = _bond_clean_delta(deals_today, deals_prev)
    mtm_today = _mtm_by_strategy(book2_mtm_today)
    dmtm = _mtm_delta_by_strategy(book2_mtm_today, book2_mtm_prev)

    # Count of Book2 hedging instruments per strategy (for visibility)
    if book2_mtm_today is not None and not book2_mtm_today.empty:
        b2_strat_col = next(
            (c for c in ("Strategy (Agapes IAS)", "Strategy IAS") if c in book2_mtm_today.columns),
            None,
        )
        if b2_strat_col:
            n_book2 = book2_mtm_today.groupby(b2_strat_col).size()
        else:
            n_book2 = pd.Series(dtype=int)
    else:
        n_book2 = pd.Series(dtype=int)

    # Deduped BND rows per strategy for hedged-item counts (ASW mirror once)
    bnd_by_strat = (
        bnd_dedup_today.groupby(strat_col).size()
        if not bnd_dedup_today.empty
        else pd.Series(dtype=int)
    )

    rows = []
    for s in sorted(strat_deals[strat_col].unique()):
        group = strat_deals[strat_deals[strat_col] == s]
        non_bnd_hedged = group[
            group["Product"].isin(_HEDGED_PRODUCTS) & (group["Product"] != "BND")
        ]
        hedging = group[group["Product"].isin(_INSTRUMENT_PRODUCTS)]
        ccys = sorted(group["Currency"].dropna().unique())

        fv_t = float(fv_today.get(s, np.nan)) if not fv_today.empty else np.nan
        dfv_s = float(dfv.get(s, np.nan)) if not dfv.empty else np.nan
        mtm_t = float(mtm_today.get(s, np.nan)) if not mtm_today.empty else np.nan
        dmtm_s = float(dmtm.get(s, np.nan)) if not dmtm.empty else np.nan

        # Effectiveness ratio: −Δhedging / Δhedged_item, target ≈ 1.0
        if pd.isna(dmtm_s) or pd.isna(dfv_s) or dfv_s == 0:
            ratio = np.nan
        else:
            ratio = -dmtm_s / dfv_s

        multi_ccy = len(ccys) > 1
        n_bnd = int(bnd_by_strat.get(s, 0))

        rows.append({
            "strategy_ias": s,
            "hedge_type": _hedge_type(group.get("Category2", pd.Series(dtype=object))),
            "currencies": "/".join(ccys),
            "multi_currency": multi_ccy,
            "n_hedged": int(len(non_bnd_hedged)) + n_bnd,
            "n_hedging": int(len(hedging)),
            "n_hedging_book2": int(n_book2.get(s, 0)),
            "hedged_clean_fv_today": fv_t,
            "hedged_clean_dFV": dfv_s,
            "hedging_irs_mtm_today": mtm_t,
            "hedging_irs_dMtM": dmtm_s,
            "effectiveness_ratio": ratio,
            "corridor_flag": _corridor_flag(ratio, multi_ccy),
        })

    return pd.DataFrame(rows)
