"""Forward curve loading — WASP daily grid, WIRP overlay, mock fallback."""
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


def load_daily_curves(
    date: Any,
    indices: list[str],
    shock: str,
    *,
    mock_data: Optional[pd.DataFrame] = None,
    end_day: int = 1856,
) -> pd.DataFrame:
    if mock_data is not None:
        df = mock_data.copy()
    elif wt is None:
        raise RuntimeError(f"waspTools unavailable ({_WASP_ERROR}) and no mock_data provided")
    else:
        shock_f = 0.0 if shock == "wirp" else float(shock)

        # Pre-load all ramp markets (registers mktUSD/mktEUR/… handles)
        # Must adjust to last business day — same as dailyFwdRate does internally
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
    if wt is None:
        return
    bday = wt.lastBusinessDay(date)
    key = (str(bday), shock)
    if key not in _ramp_loaded:
        wt.loadAllRampMarket(bday, Shock=shock)
        _ramp_loaded.add(key)


_ramp_loaded: set[tuple] = set()


def load_carry_compounded(
    start: Any,
    end: Any,
    currency: str,
) -> Optional[float]:
    """Load WASP carry-compounded rate for a (start, end, currency) period.

    Uses the WASP ``carryCompounded`` function with carry-specific indices
    (CHF->CSCML5, EUR->ESAVB1, USD->USSOFR, GBP->GBPOIS) and the
    ``MESA MARKET ALMT`` ramp — distinct from OIS forward curves.

    Returns the compounded rate as a float, or None if WASP is unavailable.
    """
    if wt is None:
        return None

    from pnl_engine.config import CURRENCY_TO_CARRY_INDEX

    indice = CURRENCY_TO_CARRY_INDEX.get(currency)
    if indice is None:
        logger.warning("No carry index for currency %s", currency)
        return None

    try:
        _ensure_ramp_loaded(start)
        start_excel = wt.datetime_to_excel_date(start)
        end_excel = wt.datetime_to_excel_date(end)
        mkt_name = f"mkt{currency}"
        res = wt.Fwd(start_excel, end_excel, indice, mkt_name)
        return res.to_list()[0][0][0]
    except Exception as exc:
        logger.warning("carryCompounded failed %s [%s, %s]: %s", currency, start, end, exc)
        return None


def load_carry_compounded_series(
    start: Any,
    end: Any,
    currency: str,
) -> Optional[pd.DataFrame]:
    """Monthly carry-compounded series via WASP for validation.

    Returns DataFrame with columns [Date, CarryCompounded] where each row
    is a month-end carry rate from start to end, or None if WASP unavailable.
    """
    if wt is None:
        return None

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
