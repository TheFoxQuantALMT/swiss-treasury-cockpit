"""Counterparty analysis — concentration, rating, HQLA, country, CDS overlay."""
from __future__ import annotations

from datetime import date

import pandas as pd

from cockpit.config import RATING_BUCKETS, HQLA_LEVELS, CDS_ALERT_THRESHOLD_BPS


def _rating_to_bucket(rating: str) -> str:
    """Map a granular rating (e.g. 'AA+') to a bucket label (e.g. 'AAA-AA')."""
    for bucket, ratings in RATING_BUCKETS.items():
        if rating in ratings:
            return bucket
    return "NR"


def _compute_hhi(shares: pd.Series) -> float:
    """Herfindahl-Hirschman Index from market share percentages (0–10000 scale)."""
    pct = shares / shares.sum() * 100
    return float((pct ** 2).sum())


def compute_counterparty(
    deals: pd.DataFrame,
    cds_spreads: dict | None,
    ref_date: date | None = None,
) -> dict:
    """Compute counterparty analysis: concentration, rating, HQLA, country, CDS.

    Args:
        deals: Enriched DataFrame with 'rating', 'hqla_level', 'country' columns.
        cds_spreads: Optional dict {counterparty: spread_bps}.
        ref_date: Reference date for the snapshot.
    """
    if ref_date is None:
        ref_date = date.today()

    deals = deals.copy()
    deals["abs_amount"] = deals["Amount"].abs()
    total_nominal = deals["abs_amount"].sum()

    # ── Concentration ─────────────────────────────────────────────
    cpty_agg = deals.groupby("Counterparty").agg(
        nominal=("abs_amount", "sum"),
    ).sort_values("nominal", ascending=False).reset_index()

    top_10_df = cpty_agg.head(10)
    top_10 = []
    for _, row in top_10_df.iterrows():
        cpty = row["Counterparty"]
        nom = row["nominal"]
        peri_series = deals.loc[deals["Counterparty"] == cpty, "Périmètre TOTAL"] if "Périmètre TOTAL" in deals.columns else pd.Series(dtype=str)
        peri = peri_series.iloc[0] if not peri_series.empty else "CC"
        top_10.append({
            "counterparty": cpty,
            "nominal": float(nom),
            "pct_total": round(float(nom / total_nominal * 100), 2) if total_nominal > 0 else 0.0,
            "perimeter": peri,
        })

    hhi = _compute_hhi(cpty_agg["nominal"]) if len(cpty_agg) > 0 else 0.0

    by_perimeter = {}
    if "Périmètre TOTAL" in deals.columns:
        by_perimeter = deals.groupby("Périmètre TOTAL")["abs_amount"].sum().to_dict()
        by_perimeter = {k: float(v) for k, v in by_perimeter.items()}

    concentration = {
        "top_10": top_10,
        "hhi": round(hhi, 1),
        "by_perimeter": by_perimeter,
    }

    # ── Rating distribution ───────────────────────────────────────
    deals["_rating_bucket"] = deals["rating"].apply(_rating_to_bucket)
    rating_agg = deals.groupby("_rating_bucket")["abs_amount"].sum()
    rating_out = {}
    for bucket in RATING_BUCKETS:
        nom = float(rating_agg.get(bucket, 0.0))
        rating_out[bucket] = {
            "nominal": nom,
            "pct": round(nom / total_nominal * 100, 2) if total_nominal > 0 else 0.0,
        }

    # ── HQLA composition ─────────────────────────────────────────
    hqla_agg = deals.groupby("hqla_level")["abs_amount"].sum()
    hqla_out = {}
    total_hqla = 0.0
    for level in HQLA_LEVELS:
        nom = float(hqla_agg.get(level, 0.0))
        hqla_out[level] = {
            "nominal": nom,
            "pct": round(nom / total_nominal * 100, 2) if total_nominal > 0 else 0.0,
        }
        if level != "Non-HQLA":
            total_hqla += nom
    hqla_out["total_hqla"] = total_hqla

    # ── Country concentration ─────────────────────────────────────
    country_agg = deals.groupby("country")["abs_amount"].sum().sort_values(ascending=False)
    country_top_10 = []
    for country, nom in country_agg.head(10).items():
        country_top_10.append({
            "country": country,
            "nominal": float(nom),
            "pct": round(float(nom / total_nominal * 100), 2) if total_nominal > 0 else 0.0,
        })
    country_hhi = _compute_hhi(country_agg) if len(country_agg) > 0 else 0.0

    country_out = {
        "top_10": country_top_10,
        "hhi": round(country_hhi, 1),
    }

    # ── CDS overlay ───────────────────────────────────────────────
    cds_out = None
    if cds_spreads is not None:
        deals["_cds"] = deals["Counterparty"].map(cds_spreads)
        with_cds = deals.dropna(subset=["_cds"])
        if not with_cds.empty:
            total_nom_cds = with_cds["abs_amount"].sum()
            weighted_avg = float(
                (with_cds["_cds"] * with_cds["abs_amount"]).sum() / total_nom_cds
            ) if total_nom_cds > 0 else 0.0

            worst = (
                with_cds.groupby("Counterparty")
                .agg(spread_bps=("_cds", "first"), nominal=("abs_amount", "sum"))
                .sort_values("spread_bps", ascending=False)
                .head(5)
                .reset_index()
            )
            worst_5 = [
                {"counterparty": r["Counterparty"], "spread_bps": float(r["spread_bps"]), "nominal": float(r["nominal"])}
                for _, r in worst.iterrows()
            ]

            alerts = [
                {"counterparty": r["Counterparty"], "spread_bps": float(r["spread_bps"]), "nominal": float(r["nominal"])}
                for _, r in worst.iterrows()
                if r["spread_bps"] > CDS_ALERT_THRESHOLD_BPS
            ]

            cds_out = {
                "weighted_avg_bps": round(weighted_avg, 1),
                "worst_5": worst_5,
                "alerts": alerts,
            }
        else:
            cds_out = {
                "weighted_avg_bps": 0.0,
                "worst_5": [],
                "alerts": [],
            }

    return {
        "ref_date": ref_date.isoformat(),
        "concentration": concentration,
        "rating": rating_out,
        "hqla": hqla_out,
        "country": country_out,
        "cds": cds_out,
    }
