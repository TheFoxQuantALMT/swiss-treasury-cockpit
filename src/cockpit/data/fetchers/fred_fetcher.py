"""FRED (Federal Reserve Economic Data) fetcher for macro indicators.

Adapted from alm-bond-engine fred_collector.py.
Async httpx client with rate limiting and circuit breaker.

Free API key from: https://fred.stlouisfed.org/docs/api/api_key.html
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import httpx
from loguru import logger

from cockpit.data.fetchers.circuit_breaker import CircuitBreaker

_BASE_URL = "https://api.stlouisfed.org/fred"

_fred_breaker = CircuitBreaker(name="FRED", failure_threshold=3, reset_timeout=60.0)

# Macro-relevant FRED series for central bank watch
MACRO_SERIES = {
    # Fed policy rates
    "DFEDTARU": "Fed Funds Target Upper",
    "DFEDTARL": "Fed Funds Target Lower",
    "DFF": "Effective Federal Funds Rate",
    # Inflation
    "PCEPI": "PCE Price Index",
    "PCEPILFE": "Core PCE Price Index",
    "T5YIE": "5-Year Breakeven Inflation",
    "T10YIE": "10-Year Breakeven Inflation",
    # Labor market
    "UNRATE": "Unemployment Rate",
    "PAYEMS": "Total Nonfarm Payrolls",
    # GDP
    "GDP": "Gross Domestic Product",
    # Treasury yields (for context)
    "DGS2": "US 2-Year Treasury",
    "DGS5": "US 5-Year Treasury",
    "DGS10": "US 10-Year Treasury",
    # Volatility
    "VIXCLS": "VIX",
    # UK / BoE (limited availability on FRED — Gilt yields come from Bloomberg)
    "IRLTLT01GBM156N": "UK Long-Term Gov Bond Yield (OECD)",
    "LRHUTTTTGBM156S": "UK Unemployment Rate",
}

# Key series for the daily brief
DAILY_SERIES = {
    "DFEDTARU": "fed_funds_upper",
    "DFEDTARL": "fed_funds_lower",
    "DFF": "fed_funds_effective",
    "DGS2": "us_2y",
    "DGS5": "us_5y",
    "DGS10": "us_10y",
    "T5YIE": "breakeven_5y",
    "T10YIE": "breakeven_10y",
    "VIXCLS": "vix",
}

# Monthly/quarterly series (less frequent updates)
PERIODIC_SERIES = {
    "PCEPI": "pce",
    "PCEPILFE": "core_pce",
    "UNRATE": "unemployment",
    "PAYEMS": "nonfarm_payrolls",
    "GDP": "gdp",
    "IRLTLT01GBM156N": "uk_10y_yield",
    "LRHUTTTTGBM156S": "uk_unemployment",
}


class FREDFetcher:
    """Async FRED API client with rate limiting.

    Args:
        api_key: FRED API key (free from FRED website).
        max_concurrent: Maximum concurrent requests.
        min_interval: Minimum seconds between requests.
    """

    def __init__(
        self,
        api_key: str,
        max_concurrent: int = 5,
        min_interval: float = 0.2,
    ):
        self.api_key = api_key
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._min_interval = min_interval
        self._last_request = 0.0

    async def get_series(
        self,
        series_id: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a FRED time series.

        Returns:
            List of {"date": str, "value": float} records.
        """
        if not self.api_key:
            logger.debug(f"No FRED API key, skipping {series_id}")
            return []

        params: dict[str, str] = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
        }
        if from_date:
            params["observation_start"] = from_date.isoformat()
        if to_date:
            params["observation_end"] = to_date.isoformat()

        if _fred_breaker.is_open():
            raise ConnectionError(f"{_fred_breaker.name} circuit open")

        async with self._semaphore:
            now = asyncio.get_event_loop().time()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)

            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.get(
                        f"{_BASE_URL}/series/observations",
                        params=params,
                    )
                    resp.raise_for_status()
                    self._last_request = asyncio.get_event_loop().time()

                    data = resp.json()
                    observations = data.get("observations", [])

                    result = []
                    for obs in observations:
                        val = obs.get("value", ".")
                        if val == "." or val is None:
                            continue
                        try:
                            result.append({
                                "date": obs["date"],
                                "value": float(val),
                            })
                        except (ValueError, KeyError):
                            continue
                    _fred_breaker.record_success()
                    return result

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                _fred_breaker.record_failure()
                logger.warning(f"FRED API error for {series_id}: {e}")
                raise
            except httpx.HTTPError as e:
                logger.warning(f"FRED API error for {series_id}: {e}")
                return []

    async def get_latest(self, series_id: str) -> float | None:
        """Get the latest value for a series."""
        records = await self.get_series(
            series_id,
            from_date=date.today() - timedelta(days=10),
        )
        if records:
            return records[-1]["value"]
        return None

    async def fetch_fed_rates(self) -> dict[str, Any]:
        """Fetch current Fed policy rates.

        Returns:
            {"upper": 3.75, "lower": 3.50, "effective": 3.58, "mid": 3.625}
        """
        upper = await self.get_latest("DFEDTARU")
        lower = await self.get_latest("DFEDTARL")
        effective = await self.get_latest("DFF")

        result: dict[str, Any] = {}
        if upper is not None:
            result["upper"] = upper
        if lower is not None:
            result["lower"] = lower
        if effective is not None:
            result["effective"] = effective
        if upper is not None and lower is not None:
            result["mid"] = (upper + lower) / 2

        return result

    async def fetch_daily_indicators(self) -> dict[str, Any]:
        """Fetch all daily market indicators.

        Returns:
            Dict mapping indicator names to latest values + date.
        """
        results: dict[str, Any] = {}

        tasks = {
            name: self.get_series(
                series_id,
                from_date=date.today() - timedelta(days=10),
            )
            for series_id, name in DAILY_SERIES.items()
        }

        gathered = await asyncio.gather(
            *tasks.values(), return_exceptions=True,
        )

        for name, result in zip(tasks.keys(), gathered):
            if isinstance(result, list) and result:
                latest = result[-1]
                results[name] = {
                    "value": latest["value"],
                    "date": latest["date"],
                }
            elif isinstance(result, Exception):
                logger.warning(f"Failed to fetch {name}: {result}")

        return results

    async def fetch_daily_history(self, period_days: int = 30) -> dict[str, list[dict[str, Any]]]:
        """Fetch 30d history for all daily series (for time-series charts).

        Returns:
            Dict mapping indicator names to list of {"date": str, "value": float}.
        """
        from_date = date.today() - timedelta(days=period_days)
        results: dict[str, list[dict[str, Any]]] = {}

        history_series = {
            "DGS2": "us_2y",
            "DGS5": "us_5y",
            "DGS10": "us_10y",
            "T5YIE": "breakeven_5y",
            "T10YIE": "breakeven_10y",
            "VIXCLS": "vix",
            "DFF": "fed_funds_effective",
        }

        tasks = {
            name: self.get_series(series_id, from_date=from_date)
            for series_id, name in history_series.items()
        }

        gathered = await asyncio.gather(
            *tasks.values(), return_exceptions=True,
        )

        for name, result in zip(tasks.keys(), gathered):
            if isinstance(result, list):
                results[name] = result
            elif isinstance(result, Exception):
                logger.warning(f"Failed to fetch history for {name}: {result}")
                results[name] = []

        return results

    async def fetch_macro_indicators(self) -> dict[str, Any]:
        """Fetch monthly/quarterly macro indicators (PCE, unemployment, GDP).

        Returns:
            Dict mapping indicator names to latest values + date.
        """
        results: dict[str, Any] = {}

        for series_id, name in PERIODIC_SERIES.items():
            try:
                records = await self.get_series(
                    series_id,
                    from_date=date.today() - timedelta(days=120),
                )
                if records:
                    latest = records[-1]
                    results[name] = {
                        "value": latest["value"],
                        "date": latest["date"],
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch {name}: {e}")

        return results
