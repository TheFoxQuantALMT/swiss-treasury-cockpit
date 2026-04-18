"""P&L computation engine — daily core, monthly aggregation, strategy pivot."""
from __future__ import annotations

import logging
import re
from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.config import (
    CURRENCY_TO_OIS,
    FLOAT_NAME_TO_WASP,
    LOOKBACK_DAYS,
    MM_BY_CURRENCY,
    PRODUCT_RATE_COLUMN,
    SHOCKS,
    STRATEGY_LEG_BND,
    STRATEGY_LEG_IAM,
)

_TENOR_SUFFIX_RE = re.compile(r"(\d+)([MWY])$")
_TENOR_DAYS_PER_UNIT = {"W": 7, "M": 30, "Y": 365}


def _infer_fixing_tenor_days(short_name: str, last_fix, next_fix) -> int:
    """Infer fixing tenor for a floating deal.

    Precedence (any one match wins):
      1. (next_fixing_date - last_fixing_date).days when both populated
      2. Numeric suffix on short name: 'SARON3M' -> 90, 'EURIBOR6M' -> 180
      3. 0 (overnight / unknown)
    """
    if pd.notna(last_fix) and pd.notna(next_fix):
        try:
            delta = (pd.Timestamp(next_fix) - pd.Timestamp(last_fix)).days
            if delta > 0:
                return int(delta)
        except (TypeError, ValueError):
            pass
    m = _TENOR_SUFFIX_RE.search(str(short_name or "").strip().upper())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return n * _TENOR_DAYS_PER_UNIT[unit]
    return 0
from pnl_engine.curves import load_daily_curves, overlay_wirp, CurveCache
from pnl_engine.matrices import (
    build_accrual_days,
    build_date_grid,
    expand_nominal_to_daily,
    build_alive_mask,
    build_mm_vector,
    build_rate_matrix,
)
from pnl_engine.saron import apply_lookback_shift

logger = logging.getLogger(__name__)


def _month_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM' month columns."""
    return [c for c in df.columns if isinstance(c, str) and "/" in c and c[:4].isdigit()]


def compute_daily_pnl(
    nominal: np.ndarray,
    ois: np.ndarray,
    rate_ref: np.ndarray,
    mm: np.ndarray,
    accrual_days: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorized daily P&L: Nominal x (OIS - RateRef) x d_i / MM.

    Args:
        accrual_days: (n_days,) calendar days each fixing accrues for
            (e.g., 3 for Friday → Monday). If None, defaults to 1 (no
            weekend/holiday adjustment).
    """
    safe_mm = np.where(mm == 0, 360.0, mm)
    daily = nominal * (ois - rate_ref) / safe_mm
    if accrual_days is not None:
        daily = daily * accrual_days[np.newaxis, :]
    return daily


def _aggregate_slice(
    daily_pnl: np.ndarray,
    nominal_daily: np.ndarray,
    ois_daily: np.ndarray,
    rate_daily: np.ndarray,
    mask: np.ndarray,
    n_cal_days: int,
    funding_daily: np.ndarray | None,
    accrual_days: np.ndarray | None,
    mm_daily: np.ndarray | None,
    carry_funding_daily: np.ndarray | None = None,
    carry_factor_month: np.ndarray | None = None,
    rate_factor_month: np.ndarray | None = None,
) -> dict:
    """Aggregate daily arrays over a boolean day-mask into a single column of metrics.

    Returns dict of (n_deals,) arrays for all core + CoC metrics.

    Compounded metrics use cumulative factors from value date when
    carry_factor_month / rate_factor_month are provided. Otherwise falls back
    to per-month products from carry_funding_daily.
    """
    n_deals = daily_pnl.shape[0]
    n_mask_days = mask.sum()

    nom_days = nominal_daily[:, mask].sum(axis=1)
    nom_avg = nom_days / n_cal_days if n_cal_days > 0 else np.zeros(n_deals)

    ois_x_nom = (ois_daily[:, mask] * nominal_daily[:, mask]).sum(axis=1)
    rate_x_nom = (rate_daily[:, mask] * nominal_daily[:, mask]).sum(axis=1)
    safe_nom = np.where(nom_days == 0, np.nan, nom_days)

    out = {
        "Nominal": nom_avg,
        "nominal_days": nom_days,
        "OISfwd": ois_x_nom / safe_nom,
        "RateRef": rate_x_nom / safe_nom,
    }

    if funding_daily is not None and n_mask_days > 0:
        d_i = accrual_days[mask] if accrual_days is not None else np.ones(n_mask_days)
        mm_slice = mm_daily[:, mask] if mm_daily is not None else np.ones((n_deals, n_mask_days))
        rate_slice = rate_daily[:, mask]
        funding_slice = funding_daily[:, mask]
        nom_slice = nominal_daily[:, mask]

        gross = (nom_slice * rate_slice * d_i[np.newaxis, :] / mm_slice).sum(axis=1)
        fund = (nom_slice * funding_slice * d_i[np.newaxis, :] / mm_slice).sum(axis=1)
        out["GrossCarry"] = gross

        # Simple: linear funding − rate, follows funding_source config (OIS or carry)
        out["FundingCost_Simple"] = fund
        out["PnL_Simple"] = fund - gross
        fund_x_nom = (funding_slice * nom_slice).sum(axis=1)
        out["FundingRate_Simple"] = fund_x_nom / safe_nom

        # Compounded: value-date cumulative factors (preferred) or per-month fallback
        if carry_factor_month is not None and rate_factor_month is not None:
            total_d = d_i.sum()
            safe_total_d = total_d if total_d > 0 else 1.0
            out["FundingCost_Compounded"] = nom_avg * (carry_factor_month - 1.0)
            out["PnL_Compounded"] = nom_avg * (carry_factor_month - rate_factor_month)
            out["FundingRate_Compounded"] = (carry_factor_month - 1.0) * mm_slice[:, 0] / safe_total_d
        elif carry_funding_daily is not None:
            carry_slice = carry_funding_daily[:, mask]
            rate_factors = 1.0 + rate_slice * d_i[np.newaxis, :] / mm_slice
            carry_factors = 1.0 + carry_slice * d_i[np.newaxis, :] / mm_slice
            total_d = d_i.sum()
            safe_total_d = total_d if total_d > 0 else 1.0
            out["FundingCost_Compounded"] = (nom_slice * carry_slice * d_i[np.newaxis, :] / mm_slice).sum(axis=1)
            out["PnL_Compounded"] = nom_avg * (np.prod(carry_factors, axis=1) - np.prod(rate_factors, axis=1))
            out["FundingRate_Compounded"] = (np.prod(carry_factors, axis=1) - 1.0) * mm_slice[:, 0] / safe_total_d
    elif funding_daily is not None:
        zeros = np.zeros(n_deals)
        for k in ("GrossCarry", "FundingCost_Simple", "PnL_Simple", "FundingRate_Simple"):
            out[k] = zeros
    else:
        # No funding context — derive PnL_Simple from precomputed daily P&L
        out["PnL_Simple"] = daily_pnl[:, mask].sum(axis=1)

    has_compounded = "FundingCost_Compounded" in out
    if not has_compounded and (carry_funding_daily is not None or carry_factor_month is not None):
        zeros = np.zeros(n_deals)
        for k in ("FundingCost_Compounded", "PnL_Compounded", "FundingRate_Compounded"):
            out[k] = zeros

    return out


def aggregate_to_monthly(
    daily_pnl: np.ndarray,
    nominal_daily: np.ndarray,
    ois_daily: np.ndarray,
    rate_daily: np.ndarray,
    days: pd.DatetimeIndex,
    funding_daily: np.ndarray | None = None,
    accrual_days: np.ndarray | None = None,
    mm_daily: np.ndarray | None = None,
    date_rates: "pd.Timestamp | None" = None,
    carry_funding_daily: np.ndarray | None = None,
    cum_carry_factors: np.ndarray | None = None,
    cum_rate_factors: np.ndarray | None = None,
) -> pd.DataFrame:
    """Aggregate daily arrays to monthly per deal.

    Core columns (always computed):
        PnL: sum of daily values.
        Nominal: average daily nominal over calendar days in the month.
        OISfwd: nominal-weighted average.
        RateRef: nominal-weighted average.
        nominal_days: sum of daily nominals (for rate weighting).

    Simple columns — OIS forward, linear (WASP dailyFwdRate, MESA AGG):
        GrossCarry: Σ(Nominal × RateRef × d_i / D) per IFRS 9.B5.4.5.
        FundingCost_Simple: Σ(Nominal × OISfwd × d_i / D).
        PnL_Simple: FundingCost_Simple − GrossCarry (= −CoC).
        FundingRate_Simple: Σ(OISfwd × Nom) / Σ(Nom).

    Compounded columns — WASP carry, geometric from deal value date:
        FundingCost_Compounded: NomAvg × (carry_factor_month − 1).
        PnL_Compounded: NomAvg × (carry_factor_month − rate_factor_month).
        FundingRate_Compounded: effective annualized rate from carry factor.
        Where monthly factors = ratio of consecutive cumulative factors from VD.

    Realized / Forecast split (when ``date_rates`` is provided):
        Adds a PnL_Type column: past months -> Realized, future months -> Forecast,
        current month (containing date_rates) -> Total + Realized + Forecast rows.
        When date_rates is None, PnL_Type = "Total" for all rows.
    """
    month_idx = days.to_period("M")
    unique_months = month_idx.unique()
    n_deals = daily_pnl.shape[0]

    rates_month = date_rates.to_period("M") if date_rates is not None else None

    common_kw = dict(
        daily_pnl=daily_pnl, nominal_daily=nominal_daily,
        ois_daily=ois_daily, rate_daily=rate_daily,
        funding_daily=funding_daily, accrual_days=accrual_days, mm_daily=mm_daily,
        carry_funding_daily=carry_funding_daily,
    )

    # --- Build boundary-to-month mapping for cumulative factors ---
    # cum_carry_factors / cum_rate_factors have columns:
    #   [0: start=1.0, 1: boundary_0, 2: boundary_1, ...]
    # Boundaries may include an extra date_rates point.
    # We need to map each unique month j to the right boundary columns.
    use_cum = cum_carry_factors is not None and cum_rate_factors is not None
    boundary_map = {}  # month_idx j -> (col_start, col_end)
    dr_boundary_col = None  # column index for the date_rates boundary (if inserted)
    if use_cum:
        # Reconstruct boundary dates (same logic as matrices.py)
        months_sorted = unique_months.sort_values()
        boundary_dates = [m_.end_time for m_ in months_sorted]
        if date_rates is not None:
            dr_ts = pd.Timestamp(date_rates)
            for k, bd in enumerate(boundary_dates):
                if dr_ts <= bd:
                    if dr_ts.date() != bd.date():
                        boundary_dates.insert(k, dr_ts)
                        dr_boundary_col = k + 1  # +1 because col 0 is "start"
                    break
        # Map month j -> boundary columns
        bd_idx = 0
        for j, m_ in enumerate(months_sorted):
            col_start = bd_idx  # column in cum array (0-based, shifted by +1 in array)
            # Skip any boundaries that are before this month's end (e.g. date_rates)
            while bd_idx < len(boundary_dates) and boundary_dates[bd_idx] <= m_.end_time:
                bd_idx += 1
            col_end = bd_idx  # column after this month's last boundary
            boundary_map[j] = (col_start, col_end)

    rows: list[dict] = []

    for j, m in enumerate(unique_months):
        month_mask = np.asarray(month_idx == m)
        n_cal_days = int(month_mask.sum())

        # Compute monthly carry/rate factors from cumulative arrays
        carry_factor_total = None
        rate_factor_total = None
        if use_cum and j in boundary_map:
            col_start, col_end = boundary_map[j]
            # Total month factor = cum[col_end] / cum[col_start]
            carry_factor_total = cum_carry_factors[:, col_end] / np.maximum(cum_carry_factors[:, col_start], 1e-15)
            rate_factor_total = cum_rate_factors[:, col_end] / np.maximum(cum_rate_factors[:, col_start], 1e-15)

        agg_total = _aggregate_slice(
            mask=month_mask, n_cal_days=n_cal_days,
            carry_factor_month=carry_factor_total,
            rate_factor_month=rate_factor_total,
            **common_kw,
        )

        if date_rates is None:
            for deal_i in range(n_deals):
                row = {"deal_idx": deal_i, "Month": m, "PnL_Type": "Total"}
                for k, arr in agg_total.items():
                    row[k] = arr[deal_i]
                rows.append(row)
        elif m == rates_month:
            # Current month: produce Total + Realized + Forecast
            realized_within = np.zeros(len(days), dtype=bool)
            realized_within[month_mask] = days[month_mask] <= date_rates
            forecast_within = np.zeros(len(days), dtype=bool)
            forecast_within[month_mask] = days[month_mask] > date_rates

            n_realized_days = int(realized_within.sum())
            n_forecast_days = int(forecast_within.sum())

            # Compute realized/forecast factors using date_rates boundary
            carry_factor_real = None
            rate_factor_real = None
            carry_factor_fore = None
            rate_factor_fore = None
            if use_cum and j in boundary_map and dr_boundary_col is not None:
                col_start, col_end = boundary_map[j]
                # Realized: col_start → dr_boundary_col
                carry_factor_real = cum_carry_factors[:, dr_boundary_col] / np.maximum(cum_carry_factors[:, col_start], 1e-15)
                rate_factor_real = cum_rate_factors[:, dr_boundary_col] / np.maximum(cum_rate_factors[:, col_start], 1e-15)
                # Forecast: dr_boundary_col → col_end
                carry_factor_fore = cum_carry_factors[:, col_end] / np.maximum(cum_carry_factors[:, dr_boundary_col], 1e-15)
                rate_factor_fore = cum_rate_factors[:, col_end] / np.maximum(cum_rate_factors[:, dr_boundary_col], 1e-15)

            agg_real = _aggregate_slice(
                mask=realized_within, n_cal_days=n_realized_days,
                carry_factor_month=carry_factor_real, rate_factor_month=rate_factor_real,
                **common_kw,
            )
            agg_fore = _aggregate_slice(
                mask=forecast_within, n_cal_days=n_forecast_days,
                carry_factor_month=carry_factor_fore, rate_factor_month=rate_factor_fore,
                **common_kw,
            )

            for deal_i in range(n_deals):
                for pnl_type, agg in [("Total", agg_total), ("Realized", agg_real), ("Forecast", agg_fore)]:
                    row = {"deal_idx": deal_i, "Month": m, "PnL_Type": pnl_type}
                    for k, arr in agg.items():
                        row[k] = arr[deal_i]
                    rows.append(row)
        elif m < rates_month:
            for deal_i in range(n_deals):
                row = {"deal_idx": deal_i, "Month": m, "PnL_Type": "Realized"}
                for k, arr in agg_total.items():
                    row[k] = arr[deal_i]
                rows.append(row)
        else:
            # Future month: all forecast
            for deal_i in range(n_deals):
                row = {"deal_idx": deal_i, "Month": m, "PnL_Type": "Forecast"}
                for k, arr in agg_total.items():
                    row[k] = arr[deal_i]
                rows.append(row)

    return pd.DataFrame(rows)


def weighted_average(
    df: pd.DataFrame,
    data_cols: list[str],
    weight_col: str,
    by_col: str | list[str],
) -> pd.DataFrame:
    """Nominal-weighted average, grouped. Null -> zero weight. Zero denom -> NaN."""
    weight = df[weight_col]
    # Build grouper: list of Series for multi-column groupby
    if isinstance(by_col, str):
        grouper = df[by_col]
    else:
        grouper = [df[c] for c in by_col]
    pieces: dict[str, pd.Series] = {}
    for col in data_cols:
        not_null = pd.notnull(df[col])
        numer = (df[col] * weight).groupby(grouper).sum()
        denom = (weight * not_null).groupby(grouper).sum().replace(0, np.nan)
        pieces[col] = numer / denom
    return pd.DataFrame(pieces)


# ---------------------------------------------------------------------------
# Strategy pivot (Families 3-6: IAS hedge decomposition)
# ---------------------------------------------------------------------------

def _safe(df: pd.DataFrame, col: str) -> pd.Series:
    """Return *col* from *df* if it exists, else a zero Series."""
    if col in df.columns:
        return df[col].fillna(0.0)
    return pd.Series(0.0, index=df.index)


def compute_strategy_pnl(monthly: pd.DataFrame) -> pd.DataFrame:
    """IAS hedge strategy decomposition into 4 synthetic legs.

    Aligned with pnl_calculation_methodology.md §10:
    1. Pre-aggregate by (Perimetre, Strategy, Currency, Product, Direction, Month, DIM)
       with nominal-weighted average rates (§10.1)
    2. Pivot by Product (§10.2)
    3. Compute spreads and marginRate (§10.3)
    4. Build 4 conditional legs with cond_col != 0 guard (§10.4)
    5. Compute P&L per leg (§10.5)
    """
    strat = monthly[monthly["Strategy IAS"].notnull()].copy()
    if strat.empty:
        return pd.DataFrame()

    # Direction map from non-HCD deals (§10.7)
    direction_map = (
        strat.loc[strat["Product"] != "HCD", ["Strategy IAS", "Direction"]]
        .drop_duplicates()
    )

    # -- Step 1: Pre-aggregate with nominal-weighted avg rates (§10.1) --
    group_cols = ["Périmètre TOTAL", "Strategy IAS", "Currency", "Product",
                  "Direction", "Month", "Days in Month", "PnL_Type"]
    present_group = [c for c in group_cols if c in strat.columns]

    # Sums
    has_compounded = "PnL_Compounded" in strat.columns
    agg_spec = {
        "Amount": ("Amount", "sum") if "Amount" in strat.columns else ("Nominal", "sum"),
        "Nominal": ("Nominal", "sum"),
        "PnL_Simple": ("PnL_Simple", "sum"),
    }
    if has_compounded:
        agg_spec["PnL_Compounded"] = ("PnL_Compounded", "sum")
    agg = strat.groupby(present_group).agg(**agg_spec).reset_index()

    # Nominal-weighted average rates
    rate_cols = ["RateRef", "Clientrate", "EqOisRate", "CocRate", "OISfwd", "YTM"]
    present_rates = [c for c in rate_cols if c in strat.columns]
    if present_rates:
        wavg = weighted_average(strat, present_rates, "Nominal", present_group)
        for col in present_rates:
            if col in wavg.columns:
                agg = agg.merge(wavg[[col]].reset_index(), on=present_group, how="left", suffixes=("_drop", ""))
                if f"{col}_drop" in agg.columns:
                    agg = agg.drop(columns=f"{col}_drop")

    # -- Step 2: Pivot by Product (§10.2) --
    idx_cols = ["Périmètre TOTAL", "Strategy IAS", "Currency", "Month", "Days in Month", "PnL_Type"]
    idx_cols = [c for c in idx_cols if c in agg.columns]
    pivot_vals = ["Amount", "Nominal", "Clientrate", "EqOisRate", "CocRate", "OISfwd", "YTM", "PnL_Simple", "PnL_Compounded"]
    present_vals = [v for v in pivot_vals if v in agg.columns]

    pivoted = pd.pivot_table(
        agg, values=present_vals, index=idx_cols, columns=["Product"],
        aggfunc="sum", fill_value=0,
    ).reset_index()

    # Flatten MultiIndex columns
    n_idx = len(idx_cols)
    flat_cols = [c[0] if isinstance(c, tuple) else c for c in pivoted.columns[:n_idx]]
    flat_cols += ["_".join(str(x) for x in c) for c in pivoted.columns[n_idx:]]
    pivoted.columns = flat_cols

    # -- Step 3: Spread combinations (§10.3) --
    pivoted["Nominal_Spread"] = _safe(pivoted, "Nominal_IAM/LD") + _safe(pivoted, "Nominal_BND") + _safe(pivoted, "Nominal_HCD")
    pivoted["Amount_Spread"] = _safe(pivoted, "Amount_IAM/LD") + _safe(pivoted, "Amount_BND") - _safe(pivoted, "Amount_HCD")
    pivoted["marginRate_Spread"] = _safe(pivoted, "EqOisRate_IAM/LD") + _safe(pivoted, "YTM_BND") - _safe(pivoted, "Clientrate_HCD")

    mm_by_ccy = np.array([MM_BY_CURRENCY.get(c, 360) for c in pivoted["Currency"]], dtype=float)
    dim = pivoted["Days in Month"].values.astype(float)

    # -- Step 4 & 5: Build conditional legs (§10.4, §10.5) --
    # Product-specific day count divisors (ISDA 2006 §4.16).
    # Avoids using per-currency default for products with different conventions
    # (e.g. GBP bonds use 30/360 = 360, not currency default 365).
    from pnl_engine.models import get_day_count as _get_dc
    _ccy_list = pivoted["Currency"].values

    def _product_mm(product: str) -> np.ndarray:
        return np.array([_get_dc(product, c).divisor for c in _ccy_list], dtype=float)

    mm_iam = _product_mm("IAM/LD")
    mm_bnd = _product_mm("BND")
    mm_hcd = _product_mm("HCD")

    def _build_leg(cond_col, leg_name, rate_src, nom_src, ois_src):
        """Build one leg: set to 0 where cond_col is 0."""
        mask = _safe(pivoted, cond_col).values != 0
        nom = np.where(mask, _safe(pivoted, nom_src).values, 0.0)
        rate = np.where(mask, rate_src.values if hasattr(rate_src, 'values') else _safe(pivoted, rate_src).values, 0.0)
        ois = np.where(mask, _safe(pivoted, ois_src).values, 0.0)
        return nom, rate, ois, mask

    def _build_pnl(nom, rate, ois, mask, subtract_rate, mm=mm_by_ccy):
        if subtract_rate:
            return np.where(mask, nom * (ois - rate) * dim / mm, 0.0)
        else:
            return np.where(mask, nom * rate * dim / mm, 0.0)

    base_cols = ["Périmètre TOTAL", "Strategy IAS", "Currency", "Month", "PnL_Type"]
    base_cols = [c for c in base_cols if c in pivoted.columns]
    base = pivoted[base_cols]

    legs = []

    # IAM/LD-NHCD: condition = Nominal_IAM/LD != 0
    nom, rate, ois, mask = _build_leg("Nominal_IAM/LD", "IAM/LD-NHCD", _safe(pivoted, "EqOisRate_IAM/LD"), "Nominal_Spread", "OISfwd_IAM/LD")
    pnl = _build_pnl(nom, rate, ois, mask, subtract_rate=True, mm=mm_iam)
    leg = base.copy()
    leg["Product2BuyBack"] = "IAM/LD-NHCD"
    leg["PnL_Simple"] = pnl
    leg["Nominal"] = nom
    leg["RateRef"] = rate
    leg["OISfwd"] = ois
    leg["Amount"] = np.where(mask, _safe(pivoted, "Amount_Spread").values, 0.0)
    legs.append(leg)

    # IAM/LD-HCD: condition = Nominal_IAM/LD != 0 (same condition — depends on IAM/LD existing)
    nom_hcd = np.where(mask, _safe(pivoted, "Nominal_HCD").values, 0.0)
    rate_margin = np.where(mask, pivoted["marginRate_Spread"].values, 0.0)
    ois_hcd = np.where(mask, _safe(pivoted, "OISfwd_HCD").values, 0.0)
    pnl_hcd = _build_pnl(nom_hcd, rate_margin, ois_hcd, mask, subtract_rate=False, mm=mm_hcd)
    leg = base.copy()
    leg["Product2BuyBack"] = "IAM/LD-HCD"
    leg["PnL_Simple"] = pnl_hcd
    leg["Nominal"] = nom_hcd
    leg["RateRef"] = rate_margin
    leg["OISfwd"] = ois_hcd
    leg["Amount"] = np.where(mask, _safe(pivoted, "Amount_HCD").values, 0.0)
    legs.append(leg)

    # BND-NHCD: condition = Nominal_BND != 0
    nom_b, rate_b, ois_b, mask_b = _build_leg("Nominal_BND", "BND-NHCD", _safe(pivoted, "YTM_BND"), "Nominal_Spread", "OISfwd_BND")
    pnl_b = _build_pnl(nom_b, rate_b, ois_b, mask_b, subtract_rate=True, mm=mm_bnd)
    leg = base.copy()
    leg["Product2BuyBack"] = "BND-NHCD"
    leg["PnL_Simple"] = pnl_b
    leg["Nominal"] = nom_b
    leg["RateRef"] = rate_b
    leg["OISfwd"] = ois_b
    leg["Amount"] = np.where(mask_b, _safe(pivoted, "Amount_Spread").values, 0.0)
    legs.append(leg)

    # BND-HCD: condition = Nominal_BND != 0 (same condition — depends on BND existing)
    nom_bhcd = np.where(mask_b, _safe(pivoted, "Nominal_HCD").values, 0.0)
    rate_bmargin = np.where(mask_b, pivoted["marginRate_Spread"].values, 0.0)
    ois_bhcd = np.where(mask_b, _safe(pivoted, "OISfwd_HCD").values, 0.0)
    pnl_bhcd = _build_pnl(nom_bhcd, rate_bmargin, ois_bhcd, mask_b, subtract_rate=False, mm=mm_hcd)
    leg = base.copy()
    leg["Product2BuyBack"] = "BND-HCD"
    leg["PnL_Simple"] = pnl_bhcd
    leg["Nominal"] = nom_bhcd
    leg["RateRef"] = rate_bmargin
    leg["OISfwd"] = ois_bhcd
    leg["Amount"] = np.where(mask_b, _safe(pivoted, "Amount_HCD").values, 0.0)
    legs.append(leg)

    combined = pd.concat(legs, ignore_index=True)

    # Remove rows where condition was false (all values = 0)
    combined = combined[combined["Nominal"] != 0].copy()

    # --- Proportional allocation of PnL_Compounded to legs ---
    if has_compounded:
        # Total compounded P&L from pivoted product-level data
        pivoted["_PnL_Compounded_total"] = (
            _safe(pivoted, "PnL_Compounded_IAM/LD")
            + _safe(pivoted, "PnL_Compounded_BND")
            + _safe(pivoted, "PnL_Compounded_HCD")
        )
        comp_map = pivoted[base_cols + ["_PnL_Compounded_total"]]
        combined = combined.merge(comp_map, on=base_cols, how="left")

        # Per-group total Simple for proportional weights
        simple_total = combined.groupby(base_cols)["PnL_Simple"].transform("sum")
        combined["PnL_Compounded"] = np.where(
            simple_total != 0,
            combined["PnL_Simple"] / simple_total * combined["_PnL_Compounded_total"],
            0.0,
        )
        combined = combined.drop(columns=["_PnL_Compounded_total"])

    # Merge direction from non-HCD deals (§10.7)
    combined = pd.merge(direction_map, combined, how="right", on=["Strategy IAS"])

    # Rename Currency to Deal currency for output compatibility
    combined["Deal currency"] = combined["Currency"]

    return combined


def compute_book2_mtm(
    irs_stock: pd.DataFrame,
    calc_date: str,
    shock: Optional[str] = None,
) -> pd.DataFrame:
    """BOOK2 IRS MTM via waspTools.stockSwapMTM.

    Returns a DataFrame with MTM values per deal.
    """
    from pnl_engine.curves import wt, _require_wasp
    _require_wasp()

    if irs_stock.empty:
        return pd.DataFrame(columns=["Deal", "Currency", "MTM"])

    shock_bps = 0
    if shock and shock not in ("0", "wirp"):
        try:
            shock_bps = int(shock)
        except (ValueError, TypeError):
            pass

    return wt.stockSwapMTM(calc_date, irs_stock, Shock=shock_bps)


def filter_strategy_legs(strategy: pd.DataFrame) -> pd.DataFrame:
    """Apply §10.8 direction filters to IAS strategy legs.

    BND-HCD / BND-NHCD legs are bond-like: drop rows where Direction is L or D.
    IAM/LD-HCD / IAM/LD-NHCD legs are deposit/loan-like: drop Direction B or S.

    Assumes ``strategy`` is a non-empty DataFrame with Product2BuyBack and
    Direction columns. Returns the filtered copy; the input is not mutated.
    """
    bnd_mask = strategy["Product2BuyBack"].isin(STRATEGY_LEG_BND)
    iam_mask = strategy["Product2BuyBack"].isin(STRATEGY_LEG_IAM)
    exclude_bnd = bnd_mask & strategy["Direction"].isin(["L", "D"])
    exclude_iam = iam_mask & strategy["Direction"].isin(["B", "S"])
    exclude = exclude_bnd | exclude_iam
    if not exclude.any():
        return strategy
    return strategy[~exclude]


def merge_results(
    non_strategy: pd.DataFrame,
    strategy: pd.DataFrame,
    book2: pd.DataFrame,
) -> pd.DataFrame:
    """Concatenate non-strategy, strategy, and book2 results with direction filtering."""
    parts = []

    if non_strategy is not None and not non_strategy.empty:
        parts.append(non_strategy)

    if strategy is not None and not strategy.empty:
        parts.append(filter_strategy_legs(strategy))

    if book2 is not None and not book2.empty:
        parts.append(book2)

    if not parts:
        return pd.DataFrame()

    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Top-level orchestrator helpers
# ---------------------------------------------------------------------------

def _resolve_rate_ref(deals: pd.DataFrame) -> pd.DataFrame:
    """Add ``RateRef``, ``is_floating``, and ``ref_index`` columns based on product type.

    ``ref_index`` maps the MTD ``Floating Rates Short Name`` to the WASP index
    name used by ``build_rate_matrix`` for floating-rate forward curve lookup.
    """
    df = deals.copy()
    df["RateRef"] = 0.0
    for product, col in PRODUCT_RATE_COLUMN.items():
        mask = df["Product"] == product
        if mask.any() and col in df.columns:
            df.loc[mask, "RateRef"] = df.loc[mask, col].fillna(0.0)

    # MTM perimeter fallback: if product not in map and Perimetre = "MTM" -> Clientrate
    if "Périmètre TOTAL" in df.columns and "Clientrate" in df.columns:
        mtm_fallback = (df["RateRef"] == 0.0) & (df["Périmètre TOTAL"] == "MTM")
        if mtm_fallback.any():
            df.loc[mtm_fallback, "RateRef"] = df.loc[mtm_fallback, "Clientrate"].fillna(0.0)

    float_col = "Floating Rates Short Name"
    if float_col in df.columns:
        df["is_floating"] = df[float_col].fillna("").astype(str).str.strip().ne("")
    else:
        df["is_floating"] = False

    # Map floating rate short name -> WASP index for forward curve loading.
    df["ref_index"] = ""
    if float_col in df.columns:
        df["ref_index"] = (
            df[float_col].fillna("").astype(str).str.strip().map(FLOAT_NAME_TO_WASP).fillna("")
        )

    # Fixing tenor in calendar days: 0 for overnight RFRs, >0 for term floaters
    # (e.g. SARON3M, ESTR6M). Drives the held-constant branch in build_rate_matrix.
    df["fixing_tenor_days"] = 0
    if df["is_floating"].any():
        last_col = "last_fixing_date" if "last_fixing_date" in df.columns else None
        next_col = "next_fixing_date" if "next_fixing_date" in df.columns else None
        sn_col = float_col if float_col in df.columns else None
        for idx in df.index[df["is_floating"]]:
            sn = df.at[idx, sn_col] if sn_col else ""
            lf = df.at[idx, last_col] if last_col else pd.NaT
            nf = df.at[idx, next_col] if next_col else pd.NaT
            df.at[idx, "fixing_tenor_days"] = _infer_fixing_tenor_days(sn, lf, nf)

    # Drop only true overnight RFR legs (tenor==0) whose ref_index equals the
    # currency's OIS base — for these, OIS - RefRate ≡ 0 and the Echeancier V-leg
    # was already dropped. Term floaters (tenor>0) must survive: their rate is
    # held constant between fixings and produces non-zero P&L vs OIS.
    _OIS_INDICES = set(CURRENCY_TO_OIS.values())
    is_rfr_float = (
        df["is_floating"]
        & (df["fixing_tenor_days"] == 0)
        & df["ref_index"].isin(_OIS_INDICES)
    )
    if is_rfr_float.any():
        logger.info("Dropping %d overnight RFR floating legs (OIS - RefRate = 0)", is_rfr_float.sum())
        df = df[~is_rfr_float].copy()

    return df


def _build_ois_matrix(
    deals: pd.DataFrame,
    ois_curves: pd.DataFrame,
    days: pd.DatetimeIndex,
) -> np.ndarray:
    """Map each deal to its currency's OIS daily curve -> (n_deals x n_days)."""
    n_deals = len(deals)
    n_days = len(days)
    result = np.zeros((n_deals, n_days), dtype=np.float64)

    for ccy, ois_indice in CURRENCY_TO_OIS.items():
        deal_mask = (deals["Currency"] == ccy).values
        if not deal_mask.any():
            continue
        sub = ois_curves[ois_curves["Indice"] == ois_indice].copy()
        if sub.empty:
            continue
        sub = sub.set_index("Date")["value"]
        sub = sub[~sub.index.duplicated(keep="first")]
        aligned = sub.reindex(days, method="ffill").bfill().fillna(0.0).values

        # Apply SARON/SONIA lookback shift for currencies with observation delay
        lookback = LOOKBACK_DAYS.get(ccy, 0)
        if lookback > 0:
            aligned = apply_lookback_shift(aligned, lookback_days=lookback)

        result[deal_mask] = aligned[np.newaxis, :]

    return result


def _mock_curves_from_wirp(
    wirp: pd.DataFrame,
    days: pd.DatetimeIndex,
    shock: str = "0",
) -> pd.DataFrame:
    """Build mock daily OIS curves from WIRP meeting schedule.

    For each OIS indice found in WIRP, creates a daily series by forward-filling
    meeting rates across the date grid. Applies parallel shock shift (bps -> decimal).
    """
    rows = []
    for indice in wirp["Indice"].unique():
        sub = wirp[wirp["Indice"] == indice].sort_values("Meeting")
        meetings = sub["Meeting"].values.astype("datetime64[D]")
        rates = sub["Rate"].values.astype(float)

        # Use searchsorted: for each day, find the latest meeting <= that day
        day_arr = days.values.astype("datetime64[D]")
        idx = np.searchsorted(meetings, day_arr, side="right") - 1

        for j, d in enumerate(days):
            if idx[j] >= 0:
                val = rates[idx[j]]
            else:
                # Before first meeting — use first rate as backfill
                val = rates[0] if len(rates) > 0 else 0.0
            rows.append({"Date": d, "Indice": indice, "value": val})

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"])
    df["dateM"] = df["Date"].dt.to_period("M")

    # Apply parallel shock shift (bps -> decimal), aligned with pnl.py mock path
    shock_f = 0.0 if shock == "wirp" else float(shock)
    if shock_f != 0.0:
        df["value"] = df["value"] + shock_f / 10_000.0

    return df


def run_all_shocks(
    deals: pd.DataFrame,
    echeancier: pd.DataFrame,
    wirp: pd.DataFrame,
    irs_stock: pd.DataFrame,
    cache: CurveCache,
    date_rates: Optional[object] = None,
    shocks: Optional[list[str]] = None,
) -> pd.DataFrame:
    """Top-level orchestrator: run full shock pipeline and return concatenated results.

    Parameters
    ----------
    deals : parsed MTD deals
    echeancier : parsed Echeancier (wide nominal schedule)
    wirp : parsed WIRP (rate expectations)
    irs_stock : parsed IRS stock (for BOOK2 — not used in shock loop)
    cache : CurveCache instance
    date_rates : optional WASP date (unused when WASP unavailable)
    shocks : list of shock labels; defaults to SHOCKS config
    """
    if shocks is None:
        shocks = SHOCKS

    # 1. Resolve deal RateRef
    deals = _resolve_rate_ref(deals)

    # 2. Build date grid (60 months from today-ish — use first month of echeancier)
    month_cols = _month_columns(echeancier)
    if month_cols:
        first_month = month_cols[0]  # e.g. "2026/03"
        start = pd.Timestamp(first_month.replace("/", "-") + "-01")
    else:
        start = pd.Timestamp("2026-03-01")
    days = build_date_grid(start, months=60)

    # 3. Join deals to echeancier by (Dealid, Direction, Currency) per spec S4.3.
    deals["Dealid"] = pd.to_numeric(deals["Dealid"], errors="coerce")
    ech_keyed = echeancier.copy()
    ech_keyed["Dealid"] = pd.to_numeric(ech_keyed["Dealid"], errors="coerce")

    join_keys = ["Dealid", "Direction", "Currency"]
    present_keys = [k for k in join_keys if k in ech_keyed.columns]
    ech_agg = ech_keyed.groupby(present_keys)[month_cols].sum().reset_index()

    merged = deals.merge(
        ech_agg,
        on=present_keys,
        how="left",
        suffixes=("", "_ech"),
    )
    for mc in month_cols:
        if mc in merged.columns:
            merged[mc] = merged[mc].fillna(0.0)

    deals_use = merged.reset_index(drop=True)

    nominal_daily = expand_nominal_to_daily(deals_use[month_cols], days)
    alive = build_alive_mask(deals_use, days, date_run=start)
    nominal_daily = nominal_daily * alive

    # Apply CPR prepayment to fixed-rate mortgages (reduces nominal schedule)
    try:
        from pnl_engine.prepayment import apply_cpr
        nominal_daily, _cpr_log = apply_cpr(deals_use, nominal_daily, days)
    except Exception as exc:
        logger.debug("CPR prepayment skipped: %s", exc)

    mm = build_mm_vector(deals_use)
    accrual_days = build_accrual_days(days)

    # OIS indices needed
    ois_indices = list({CURRENCY_TO_OIS[c] for c in deals_use["Currency"].unique() if c in CURRENCY_TO_OIS})

    # Floating ref indices needed (from ref_index column populated by _resolve_rate_ref)
    float_wasp_indices = list(
        deals_use.loc[deals_use["is_floating"], "ref_index"]
        .replace("", np.nan).dropna().unique()
    )
    # Exclude OIS indices from float loading (they're already in Set 1)
    float_wasp_indices = [i for i in float_wasp_indices if i not in set(CURRENCY_TO_OIS.values())]

    all_results = []

    for shock in shocks:
        # 4a. Load OIS curves (from cache or WASP or WIRP mock)
        cache_key = ("ois", shock, tuple(sorted(ois_indices)))
        ois_curves = cache.get(cache_key)
        if ois_curves is None:
            try:
                ois_curves = load_daily_curves(
                    date=date_rates,
                    indices=ois_indices,
                    shock=shock,
                )
            except RuntimeError:
                logger.info("WASP unavailable, building mock curves from WIRP (shock=%s)", shock)
                ois_curves = _mock_curves_from_wirp(wirp, days, shock=shock)
            cache.put(cache_key, ois_curves)

        # 4b. Apply WIRP overlay if shock == "wirp"
        if shock == "wirp":
            ois_curves = overlay_wirp(ois_curves, wirp)

        # 4c. Build OIS matrix
        ois_matrix = _build_ois_matrix(deals_use, ois_curves, days)

        # 4d. Load ref rate curves for floating legs (non-OIS indices only)
        ref_curves = None
        if float_wasp_indices:
            cache_key_ref = ("ref", shock, tuple(sorted(float_wasp_indices)))
            ref_curves = cache.get(cache_key_ref)
            if ref_curves is None:
                try:
                    ref_curves = load_daily_curves(
                        date=date_rates,
                        indices=float_wasp_indices,
                        shock=shock,
                    )
                except RuntimeError:
                    ref_curves = None  # floating deals fall back to static RateRef
                if ref_curves is not None:
                    cache.put(cache_key_ref, ref_curves)

        # 4e. Build rate matrix
        rate_matrix = build_rate_matrix(deals_use, days, ref_curves, date_run=start)

        # 4f. compute_daily_pnl (one vectorized broadcast)
        daily_pnl = compute_daily_pnl(
            nominal_daily,
            ois_matrix,
            rate_matrix,
            mm[:, np.newaxis],
            accrual_days=accrual_days,
        )

        # 4g. aggregate_to_monthly
        monthly = aggregate_to_monthly(
            daily_pnl, nominal_daily, ois_matrix, rate_matrix, days,
            date_rates=pd.Timestamp(date_rates) if date_rates else None,
        )

        # 4h. Enrich monthly with deal metadata for strategy pivot
        deal_meta_cols = [
            c for c in ["Product", "Currency", "Direction", "Strategy IAS",
                         "Périmètre TOTAL", "Clientrate", "EqOisRate", "YTM", "CocRate",
                         "Counterparty", "Dealid", "Maturitydate", "is_floating"]
            if c in deals_use.columns
        ]
        for col in deal_meta_cols:
            monthly[col] = monthly["deal_idx"].map(deals_use[col])

        # 4i. Add Days in Month for strategy pivot
        monthly["Days in Month"] = monthly["Month"].apply(lambda p: p.days_in_month if hasattr(p, "days_in_month") else 30)

        # OISfwd and Nominal already set by aggregate_to_monthly

        monthly["Shock"] = shock

        # 5. Strategy pivot — deals with Strategy IAS
        strategy_result = compute_strategy_pnl(monthly)

        # 6. Non-strategy deals (filter out strategy deals from monthly)
        non_strat = monthly[monthly["Strategy IAS"].isna()].copy()

        # 7. BOOK2 IRS MTM
        book2 = compute_book2_mtm(irs_stock, date_rates, shock)

        # 8. Merge all
        merged_pnl = merge_results(non_strat, strategy_result, book2)
        all_results.append(merged_pnl)

    # 9. Concat all shock results
    if not all_results:
        return pd.DataFrame()
    return pd.concat(all_results, ignore_index=True)
