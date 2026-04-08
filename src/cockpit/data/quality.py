"""Data quality checks for the daily ALM pipeline.

Produces a DataQualityReport with:
- Deal/rate match rates
- Stale rate detection
- Orphan deals (no matching echeancier)
- Missing/null field coverage per column
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


@dataclass
class QualityCheck:
    """Single quality check result."""
    name: str
    status: str  # "pass", "warn", "fail"
    value: float | int | str
    detail: str = ""


@dataclass
class DataQualityReport:
    """Aggregated data quality report for the daily run."""
    date_run: datetime
    checks: list[QualityCheck] = field(default_factory=list)
    coverage: dict[str, float] = field(default_factory=dict)

    @property
    def n_pass(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def n_warn(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def n_fail(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def overall_status(self) -> str:
        if self.n_fail > 0:
            return "fail"
        if self.n_warn > 0:
            return "warn"
        return "pass"

    def to_dict(self) -> dict:
        return {
            "date_run": self.date_run.strftime("%Y-%m-%d"),
            "overall_status": self.overall_status,
            "n_pass": self.n_pass,
            "n_warn": self.n_warn,
            "n_fail": self.n_fail,
            "checks": [
                {"name": c.name, "status": c.status, "value": c.value, "detail": c.detail}
                for c in self.checks
            ],
            "coverage": self.coverage,
        }


def is_rate_stale(curve_date: datetime | str, ref_date: datetime, max_age_days: int = 3) -> bool:
    """Return True if *curve_date* is more than *max_age_days* before *ref_date*."""
    if isinstance(curve_date, str):
        try:
            curve_date = datetime.strptime(curve_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            return True  # unparseable → treat as stale
    if curve_date is None or pd.isna(curve_date):
        return True
    # Normalize timezone (curve_date may be tz-aware from parsers)
    if hasattr(curve_date, 'tzinfo') and curve_date.tzinfo is not None:
        curve_date = curve_date.replace(tzinfo=None)
    return (ref_date - curve_date) > timedelta(days=max_age_days)


def check_deal_rate_match(
    deals: Optional[pd.DataFrame],
    echeancier: Optional[pd.DataFrame],
) -> QualityCheck:
    """Check how many deals have a matching echeancier schedule."""
    if deals is None or deals.empty:
        return QualityCheck("Deal-Schedule Match", "warn", "N/A", "No deals provided")
    if echeancier is None or echeancier.empty:
        return QualityCheck("Deal-Schedule Match", "fail", 0.0, "No echeancier provided")

    deal_keys = set()
    for col_set in [("Dealid", "Direction", "Currency"), ("Dealid",)]:
        if all(c in deals.columns for c in col_set):
            deal_keys = set(deals[list(col_set)].drop_duplicates().itertuples(index=False, name=None))
            ech_keys = set(echeancier[list(col_set)].drop_duplicates().itertuples(index=False, name=None)) if all(c in echeancier.columns for c in col_set) else set()
            break
    else:
        return QualityCheck("Deal-Schedule Match", "warn", "N/A", "Missing key columns")

    if not deal_keys:
        return QualityCheck("Deal-Schedule Match", "warn", "N/A", "No deal keys found")

    matched = deal_keys & ech_keys
    rate = len(matched) / len(deal_keys) * 100

    status = "pass" if rate >= 95 else "warn" if rate >= 80 else "fail"
    return QualityCheck(
        "Deal-Schedule Match", status, round(rate, 1),
        f"{len(matched)}/{len(deal_keys)} deals matched ({rate:.1f}%)"
    )


def check_orphan_deals(
    deals: Optional[pd.DataFrame],
    echeancier: Optional[pd.DataFrame],
) -> QualityCheck:
    """Identify deals with no echeancier entry."""
    if deals is None or deals.empty or echeancier is None or echeancier.empty:
        return QualityCheck("Orphan Deals", "warn", "N/A", "Insufficient data")

    key_cols = ["Dealid"]
    if "Dealid" not in deals.columns:
        return QualityCheck("Orphan Deals", "warn", "N/A", "No Dealid column")

    deal_ids = set(deals["Dealid"].dropna().unique())
    ech_ids = set(echeancier["Dealid"].dropna().unique()) if "Dealid" in echeancier.columns else set()
    orphans = deal_ids - ech_ids
    n = len(orphans)

    status = "pass" if n == 0 else "warn" if n <= 5 else "fail"
    detail = f"{n} orphan deal(s)" + (f": {sorted(orphans)[:5]}" if 0 < n <= 5 else "")
    return QualityCheck("Orphan Deals", status, n, detail)


def check_field_coverage(deals: Optional[pd.DataFrame]) -> dict[str, float]:
    """Return per-column non-null coverage percentage for key fields."""
    if deals is None or deals.empty:
        return {}
    key_fields = [
        "Dealid", "Direction", "Currency", "Amount", "Product",
        "Maturitydate", "Clientrate", "FTP",
    ]
    coverage = {}
    for col in key_fields:
        if col in deals.columns:
            non_null = deals[col].notna().sum()
            coverage[col] = round(non_null / len(deals) * 100, 1)
    return coverage


def check_rate_staleness(
    ois_curves: Optional[pd.DataFrame],
    ref_date: datetime,
    max_age_days: int = 3,
) -> QualityCheck:
    """Check if OIS curves are stale relative to ref_date."""
    if ois_curves is None or ois_curves.empty:
        return QualityCheck("Rate Staleness", "warn", "N/A", "No OIS curves provided")

    date_col = None
    for candidate in ["date", "Date", "curve_date"]:
        if candidate in ois_curves.columns:
            date_col = candidate
            break

    if date_col is None:
        # Check index
        if hasattr(ois_curves.index, 'date') or ois_curves.index.dtype == "datetime64[ns]":
            latest = pd.Timestamp(ois_curves.index.max())
        else:
            return QualityCheck("Rate Staleness", "warn", "N/A", "Cannot determine curve date")
    else:
        latest = pd.to_datetime(ois_curves[date_col]).max()

    if pd.isna(latest):
        return QualityCheck("Rate Staleness", "fail", "N/A", "No valid curve dates")

    age_days = (ref_date - latest.to_pydatetime().replace(tzinfo=None)).days
    stale = age_days > max_age_days

    status = "fail" if stale else "pass"
    return QualityCheck(
        "Rate Staleness", status, age_days,
        f"Latest curve: {latest.strftime('%Y-%m-%d')} ({age_days}d old)"
    )


def check_rate_bounds(
    deals: Optional[pd.DataFrame],
    min_rate: float = -0.02,
    max_rate: float = 0.20,
) -> list[QualityCheck]:
    """Check that key rate columns are within plausible bounds.

    Flags deals where Clientrate or EqOisRate fall outside [min_rate, max_rate].
    """
    if deals is None or deals.empty:
        return [QualityCheck("Rate Bounds", "warn", "N/A", "No deals provided")]

    checks = []
    for col in ["Clientrate", "EqOisRate"]:
        if col not in deals.columns:
            continue
        rates = pd.to_numeric(deals[col], errors="coerce").dropna()
        if rates.empty:
            continue
        oob = rates[(rates < min_rate) | (rates > max_rate)]
        n = len(oob)
        status = "pass" if n == 0 else "warn" if n <= 3 else "fail"
        detail = f"{n} deal(s) with {col} outside [{min_rate:.2%}, {max_rate:.2%}]"
        if 0 < n <= 5:
            detail += f" — values: {oob.values.tolist()}"
        checks.append(QualityCheck(f"Rate Bounds ({col})", status, n, detail))

    return checks if checks else [QualityCheck("Rate Bounds", "pass", 0, "No rate columns found")]


def check_duplicate_deals(deals: Optional[pd.DataFrame]) -> QualityCheck:
    """Check for duplicate Dealid values."""
    if deals is None or deals.empty:
        return QualityCheck("Duplicate Deals", "warn", "N/A", "No deals provided")
    if "Dealid" not in deals.columns:
        return QualityCheck("Duplicate Deals", "warn", "N/A", "No Dealid column")

    dups = deals["Dealid"].dropna()
    dup_ids = dups[dups.duplicated(keep=False)].unique()
    n = len(dup_ids)
    n_dup_rows = len(dups[dups.duplicated(keep=False)])
    status = "pass" if n_dup_rows == 0 else "warn" if n_dup_rows <= 3 else "fail"
    detail = f"{n} duplicate Dealid(s)"
    if 0 < n <= 5:
        detail += f": {sorted(dup_ids)[:5]}"
    return QualityCheck("Duplicate Deals", status, n_dup_rows, detail)


def check_maturity_consistency(deals: Optional[pd.DataFrame]) -> QualityCheck:
    """Check that Maturitydate is after Valuedate for all deals."""
    if deals is None or deals.empty:
        return QualityCheck("Maturity Consistency", "warn", "N/A", "No deals provided")

    mat_col = "Maturitydate" if "Maturitydate" in deals.columns else None
    val_col = "Valuedate" if "Valuedate" in deals.columns else None

    if mat_col is None:
        return QualityCheck("Maturity Consistency", "warn", "N/A", "No Maturitydate column")
    if val_col is None:
        return QualityCheck("Maturity Consistency", "pass", 0, "No Valuedate column to compare")

    mat = pd.to_datetime(deals[mat_col], errors="coerce")
    val = pd.to_datetime(deals[val_col], errors="coerce")
    both_valid = mat.notna() & val.notna()
    bad = (mat[both_valid] < val[both_valid])
    n = int(bad.sum())

    status = "pass" if n == 0 else "warn" if n <= 2 else "fail"
    detail = f"{n} deal(s) where Maturitydate < Valuedate"
    if n > 0 and "Dealid" in deals.columns:
        bad_ids = deals.loc[bad[bad].index, "Dealid"].tolist()[:5]
        detail += f" — DealIds: {bad_ids}"
    return QualityCheck("Maturity Consistency", status, n, detail)


def check_sign_consistency(deals: Optional[pd.DataFrame]) -> QualityCheck:
    """Check that Amount sign is consistent with Direction.

    Convention: Deposits (D) should have positive Amount (bank receives funds).
    Loans (L) should have negative Amount (bank lends out).
    """
    if deals is None or deals.empty:
        return QualityCheck("Sign Consistency", "warn", "N/A", "No deals provided")
    if "Direction" not in deals.columns or "Amount" not in deals.columns:
        return QualityCheck("Sign Consistency", "warn", "N/A", "Missing Direction or Amount")

    amounts = pd.to_numeric(deals["Amount"], errors="coerce")
    directions = deals["Direction"]

    # Loans: Amount should be negative (or zero)
    loan_mask = directions == "L"
    loan_positive = loan_mask & (amounts > 0)

    # Deposits: Amount should be positive (or zero)
    dep_mask = directions == "D"
    dep_negative = dep_mask & (amounts < 0)

    n = int(loan_positive.sum() + dep_negative.sum())
    status = "pass" if n == 0 else "warn" if n <= 3 else "fail"
    detail = f"{n} deal(s) with Amount sign inconsistent with Direction"
    return QualityCheck("Sign Consistency", status, n, detail)


def build_quality_report(
    date_run: datetime,
    deals: Optional[pd.DataFrame] = None,
    echeancier: Optional[pd.DataFrame] = None,
    ois_curves: Optional[pd.DataFrame] = None,
) -> DataQualityReport:
    """Run all quality checks and return a consolidated report."""
    report = DataQualityReport(date_run=date_run)

    report.checks.append(check_deal_rate_match(deals, echeancier))
    report.checks.append(check_orphan_deals(deals, echeancier))
    report.checks.append(check_rate_staleness(ois_curves, date_run))
    report.checks.extend(check_rate_bounds(deals))
    report.checks.append(check_duplicate_deals(deals))
    report.checks.append(check_maturity_consistency(deals))
    report.checks.append(check_sign_consistency(deals))

    report.coverage = check_field_coverage(deals)

    # Coverage quality check
    if report.coverage:
        min_coverage = min(report.coverage.values())
        status = "pass" if min_coverage >= 95 else "warn" if min_coverage >= 80 else "fail"
        worst_col = min(report.coverage, key=report.coverage.get)
        report.checks.append(QualityCheck(
            "Field Coverage", status, round(min_coverage, 1),
            f"Worst: {worst_col} at {min_coverage:.1f}%"
        ))

    return report
