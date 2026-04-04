"""SNB (Swiss National Bank) data fetcher for sight deposits and rates.

Adapted from alm-bond-engine snb.py.
Removed database storage, added sight deposits cube.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import httpx
from loguru import logger

from cockpit.data.fetchers.circuit_breaker import CircuitBreaker

_snb_breaker = CircuitBreaker(name="SNB", failure_threshold=3, reset_timeout=60.0)

SNB_API_BASE = os.getenv("SNB_API_BASE", "https://data.snb.ch/api/cube")

# SNB API cube identifiers
_CUBES = {
    "sight_deposits": "snbgwdchfsgw",  # Sight deposits (weekly, Monday)
    "saron": "snboffzisa",  # SARON fixing
    "confederation_yields": "rendeidgam",  # CHF gov bond yields
    "fx_transactions": "snbfxtr",  # Official FX transactions (quarterly)
}


def _build_params(
    from_date: date | None,
    to_date: date | None,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if from_date:
        params["fromDate"] = from_date.isoformat()
    if to_date:
        params["toDate"] = to_date.isoformat()
    return params


async def _fetch_snb_cube(
    cube_key: str,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch and parse data from an SNB API cube.

    Returns:
        Parsed records, or empty list on failure.
    """
    if _snb_breaker.is_open():
        raise ConnectionError(f"{_snb_breaker.name} circuit open")

    cube = _CUBES[cube_key]
    params = _build_params(from_date, to_date)

    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{SNB_API_BASE}/{cube}/data/csv/{cube}.csv"
        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            _snb_breaker.record_success()
            return _parse_snb_csv(resp.text)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            _snb_breaker.record_failure()
            logger.warning(f"Failed to fetch SNB {cube_key}: {e}")
            raise
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 or e.response.status_code == 429:
                _snb_breaker.record_failure()
            else:
                _snb_breaker.record_failure(transient=False)
            logger.warning(f"Failed to fetch SNB {cube_key}: {e}")
            return []
        except httpx.HTTPError as e:
            logger.warning(f"Failed to fetch SNB {cube_key}: {e}")
            return []


async def fetch_sight_deposits(
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch BNS sight deposits (weekly, published Mondays).

    Key proxy for FX intervention detection.
    Domestic sight deposits have correlation 0.68 with actual interventions.
    Total sight deposits have correlation 0.28 only (unreliable alone).

    Returns:
        List of records with date, total, domestic deposit values.
    """
    if from_date is None:
        from_date = date.today() - timedelta(days=60)
    return await _fetch_snb_cube("sight_deposits", from_date, to_date)


async def fetch_saron(
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch SARON (Swiss Average Rate Overnight) fixing rates."""
    return await _fetch_snb_cube("saron", from_date, to_date)


async def fetch_confederation_yields(
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    """Fetch Swiss Confederation bond yield curve data."""
    return await _fetch_snb_cube("confederation_yields", from_date, to_date)


def _parse_snb_csv(csv_text: str) -> list[dict[str, Any]]:
    """Parse SNB CSV response.

    SNB CSV has a metadata header block (CubeId, PublishingDate) followed by
    an empty line, then the actual data block (Date;D0;Value). We skip to the
    data block by finding the second header row.
    """
    lines = csv_text.strip().split("\n")

    # Find the actual data header (starts with "Date" or after an empty line)
    data_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip().lstrip("\ufeff").strip('"')
        if stripped.startswith("Date"):
            data_start = i
            break

    if data_start >= len(lines) - 1:
        return []

    headers = [h.strip().lstrip("\ufeff").strip('"') for h in lines[data_start].split(";")]
    records = []
    for line in lines[data_start + 1:]:
        if not line.strip():
            continue
        values = [v.strip().strip('"') for v in line.split(";")]
        if len(values) == len(headers):
            record: dict[str, Any] = {}
            for h, v in zip(headers, values):
                if not v:
                    continue
                try:
                    record[h] = float(v)
                except ValueError:
                    record[h] = v
            # Only include records that have a Value
            if "Value" in record:
                records.append(record)
    return records
