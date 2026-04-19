"""Daily KPI snapshot storage and retrieval for trend analysis.

Saves a compact daily snapshot of key ALM metrics and loads historical
series for the Trends dashboard tab.

Also stores the per-deal inputs needed by the cross-book hedge-effectiveness
consolidator (``pnl_engine.strategy_consolidated``) — namely bond Clean Prices
and Book2 IRS MTM — so tomorrow's run can compute ΔFV / ΔMtM against today's.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _json_default(v):
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.integer):
        return int(v)
    return str(v)


def save_daily_kpis(
    dashboard_data: dict,
    date: str,
    output_dir: Path,
) -> Path | None:
    """Save daily KPI snapshot from build_pnl_dashboard_data result.

    Args:
        dashboard_data: Full result dict from build_pnl_dashboard_data().
        date: Date string (YYYY-MM-DD).
        output_dir: Directory for snapshot files.

    Returns:
        Path to saved file, or None if no data.
    """
    kpis = {}

    # NII (base)
    summary = dashboard_data.get("summary", {})
    shock_0 = summary.get("kpis", {}).get("shock_0", {})
    if shock_0:
        kpis["nii_base"] = shock_0.get("total", 0)

    # NII sensitivity (+50bp - base)
    kpis["nii_sensitivity_50bp"] = summary.get("kpis", {}).get("delta_50_0", 0)

    # NIM
    nim = dashboard_data.get("nim", {})
    if nim.get("has_data"):
        kpis["nim_bps"] = nim.get("kpis", {}).get("nim_bps", 0)

    # EVE
    eve = dashboard_data.get("eve", {})
    if eve.get("has_data"):
        kpis["eve_total"] = eve.get("total_eve", 0)
        conv = eve.get("convexity", {})
        if conv:
            kpis["effective_duration"] = conv.get("effective_duration", 0)
        sc = eve.get("scenarios", {})
        if sc:
            kpis["eve_worst_delta"] = sc.get("worst_delta", 0)

    # Counterparty HHI
    cpty = dashboard_data.get("counterparty_pnl", {})
    if cpty.get("has_data"):
        kpis["hhi"] = cpty.get("hhi", 0)

    # Liquidity survival
    liq = dashboard_data.get("liquidity", {})
    if liq.get("has_data"):
        liq_sum = liq.get("summary", {})
        kpis["liquidity_net_30d"] = liq_sum.get("net_30d", 0)
        if liq_sum.get("survival_days") is not None:
            kpis["survival_days"] = liq_sum["survival_days"]

    # Alert count
    alerts = dashboard_data.get("pnl_alerts", {})
    if alerts.get("has_data"):
        a_sum = alerts.get("summary", {})
        kpis["alert_count"] = (
            a_sum.get("critical", 0) + a_sum.get("high", 0) + a_sum.get("medium", 0)
        )

    if not kpis:
        return None

    snapshot = {"date": date, **{k: round(float(v), 2) if v is not None else None for k, v in kpis.items()}}

    snapshot_dir = output_dir / "kpi_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_kpis.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return out_path


def load_kpi_history(
    snapshot_dir: Path,
    lookback_days: int = 90,
) -> Optional[pd.DataFrame]:
    """Load KPI history from snapshot files.

    Args:
        snapshot_dir: Directory containing *_kpis.json files.
        lookback_days: Maximum number of days to look back.

    Returns:
        DataFrame with date column + one column per metric.
        Returns None if no snapshots found.
    """
    kpi_dir = snapshot_dir / "kpi_snapshots"
    if not kpi_dir.exists():
        return None

    files = sorted(kpi_dir.glob("*_kpis.json"))
    if not files:
        return None

    rows = []
    for f in files[-lookback_days:]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            rows.append(data)
        except Exception:
            continue

    if not rows:
        return None

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Realized daily P&L snapshot (for MTD accumulation)
# ---------------------------------------------------------------------------

def save_realized_daily(
    pnl_data: Optional[pd.DataFrame],
    book2_non_irs: Optional[pd.DataFrame],
    date: str,
    output_dir: Path,
) -> Path | None:
    """Persist today's per-currency realized totals for later MTD accumulation.

    Aggregates ``PnL_Acc_Adj`` and ``PnL_Realized`` from ``pnl_data`` (BOOK1)
    and ``PnL_Realized`` from ``book2_non_irs`` (BOOK2) by Currency. Writes
    ``kpi_snapshots/{date}_realized.json``. Returns ``None`` when there is
    nothing to record.
    """
    def _agg(df: Optional[pd.DataFrame], col: str) -> dict[str, float]:
        if df is None or df.empty or col not in df.columns or "Currency" not in df.columns:
            return {}
        sub = df[["Currency", col]].copy()
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
        grouped = sub.dropna(subset=["Currency"]).groupby("Currency")[col].sum()
        return {str(k): float(v) for k, v in grouped.items() if float(v) != 0.0}

    payload = {
        "date": date,
        "book1_accrual": _agg(pnl_data, "PnL_Acc_Adj"),
        "book1_ias": _agg(pnl_data, "PnL_Realized"),
        "book2_mtm": _agg(book2_non_irs, "PnL_Realized"),
    }
    if not any(payload[k] for k in ("book1_accrual", "book1_ias", "book2_mtm")):
        return None

    snapshot_dir = output_dir / "kpi_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_realized.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def load_realized_mtd(
    snapshot_dir: Path,
    month_start: str,
    date_run: str,
) -> Optional[dict]:
    """Sum realized daily snapshots across ``[month_start, date_run]`` inclusive.

    Returns ``{has_data, month_start, date_run, days_counted, rows, totals}``
    where each row is ``{currency, book1_accrual, book1_ias, book2_mtm, total}``
    and ``days_counted`` is the number of snapshots actually found.
    """
    kpi_dir = snapshot_dir / "kpi_snapshots"
    if not kpi_dir.exists():
        return None

    files = sorted(kpi_dir.glob("*_realized.json"))
    if not files:
        return None

    per_ccy: dict[str, dict[str, float]] = {}
    days_counted = 0
    for f in files:
        d = f.name.split("_")[0]
        if d < month_start or d > date_run:
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        days_counted += 1
        for field in ("book1_accrual", "book1_ias", "book2_mtm"):
            for ccy, v in (payload.get(field) or {}).items():
                per_ccy.setdefault(ccy, {"book1_accrual": 0.0, "book1_ias": 0.0, "book2_mtm": 0.0})
                per_ccy[ccy][field] += float(v)

    if not per_ccy:
        return {
            "has_data": False, "month_start": month_start, "date_run": date_run,
            "days_counted": days_counted, "rows": [], "totals": {},
        }

    preferred = ["CHF", "EUR", "USD", "GBP"]
    ordered = [c for c in preferred if c in per_ccy] + sorted(c for c in per_ccy if c not in preferred)
    rows = []
    tot = {"book1_accrual": 0.0, "book1_ias": 0.0, "book2_mtm": 0.0}
    for ccy in ordered:
        v = per_ccy[ccy]
        row_total = v["book1_accrual"] + v["book1_ias"]  # BOOK1-only per sheet scope
        rows.append({
            "currency": ccy,
            "book1_accrual": v["book1_accrual"],
            "book1_ias": v["book1_ias"],
            "book2_mtm": v["book2_mtm"],
            "book1_total": row_total,
        })
        for k in tot:
            tot[k] += v[k]
    totals = {**tot, "book1_total": tot["book1_accrual"] + tot["book1_ias"]}
    return {
        "has_data": True, "month_start": month_start, "date_run": date_run,
        "days_counted": days_counted, "rows": rows, "totals": totals,
    }


# ---------------------------------------------------------------------------
# P&L Explain snapshot (for Month-over-Month attribution waterfall)
# ---------------------------------------------------------------------------

_EXPLAIN_INDICES = ("PnL_Simple", "Nominal", "OISfwd", "RateRef")


def save_pnl_explain_snapshot(
    pnl_by_deal: Optional[pd.DataFrame],
    pnl_all_s: Optional[pd.DataFrame],
    date: str,
    output_dir: Path,
) -> Path | None:
    """Persist the subset of engine outputs needed to recompute P&L Explain later.

    Aggregates ``pnl_by_deal`` to per-deal totals at Shock=0 (the inputs
    ``compute_pnl_explain`` consumes after its own internal aggregation) and
    keeps the ``pnl_all_s`` rows for the four indices used to derive the
    rate/spread effects. Writes ``kpi_snapshots/{date}_explain.json``.
    """
    if pnl_by_deal is None or pnl_by_deal.empty:
        return None
    if pnl_all_s is None or pnl_all_s.empty:
        return None

    by_deal = pnl_by_deal
    if "Shock" in by_deal.columns:
        by_deal = by_deal[by_deal["Shock"].astype(str) == "0"]
    if by_deal.empty:
        return None

    group_cols = [c for c in ("Dealid", "Counterparty", "Currency", "Product", "Direction")
                  if c in by_deal.columns]
    if "Dealid" not in group_cols:
        return None

    agg_deal = by_deal.groupby(group_cols, dropna=False).agg(
        PnL_Simple=("PnL_Simple", "sum"),
        Nominal=("Nominal", "mean"),
    ).reset_index()

    all_s = pnl_all_s.reset_index() if isinstance(pnl_all_s.index, pd.MultiIndex) else pnl_all_s.copy()
    required = {"Indice", "Shock", "Deal currency", "Value"}
    if not required.issubset(all_s.columns):
        return None
    all_s = all_s[(all_s["Shock"].astype(str) == "0") & (all_s["Indice"].isin(_EXPLAIN_INDICES))]
    if all_s.empty:
        return None

    payload = {
        "date": date,
        "pnl_by_deal": agg_deal.to_dict(orient="records"),
        "pnl_all_s": all_s[["Indice", "Shock", "Deal currency", "Value"]]
            .to_dict(orient="records"),
    }

    snapshot_dir = output_dir / "kpi_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_explain.json"

    out_path.write_text(
        json.dumps(payload, indent=2, default=_json_default, allow_nan=True),
        encoding="utf-8",
    )
    return out_path


def load_pnl_explain_snapshot(
    snapshot_dir: Path,
    on_or_before: Optional[str] = None,
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[str]]:
    """Load the most recent explain snapshot on or before ``on_or_before``.

    Returns ``(pnl_by_deal, pnl_all_s, date)``; any element may be ``None``.
    The returned frames have the shape ``compute_pnl_explain`` expects:
    ``pnl_by_deal`` is already deal-aggregated (the internal
    ``_aggregate_deal_pnl`` is idempotent on these inputs) and ``pnl_all_s``
    carries the Shock=0 rows for the indices we care about.
    """
    kpi_dir = snapshot_dir / "kpi_snapshots"
    if not kpi_dir.exists():
        return None, None, None

    files = sorted(kpi_dir.glob("*_explain.json"))
    if not files:
        return None, None, None

    if on_or_before is not None:
        files = [f for f in files if f.name.split("_")[0] <= on_or_before]
    if not files:
        return None, None, None

    latest = files[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None

    by_deal_records = payload.get("pnl_by_deal") or []
    all_s_records = payload.get("pnl_all_s") or []
    # Inject Shock column so compute_pnl_explain's shock filter passes through.
    if by_deal_records:
        by_deal_df = pd.DataFrame(by_deal_records)
        by_deal_df["Shock"] = "0"
    else:
        by_deal_df = None
    all_s_df = pd.DataFrame(all_s_records) if all_s_records else None
    return by_deal_df, all_s_df, payload.get("date")


# ---------------------------------------------------------------------------
# Strategy-consolidated per-deal snapshot (for cross-book hedge effectiveness)
# ---------------------------------------------------------------------------

_STRAT_DEAL_COLS = [
    "Dealid", "Product", "IAS Book", "Strategy IAS", "Amount",
    "Currency", "Clean Price", "Category2", "ISIN", "Direction",
]
_STRAT_MTM_COLS = ["Deal", "Dealid", "Strategy (Agapes IAS)", "MTM"]


def save_strategy_snapshot(
    deals_full: pd.DataFrame,
    book2_mtm: Optional[pd.DataFrame],
    date: str,
    output_dir: Path,
) -> Path | None:
    """Persist per-deal inputs required to compute tomorrow's effectiveness deltas.

    Writes ``{date}_strategy.json`` containing two lists of records:
    ``deals`` (Clean Price and direction per BND/IAM-LD row) and ``book2_mtm``
    (one row per Book2 IRS with its MTM). Returns ``None`` when there is
    nothing worth persisting.
    """
    if deals_full is None or deals_full.empty:
        return None

    deal_cols = [c for c in _STRAT_DEAL_COLS if c in deals_full.columns]
    if not deal_cols:
        return None
    deals_slim = deals_full[deal_cols].copy()

    mtm_records: list[dict] = []
    if book2_mtm is not None and not book2_mtm.empty:
        mtm_cols = [c for c in _STRAT_MTM_COLS if c in book2_mtm.columns]
        if mtm_cols:
            mtm_slim = book2_mtm[mtm_cols].copy()
            mtm_records = mtm_slim.to_dict(orient="records")

    payload = {
        "date": date,
        "deals": deals_slim.to_dict(orient="records"),
        "book2_mtm": mtm_records,
    }

    snapshot_dir = output_dir / "kpi_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshot_dir / f"{date}_strategy.json"

    out_path.write_text(
        json.dumps(payload, indent=2, default=_json_default, allow_nan=True),
        encoding="utf-8",
    )
    return out_path


def load_strategy_snapshot(
    snapshot_dir: Path,
    on_or_before: Optional[str] = None,
) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], Optional[str]]:
    """Load the most recent strategy snapshot on or before ``on_or_before``.

    Returns ``(deals_prev, book2_mtm_prev, date)`` — any of which may be
    ``None`` when the file is missing or empty. ``date`` is the ISO date of
    the snapshot actually loaded.
    """
    strat_dir = snapshot_dir / "kpi_snapshots"
    if not strat_dir.exists():
        return None, None, None

    files = sorted(strat_dir.glob("*_strategy.json"))
    if not files:
        return None, None, None

    if on_or_before is not None:
        files = [f for f in files if f.name.split("_")[0] <= on_or_before]
    if not files:
        return None, None, None

    latest = files[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None

    deals_records = payload.get("deals") or []
    mtm_records = payload.get("book2_mtm") or []
    deals_df = pd.DataFrame(deals_records) if deals_records else None
    mtm_df = pd.DataFrame(mtm_records) if mtm_records else None
    return deals_df, mtm_df, payload.get("date")
