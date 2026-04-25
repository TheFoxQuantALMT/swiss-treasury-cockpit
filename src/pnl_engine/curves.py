"""Forward curve loading — WASP daily grid and WIRP overlay.

WASP is a hard requirement: in production the bank's ``wasptools`` wrapper
(which imports ``PyWestminster`` / ``PyWestRamp`` / ``PyFPGTools``) must be
reachable. When it is not — e.g. on a dev laptop off the bank network — the
import below fails and every WASP-using call raises ``RuntimeError`` with a
clear message. Tests that require WASP are gated with ``@pytest.mark.wasp``.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from pnl_engine import wasptools as wt
except Exception as exc:  # WASP binaries unreachable (e.g. dev laptop)
    wt = None
    _WASP_ERROR = exc
else:
    _WASP_ERROR = None


def _require_wasp():
    """Raise immediately if wasptools is not available."""
    if wt is None:
        raise RuntimeError(f"wasptools is required but unavailable: {_WASP_ERROR}")


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

    # Register mktUSD/mktEUR/... handles for (date, shock_f); no-op if already active.
    _ensure_ramp_loaded(date, shock=shock_f)

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


# mkt{CCY} handles are shared between the AGG ramp and the carry ramp, so we
# track the *currently active* state rather than a set of "ever loaded" keys:
# any load overwrites the handles, so a cache that only recorded intent would
# serve stale state after an interleaved load of the other ramp kind.
_active_ramp: Optional[tuple] = None


def _ensure_ramp_loaded(date: Any, shock: float = 0.0) -> None:
    """Load the AGG ramp for (date, shock). No-op if already the active ramp."""
    global _active_ramp
    _require_wasp()
    bday = wt.lastBusinessDay(date)
    key = ("agg", str(bday), shock)
    if _active_ramp == key:
        return
    wt.loadAllRampMarket(bday, Shock=shock)
    _active_ramp = key


def _ensure_carry_ramp_loaded(ref_date: Any) -> None:
    """Load the MESA MARKET ALMT (carry) ramp for ``ref_date``.

    Carry values are shock-independent, so only ``lastBusinessDay(ref_date)``
    is part of the cache key. No-op if already the active ramp.
    """
    global _active_ramp
    _require_wasp()
    bday = wt.lastBusinessDay(ref_date)
    key = ("carry", str(bday))
    if _active_ramp == key:
        return
    wt.loadCarryCompoundedMarket(bday)
    _active_ramp = key


def load_carry_compounded(
    start: Any,
    end: Any,
    currency: str,
    *,
    ref_date: Any,
) -> float:
    """Load WASP carry-compounded rate for a (start, end, currency) period.

    Uses carry-specific indices (CHF->CSCML5, EUR->ESAVB1, USD->USSOFR,
    GBP->GBPOIS) and the ``MESA MARKET ALMT`` ramp. ``ref_date`` is the market
    reference date (typically ``dateRates``) used to load the ramp; it is
    independent of the (start, end) period being priced.
    """
    _require_wasp()
    _ensure_carry_ramp_loaded(ref_date)
    return wt.carryCompounded(start, end, currency)


_carry_cache: dict[tuple[str, str, str], float] = {}


def load_carry_compounded_cached(
    start: Any,
    end: Any,
    currency: str,
    *,
    ref_date: Any,
) -> float:
    """Cached version of load_carry_compounded — avoids duplicate WASP calls.

    Cache key is (currency, start_date_str, end_date_str); carry values are
    shock-independent so shock is not part of the key. ``ref_date`` is forwarded
    to the ramp loader. Call clear_carry_cache() between runs to reset.
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
    *,
    ref_date: Any,
) -> pd.DataFrame:
    """Monthly carry-compounded series via WASP for validation."""
    _require_wasp()
    months = pd.date_range(start=start, end=end, freq="ME").to_list()
    if pd.Timestamp(end) not in [pd.Timestamp(m) for m in months]:
        months.append(pd.Timestamp(end))

    rows = []
    for month_end in months:
        carry = load_carry_compounded(start, month_end, currency, ref_date=ref_date)
        rows.append({"Date": month_end, "Currency": currency, "CarryCompounded": carry})

    return pd.DataFrame(rows)


class CurveCache:
    """Stores forward-curve frames by key.

    Returns the stored frame by reference — callers must not mutate in place.
    All in-tree consumers either filter (which yields a new frame) or call
    `.copy()` explicitly before shifting values.
    """

    def __init__(self) -> None:
        self._store: dict[tuple, pd.DataFrame] = {}

    def get(self, key: tuple) -> Optional[pd.DataFrame]:
        return self._store.get(key)

    def put(self, key: tuple, df: pd.DataFrame) -> None:
        self._store[key] = df
