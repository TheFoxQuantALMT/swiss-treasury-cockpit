"""Unified data manager for all market data sources.

Adapted from macro-cbwatch automation/fetchers/data_manager.py.
Orchestrates FRED, ECB, SNB, and yfinance fetchers with graceful degradation.
Falls back to yesterday's data if any source fails.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from loguru import logger

from cockpit.data.fetchers import FREDFetcher, ECBFetcher, fetch_sight_deposits, fetch_saron, YFinanceFetcher
from cockpit.config import DATA_DIR

ARCHIVE_DIR = DATA_DIR / "archive"


class DataManager:
    """Unified facade over all market data providers.

    Handles concurrent fetching, fallback to stale data, and JSON persistence.
    """

    def __init__(self, fred_api_key: str = ""):
        self._fred_key = fred_api_key
        self._fred: FREDFetcher | None = None
        self._ecb = ECBFetcher()
        self._yfinance = YFinanceFetcher()

    def _get_fred(self) -> FREDFetcher | None:
        if self._fred is None and self._fred_key:
            self._fred = FREDFetcher(self._fred_key)
        return self._fred

    async def refresh_all_data(self) -> dict[str, Any]:
        """Fetch all data sources concurrently.

        Returns:
            {
                "rates": {...},
                "fx": {...},
                "energy": {...},
                "sight_deposits": {...},
                "stale": ["source_name", ...],  # sources that failed
                "timestamp": "2026-03-30T07:00:00",
            }
        """
        # Archive current data before overwriting
        self._archive_current()

        results: dict[str, Any] = {
            "stale": [],
            "timestamp": date.today().isoformat(),
        }

        # Run all fetchers concurrently
        tasks = {
            "fred": self._fetch_fred(),
            "ecb": self._fetch_ecb(),
            "snb": self._fetch_snb(),
            "yfinance": self._fetch_yfinance(),
        }

        gathered = await asyncio.gather(
            *tasks.values(), return_exceptions=True,
        )

        for source, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                logger.error(f"Fetcher {source} failed: {result}")
                results["stale"].append(source)
            elif result is not None:
                results.update(result)
            else:
                results["stale"].append(source)

        # For any stale sources, load yesterday's data
        if results["stale"]:
            self._load_stale_fallback(results)

        return results

    async def _fetch_fred(self) -> dict[str, Any] | None:
        """Fetch Fed rates and macro indicators from FRED."""
        fred = self._get_fred()
        if not fred:
            logger.warning("No FRED API key configured")
            return None

        fed_rates = await fred.fetch_fed_rates()
        daily = await fred.fetch_daily_indicators()
        macro = await fred.fetch_macro_indicators()
        daily_history = await fred.fetch_daily_history()

        return {
            "fed_rates": fed_rates,
            "daily_indicators": daily,
            "macro_indicators": macro,
            "daily_history": daily_history,
        }

    async def _fetch_ecb(self) -> dict[str, Any] | None:
        """Fetch ECB rates and EUR/CHF from ECB SDMX."""
        ecb_rates = await self._ecb.fetch_ecb_rates()
        eur_chf = await self._ecb.fetch_eur_chf()
        eur_chf_latest = await self._ecb.fetch_eur_chf_latest()

        return {
            "ecb_rates": ecb_rates,
            "eur_chf_history": eur_chf,
            "eur_chf_latest": eur_chf_latest,
        }

    async def _fetch_snb(self) -> dict[str, Any] | None:
        """Fetch sight deposits and SARON from SNB."""
        deposits = await fetch_sight_deposits()
        saron = await fetch_saron()

        # Pivot sight deposits: group by date, map D0 codes to named fields
        # GI = domestic (Giroguthaben Inland), TG = total, UEB = foreign
        deposit_map: dict[str, dict[str, float]] = {}
        for row in deposits:
            d = row.get("Date", "")
            code = row.get("D0", "")
            value = row.get("Value")
            if d and value is not None:
                if d not in deposit_map:
                    deposit_map[d] = {"date": d}
                if code == "GI":
                    deposit_map[d]["domestic"] = value
                elif code == "TG":
                    deposit_map[d]["total"] = value
                elif code == "UEB":
                    deposit_map[d]["foreign"] = value

        deposit_series = sorted(deposit_map.values(), key=lambda x: x.get("date", ""))

        # Extract SNB policy rate (D0=LZ = Leitzins)
        # Note: this cube (snboffzisa) contains official policy rates, not SARON.
        # D0=LZ is the SNB policy rate, D0=EF is the ECB deposit facility.
        snb_rate = None
        for row in reversed(saron):
            if row.get("D0") == "LZ" and "Value" in row:
                snb_rate = {"date": row.get("Date", ""), "value": row["Value"]}
                break

        return {
            "sight_deposits": deposit_series,
            "snb_rate": snb_rate,
            "saron": None,  # SARON daily fixing not available from this SNB cube
        }

    async def _fetch_yfinance(self) -> dict[str, Any] | None:
        """Fetch USD/CHF, Brent, EU gas from Yahoo Finance."""
        all_data = await self._yfinance.fetch_all(period_days=30)

        return {
            "usd_chf_history": all_data.get("usd_chf", []),
            "brent_history": all_data.get("brent", []),
            "eu_gas_history": all_data.get("eu_gas", []),
            "vix_history": all_data.get("vix", []),
            "gbp_chf_history": all_data.get("gbp_chf", []),
        }

    def _archive_current(self) -> None:
        """Archive current JSON files before overwriting."""
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        archive_subdir = ARCHIVE_DIR / today

        if archive_subdir.exists():
            return  # Already archived today

        archive_subdir.mkdir(exist_ok=True)
        for json_file in DATA_DIR.glob("*.json"):
            shutil.copy2(json_file, archive_subdir / json_file.name)
        logger.info(f"Archived current data to {archive_subdir}")

    # Mapping from source name to the top-level keys it produces in the
    # unified snapshot. Used to lift stale fields back into `results` when
    # a live fetch fails. Keep in sync with the _fetch_* methods above.
    _SOURCE_KEYS: dict[str, tuple[str, ...]] = {
        "fred": ("fed_rates", "daily_indicators", "macro_indicators", "daily_history"),
        "ecb": ("ecb_rates", "eur_chf_history", "eur_chf_latest"),
        "snb": ("sight_deposits", "snb_rate", "saron"),
        "yfinance": (
            "usd_chf_history",
            "brent_history",
            "eu_gas_history",
            "vix_history",
            "gbp_chf_history",
        ),
    }

    def _load_stale_fallback(self, results: dict[str, Any]) -> None:
        """Load yesterday's data for any failed sources.

        Reads the archived unified snapshot (`latest_snapshot.json`) and lifts
        the keys belonging to each failed source back into `results`, plus a
        `<source>_stale_data` marker for downstream consumers.
        """
        if not ARCHIVE_DIR.exists():
            return

        archives = sorted(
            [d for d in ARCHIVE_DIR.iterdir() if d.is_dir()],
            reverse=True,
        )

        if not archives:
            return

        latest_archive = archives[0]
        snapshot_file = latest_archive / "latest_snapshot.json"
        if not snapshot_file.exists():
            logger.warning(
                f"No archived snapshot at {snapshot_file}; "
                f"cannot restore stale sources: {results['stale']}"
            )
            return

        try:
            with open(snapshot_file) as f:
                stale_snapshot = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Failed to read stale snapshot {snapshot_file}: {e}")
            return

        logger.warning(
            f"Loading stale data from {latest_archive.name} "
            f"for sources: {results['stale']}"
        )

        for source in results["stale"]:
            keys = self._SOURCE_KEYS.get(source)
            if not keys:
                continue
            loaded: dict[str, Any] = {}
            for key in keys:
                if key in stale_snapshot:
                    results[key] = stale_snapshot[key]
                    loaded[key] = stale_snapshot[key]
            if loaded:
                results[f"{source}_stale_data"] = loaded
                logger.info(
                    f"Restored {len(loaded)} stale field(s) for {source} "
                    f"from {latest_archive.name}"
                )

    def save_results(self, results: dict[str, Any]) -> None:
        """Persist fetched data to JSON files in data/ directory."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Save a unified snapshot for the agents
        snapshot_path = DATA_DIR / "latest_snapshot.json"
        with open(snapshot_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Saved data snapshot to {snapshot_path}")
