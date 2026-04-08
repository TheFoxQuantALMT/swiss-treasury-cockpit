"""P&L computation engine — daily core, monthly aggregation, strategy pivot."""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

from pnl_engine.config import CURRENCY_TO_OIS, MM_BY_CURRENCY, PRODUCT_RATE_COLUMN, SHOCKS, FLOAT_NAME_TO_WASP, LOOKBACK_DAYS
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
) -> dict:
    """Aggregate daily arrays over a boolean day-mask into a single column of metrics.

    Returns dict of (n_deals,) arrays for all core + CoC metrics.
    """
    n_deals = daily_pnl.shape[0]
    n_mask_days = mask.sum()

    pnl = daily_pnl[:, mask].sum(axis=1)
    nom_days = nominal_daily[:, mask].sum(axis=1)
    nom_avg = nom_days / n_cal_days if n_cal_days > 0 else np.zeros(n_deals)

    ois_x_nom = (ois_daily[:, mask] * nominal_daily[:, mask]).sum(axis=1)
    rate_x_nom = (rate_daily[:, mask] * nominal_daily[:, mask]).sum(axis=1)
    safe_nom = np.where(nom_days == 0, np.nan, nom_days)

    out = {
        "PnL": pnl,
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
        out["FundingCost"] = fund
        out["CoC_Simple"] = gross - fund

        rate_factors = 1.0 + rate_slice * d_i[np.newaxis, :] / mm_slice
        funding_factors = 1.0 + funding_slice * d_i[np.newaxis, :] / mm_slice
        out["CoC_Compound"] = nom_avg * (np.prod(rate_factors, axis=1) - np.prod(funding_factors, axis=1))

        fund_x_nom = (funding_slice * nom_slice).sum(axis=1)
        out["FundingRate"] = fund_x_nom / safe_nom
    elif funding_daily is not None:
        zeros = np.zeros(n_deals)
        for k in ("GrossCarry", "FundingCost", "CoC_Simple", "CoC_Compound", "FundingRate"):
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
) -> pd.DataFrame:
    """Aggregate daily arrays to monthly per deal.

    Core columns (always computed):
        PnL: sum of daily values.
        Nominal: average daily nominal over calendar days in the month.
        OISfwd: nominal-weighted average.
        RateRef: nominal-weighted average.
        nominal_days: sum of daily nominals (for rate weighting).

    CoC columns (when ``funding_daily`` is provided):
        GrossCarry: sum(Nominal x RateRef x d_i / D) per IFRS 9.B5.4.5.
        FundingCost: sum(Nominal x FundingRate x d_i / D).
        CoC_Simple: GrossCarry - FundingCost (NII component, BCBS 368).
        CoC_Compound: Nom_avg x [prod(1 + r_i x d_i/D) - prod(1 + f_i x d_i/D)]
                      per ISDA 2021 §6.9 compounding in arrears.
        FundingRate: nominal-weighted average of funding rate.

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
    )

    rows: list[dict] = []

    for j, m in enumerate(unique_months):
        month_mask = np.asarray(month_idx == m)
        n_cal_days = int(month_mask.sum())

        agg_total = _aggregate_slice(mask=month_mask, n_cal_days=n_cal_days, **common_kw)

        if date_rates is None:
            # Backward compat: no split
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
            agg_real = _aggregate_slice(mask=realized_within, n_cal_days=n_realized_days, **common_kw)
            agg_fore = _aggregate_slice(mask=forecast_within, n_cal_days=n_forecast_days, **common_kw)

            for deal_i in range(n_deals):
                for pnl_type, agg in [("Total", agg_total), ("Realized", agg_real), ("Forecast", agg_fore)]:
                    row = {"deal_idx": deal_i, "Month": m, "PnL_Type": pnl_type}
                    for k, arr in agg.items():
                        row[k] = arr[deal_i]
                    rows.append(row)
        elif m < rates_month:
            # Past month: all realized
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
    agg = strat.groupby(present_group).agg(
        Amount=("Amount", "sum") if "Amount" in strat.columns else ("Nominal", "sum"),
        Nominal=("Nominal", "sum"),
        PnL=("PnL", "sum") if "PnL" in strat.columns else ("pnl", "sum"),
    ).reset_index()

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
    pivot_vals = ["Amount", "Nominal", "Clientrate", "EqOisRate", "CocRate", "OISfwd", "YTM", "PnL"]
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
    leg["PnL"] = pnl
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
    leg["PnL"] = pnl_hcd
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
    leg["PnL"] = pnl_b
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
    leg["PnL"] = pnl_bhcd
    leg["Nominal"] = nom_bhcd
    leg["RateRef"] = rate_bmargin
    leg["OISfwd"] = ois_bhcd
    leg["Amount"] = np.where(mask_b, _safe(pivoted, "Amount_HCD").values, 0.0)
    legs.append(leg)

    combined = pd.concat(legs, ignore_index=True)

    # Remove rows where condition was false (all values = 0)
    combined = combined[combined["Nominal"] != 0].copy()

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
    """BOOK2 IRS MTM via waspTools.stockSwapMTM; falls back to deterministic mock.

    Returns a DataFrame with MTM values per deal.
    """
    try:
        from pnl_engine.curves import wt  # reuse the WASP_TOOLS_PATH-aware import
        stockSwapMTM = wt.stockSwapMTM  # type: ignore[union-attr]
        mtm = stockSwapMTM(irs_stock, calc_date, shock)
        return mtm
    except (ImportError, Exception):
        # Analytical MTM fallback: PV of rate differential
        # MTM ≈ Notional × (fixed_rate - OIS_fwd) × remaining_years
        # First-order approximation — adequate for dashboard, not regulatory
        if irs_stock.empty:
            return pd.DataFrame(columns=["Deal", "Currency", "MTM"])
        result = irs_stock.copy()

        calc_ts = pd.Timestamp(calc_date)
        notional = pd.to_numeric(
            result.get("Notional", result.get("notional", pd.Series(dtype=float))),
            errors="coerce",
        ).fillna(0)
        rate = pd.to_numeric(
            result.get("Rate", result.get("Clientrate", result.get("rate", pd.Series(dtype=float)))),
            errors="coerce",
        ).fillna(0)
        maturity = pd.to_datetime(
            result.get("Maturity Date", result.get("Maturitydate", pd.Series(dtype="datetime64[ns]"))),
            errors="coerce",
        )
        remaining_years = ((maturity - calc_ts).dt.days / 365.0).clip(lower=0).fillna(0)

        # Assume OIS fwd ≈ 1% (conservative mid for CHF/EUR/USD)
        # Shock adjusts: +50bp → 1.50%, etc.
        ois_proxy = 0.01
        if shock and shock not in ("0", "wirp"):
            try:
                ois_proxy += int(shock) / 10000
            except (ValueError, TypeError):
                pass

        # Pay fixed → MTM positive when OIS rises above fixed rate
        # Receive fixed → MTM positive when OIS falls below fixed rate
        pay_receive = result.get("Pay/Receive", result.get("pay_receive", pd.Series(["PAY"] * len(result))))
        sign = np.where(pay_receive.str.upper().str.contains("REC", na=False), 1.0, -1.0)

        result["MTM"] = sign * notional * (rate - ois_proxy) * remaining_years
        return result


def merge_results(
    non_strategy: pd.DataFrame,
    strategy: pd.DataFrame,
    book2: pd.DataFrame,
) -> pd.DataFrame:
    """Concatenate non-strategy, strategy, and book2 results with direction filtering.

    Direction filters applied to strategy legs:
    - BND-HCD / BND-NHCD: exclude Direction L and D
    - IAM/LD-HCD / IAM/LD-NHCD: exclude Direction B and S (bond-like)
    """
    parts = []

    if non_strategy is not None and not non_strategy.empty:
        parts.append(non_strategy)

    if strategy is not None and not strategy.empty:
        # Apply direction filters
        bnd_mask = strategy["Product2BuyBack"].isin(["BND-HCD", "BND-NHCD"])
        iam_mask = strategy["Product2BuyBack"].isin(["IAM/LD-HCD", "IAM/LD-NHCD"])

        exclude_bnd = bnd_mask & strategy["Direction"].isin(["L", "D"])
        exclude_iam = iam_mask & strategy["Direction"].isin(["B", "S"])

        filtered = strategy[~(exclude_bnd | exclude_iam)]
        parts.append(filtered)

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

    # Drop RFR floating legs: ref_index maps to an OIS index -> OIS - RefRate = 0,
    # and their Echeancier V-leg balance was already dropped. These produce zero
    # P&L and pollute the output with zero-nominal rows.
    _OIS_INDICES = set(CURRENCY_TO_OIS.values())
    is_rfr_float = df["is_floating"] & df["ref_index"].isin(_OIS_INDICES)
    if is_rfr_float.any():
        logger.info("Dropping %d RFR floating legs (OIS - RefRate = 0)", is_rfr_float.sum())
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
        rate_matrix = build_rate_matrix(deals_use, days, ref_curves)

        # 4f. compute_daily_pnl (one vectorized broadcast)
        daily_pnl = compute_daily_pnl(
            nominal_daily,
            ois_matrix,
            rate_matrix,
            mm[:, np.newaxis] * np.ones((1, len(days))),
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
