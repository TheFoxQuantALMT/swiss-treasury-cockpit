"""ECB SDMX data provider for EUR/CHF exchange rate and policy rates.

Adapted from alm-bond-engine ecb_provider.py.
Uses the ECB Statistical Data Warehouse REST API (SDMX 2.1).
No API key required.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
from loguru import logger

from cockpit.data.fetchers.circuit_breaker import CircuitBreaker

_ECB_BASE = "https://data-api.ecb.europa.eu/service/data"

_ecb_breaker = CircuitBreaker(name="ECB", failure_threshold=3, reset_timeout=60.0)

# ECB policy rates
_POLICY_RATE_KEYS = {
    "deposit_facility": "FM.B.U2.EUR.4F.KR.DFR.LEV",
    "main_refinancing": "FM.B.U2.EUR.4F.KR.MRR_FR.LEV",
}

# EUR/CHF exchange rate
_EURCHF_FLOW = "EXR"
_EURCHF_KEY = "D.CHF.EUR.SP00.A"


class ECBFetcher:
    """ECB Statistical Data Warehouse client.

    Fetches EUR/CHF exchange rate and ECB policy rates
    via SDMX 2.1 REST API. No API key needed.
    """

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    async def fetch_ecb_rates(self) -> dict[str, float]:
        """Fetch current ECB policy rates.

        Returns:
            {"deposit_facility": 2.00, "main_refinancing": 2.40}
        """
        rates: dict[str, float] = {}
        # ECB rates change infrequently — look back 365 days to catch the last change
        from_date = date.today() - timedelta(days=365)

        for name, key in _POLICY_RATE_KEYS.items():
            parts = key.split(".", 1)
            if len(parts) == 2:
                records = await self._fetch_series(
                    parts[0], parts[1], from_date,
                )
                if records:
                    rates[name] = records[-1]["value"]

        return rates

    async def fetch_eur_chf(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch EUR/CHF daily exchange rate.

        Returns:
            List of {"date": str, "value": float} records.
        """
        if to_date is None:
            to_date = date.today()
        if from_date is None:
            from_date = to_date - timedelta(days=30)

        return await self._fetch_series(
            _EURCHF_FLOW, _EURCHF_KEY, from_date, to_date,
        )

    async def fetch_eur_chf_latest(self) -> dict[str, Any] | None:
        """Fetch the latest EUR/CHF rate.

        Returns:
            {"date": "2026-03-28", "value": 0.904} or None.
        """
        records = await self.fetch_eur_chf(
            from_date=date.today() - timedelta(days=10),
        )
        if records:
            return records[-1]
        return None

    async def _fetch_series(
        self,
        flow: str,
        key: str,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch a single SDMX series from ECB."""
        url = f"{_ECB_BASE}/{flow}/{key}"
        params: dict[str, str] = {
            "format": "csvdata",
        }
        if from_date:
            params["startPeriod"] = from_date.isoformat()
        if to_date:
            params["endPeriod"] = to_date.isoformat()

        if _ecb_breaker.is_open():
            raise ConnectionError(f"{_ecb_breaker.name} circuit open")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                _ecb_breaker.record_success()
                return self._parse_csv(resp.text)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            _ecb_breaker.record_failure()
            logger.warning(f"ECB API error for {flow}/{key}: {e}")
            raise
        except httpx.HTTPError as e:
            logger.warning(f"ECB API error for {flow}/{key}: {e}")
            return []

    @staticmethod
    def _parse_csv(csv_text: str) -> list[dict[str, Any]]:
        """Parse ECB CSV response (handles both comma and semicolon separators)."""
        lines = csv_text.strip().split("\n")
        if len(lines) < 2:
            return []

        headers = [h.strip() for h in lines[0].split(",")]
        try:
            date_idx = headers.index("TIME_PERIOD")
            value_idx = headers.index("OBS_VALUE")
        except ValueError:
            headers = [h.strip() for h in lines[0].split(";")]
            try:
                date_idx = headers.index("TIME_PERIOD")
                value_idx = headers.index("OBS_VALUE")
            except ValueError:
                return []

        sep = ";" if ";" in lines[0] else ","
        results = []
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(sep)]
            if len(parts) > max(date_idx, value_idx):
                try:
                    results.append({
                        "date": parts[date_idx],
                        "value": float(parts[value_idx]),
                    })
                except (ValueError, IndexError):
                    continue

        return results
