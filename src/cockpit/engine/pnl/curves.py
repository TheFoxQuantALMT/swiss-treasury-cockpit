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

        def _load_one(indice: str) -> pd.DataFrame:
            return wt.dailyFwdRate(dateC=date, indice=indice, startDay=-31, endDay=end_day, Shock=shock_f)

        with ThreadPoolExecutor(max_workers=len(indices)) as pool:
            frames = list(pool.map(_load_one, indices))
        df = pd.concat(frames, ignore_index=True)

    df["Date"] = pd.to_datetime(df["Date"])
    df["dateM"] = df["Date"].dt.to_period("M")
    return df


def overlay_wirp(base: pd.DataFrame, wirp: pd.DataFrame) -> pd.DataFrame:
    merged = base.merge(
        wirp[["Indice", "Meeting", "Rate"]],
        how="left",
        left_on=["Indice", "Date"],
        right_on=["Indice", "Meeting"],
    )
    merged["value"] = merged.groupby("Indice")["Rate"].ffill()
    merged["value"] = merged.groupby("Indice")["value"].bfill()
    merged["value"] = merged["value"].fillna(base["value"])
    merged = merged.drop(columns=["Meeting", "Rate"], errors="ignore")
    return merged


class CurveCache:
    def __init__(self) -> None:
        self._store: dict[tuple, pd.DataFrame] = {}

    def get(self, key: tuple) -> Optional[pd.DataFrame]:
        df = self._store.get(key)
        return df.copy() if df is not None else None

    def put(self, key: tuple, df: pd.DataFrame) -> None:
        self._store[key] = df.copy()
