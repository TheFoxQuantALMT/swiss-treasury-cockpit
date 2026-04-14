"""Forward curve loading — WASP daily grid and WIRP overlay."""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_WASP_PATH = os.environ.get("WASP_TOOLS_PATH", "").strip()
if _WASP_PATH:
    sys.path.insert(0, _WASP_PATH)

try:
    import waspTools as wt
except Exception as exc:
    wt = None
    _WASP_ERROR = exc
else:
    _WASP_ERROR = None


def _require_wasp():
    """Raise immediately if waspTools is not available."""
    if wt is None:
        raise RuntimeError(f"waspTools is required but unavailable: {_WASP_ERROR}")


def load_daily_curves(
    date: Any,
    indices: list[str],
    shock: str,
    *,
    end_day: int = 1856,
) -> pd.DataFrame:
    """Load daily forward curves from WASP for the given indices and shock."""
    _require_wasp()
    shock_f = 0.0 if shock == "wirp" else float(shock)

    # Pre-load all ramp markets (registers mktUSD/mktEUR/… handles)
    wt.loadAllRampMarket(wt.lastBusinessDay(date), Shock=shock_f)

    def _load_one(indice: str) -> pd.DataFrame:
        ccy = wt.indiceDict.get(indice)
        mkt = f"mkt{ccy}" if ccy else None
        return wt.dailyFwdRate(dateC=date, indice=indice, mkt=mkt, startDay=-31, endDay=end_day, Shock=shock_f)

    with ThreadPoolExecutor(max_workers=len(indices)) as pool:
        frames = list(pool.map(_load_one, indices))
    df = pd.concat(frames, ignore_index=True)

    df["Date"] = pd.to_datetime(df["Date"])
    df["dateM"] = df["Date"].dt.to_period("M")
    return df


def overlay_wirp(base: pd.DataFrame, wirp: pd.DataFrame) -> pd.DataFrame:
    wirp_renamed = wirp[["Indice", "Meeting", "Rate"]].rename(columns={"Meeting": "Date"})
    wirp_renamed["Date"] = pd.to_datetime(wirp_renamed["Date"])
    base_sorted = base.sort_values("Date").copy()
    wirp_sorted = wirp_renamed.sort_values("Date")

    merged = pd.merge_asof(
        base_sorted,
        wirp_sorted,
        on="Date",
        by="Indice",
        tolerance=pd.Timedelta("2D"),
        direction="nearest",
    )
    merged["value"] = merged.groupby("Indice")["Rate"].ffill()
    merged["value"] = merged.groupby("Indice")["value"].bfill()
    merged["value"] = merged["value"].fillna(base_sorted["value"])
    merged = merged.drop(columns=["Rate"], errors="ignore")
    return merged


def _ensure_ramp_loaded(date: Any, shock: float = 0.0) -> None:
    """Call ``loadAllRampMarket`` once per (date, shock) to populate mkt handles."""
    _require_wasp()
    bday = wt.lastBusinessDay(date)
    key = ("agg", str(bday), shock)
    if key not in _ramp_loaded:
        wt.loadAllRampMarket(bday, Shock=shock)
        _ramp_loaded.add(key)


def _ensure_carry_ramp_loaded(date: Any) -> None:
    """Load MESA MARKET ALMT ramp via wt.loadCarryCompoundedMarket.

    Note: this overwrites mkt{CCY} handles (shared with AGG ramp).
    Call AGG ramp reload after carry if both are needed in same session.
    """
    _require_wasp()
    bday = wt.lastBusinessDay(date)
    key = ("carry", str(bday))
    if key not in _ramp_loaded:
        wt.loadCarryCompoundedMarket(bday)
        _ramp_loaded.add(key)
        # Invalidate AGG ramp cache since handles were overwritten
        _ramp_loaded.discard(("agg", str(bday), 0.0))


_ramp_loaded: set[tuple] = set()


def load_carry_compounded(
    start: Any,
    end: Any,
    currency: str,
) -> float:
    """Load WASP carry-compounded rate for a (start, end, currency) period.

    Uses carry-specific indices (CHF->CSCML5, EUR->ESAVB1, USD->USSOFR,
    GBP->GBPOIS) and the ``MESA MARKET ALMT`` ramp.
    """
    _require_wasp()
    _ensure_carry_ramp_loaded(start)
    return wt.carryCompounded(start, end, currency)


_carry_cache: dict[tuple[str, str, str], float] = {}


def load_carry_compounded_cached(
    start: Any,
    end: Any,
    currency: str,
) -> float:
    """Cached version of load_carry_compounded — avoids duplicate WASP calls.

    Cache key is (currency, start_date_str, end_date_str).
    Call clear_carry_cache() between runs to reset.
    """
    key = (currency, str(pd.Timestamp(start).date()), str(pd.Timestamp(end).date()))
    if key not in _carry_cache:
        _carry_cache[key] = load_carry_compounded(start, end, currency)
    return _carry_cache[key]


def clear_carry_cache() -> None:
    """Reset the carry-compounded cache between engine runs."""
    _carry_cache.clear()


def load_carry_compounded_series(
    start: Any,
    end: Any,
    currency: str,
) -> pd.DataFrame:
    """Monthly carry-compounded series via WASP for validation."""
    _require_wasp()
    months = pd.date_range(start=start, end=end, freq="ME").to_list()
    if pd.Timestamp(end) not in [pd.Timestamp(m) for m in months]:
        months.append(pd.Timestamp(end))

    rows = []
    for month_end in months:
        carry = load_carry_compounded(start, month_end, currency)
        rows.append({"Date": month_end, "Currency": currency, "CarryCompounded": carry})

    return pd.DataFrame(rows)


class CurveCache:
    def __init__(self) -> None:
        self._store: dict[tuple, pd.DataFrame] = {}

    def get(self, key: tuple) -> Optional[pd.DataFrame]:
        df = self._store.get(key)
        return df.copy() if df is not None else None

    def put(self, key: tuple, df: pd.DataFrame) -> None:
        self._store[key] = df.copy()
