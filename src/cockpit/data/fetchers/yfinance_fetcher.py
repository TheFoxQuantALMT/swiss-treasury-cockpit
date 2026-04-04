"""Yahoo Finance fetcher for FX rates and commodity prices.

Fetches USD/CHF, Brent crude, and EU natural gas prices.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import yfinance as yf
from loguru import logger

# Ticker symbols (with fallbacks for unreliable tickers)
TICKERS = {
    "usd_chf": "USDCHF=X",
    "brent": "BZ=F",
    "eu_gas": "TTF=F",
    "vix": "^VIX",
    "gbp_chf": "GBPCHF=X",
}

# Fallback tickers when primary returns sparse data
TICKER_FALLBACKS = {
    "eu_gas": ["NG=F"],  # US natural gas as proxy if TTF unavailable
}


class YFinanceFetcher:
    """Yahoo Finance client for FX and commodity data."""

    async def fetch_usd_chf(
        self,
        period_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch USD/CHF daily rates.

        Returns:
            List of {"date": str, "value": float} records.
        """
        return self._fetch_ticker(TICKERS["usd_chf"], period_days)

    async def fetch_brent(
        self,
        period_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch Brent crude oil futures ($/bbl).

        Returns:
            List of {"date": str, "value": float} records.
        """
        return self._fetch_ticker(TICKERS["brent"], period_days)

    async def fetch_eu_gas(
        self,
        period_days: int = 30,
    ) -> list[dict[str, Any]]:
        """Fetch EU natural gas (TTF) futures (EUR/MWh).

        Returns:
            List of {"date": str, "value": float} records.
        """
        return self._fetch_ticker(TICKERS["eu_gas"], period_days)

    async def fetch_all(
        self,
        period_days: int = 30,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch all tracked tickers.

        Returns:
            Dict mapping name to list of {"date": str, "value": float}.
        """
        results: dict[str, list[dict[str, Any]]] = {}
        for name, ticker in TICKERS.items():
            try:
                data = self._fetch_ticker(ticker, period_days)
                # If primary ticker returns sparse data, try fallbacks
                if len(data) < 5 and name in TICKER_FALLBACKS:
                    for fallback in TICKER_FALLBACKS[name]:
                        try:
                            fallback_data = self._fetch_ticker(fallback, period_days)
                            if len(fallback_data) > len(data):
                                logger.info(
                                    f"{name}: primary {ticker} returned {len(data)} points, "
                                    f"using fallback {fallback} ({len(fallback_data)} points)"
                                )
                                data = fallback_data
                                break
                        except Exception as fe:
                            logger.warning(f"Fallback {fallback} for {name} failed: {fe}")
                results[name] = data
            except Exception as e:
                logger.warning(f"Failed to fetch {name} ({ticker}): {e}")
                results[name] = []
        return results

    @staticmethod
    def _fetch_ticker(
        ticker: str,
        period_days: int,
    ) -> list[dict[str, Any]]:
        """Fetch historical close prices for a ticker.

        Note: yfinance is synchronous internally, but we wrap it
        in async interface for consistency with other fetchers.
        """
        end = date.today()
        start = end - timedelta(days=period_days)

        try:
            data = yf.download(
                ticker,
                start=start.isoformat(),
                end=end.isoformat(),
                progress=False,
                auto_adjust=True,
            )

            if data.empty:
                logger.warning(f"No data returned for {ticker}")
                return []

            records = []
            for idx, row in data.iterrows():
                close_val = row["Close"]
                # Handle multi-level columns from yfinance
                if hasattr(close_val, "iloc"):
                    close_val = close_val.iloc[0]
                records.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "value": round(float(close_val), 4),
                })
            return records

        except Exception as e:
            logger.warning(f"yfinance error for {ticker}: {e}")
            return []
