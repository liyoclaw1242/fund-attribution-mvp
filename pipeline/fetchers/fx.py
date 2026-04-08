"""FX rate fetcher — daily exchange rates for TWD conversion.

Primary: exchangerate.host (free, no API key).
Fallback: hardcoded recent rates for resilience.
"""

import logging
from datetime import date

import aiohttp
import pandas as pd

from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

DEFAULT_PAIRS = ["USDTWD", "HKDTWD", "CNYTWD", "SGDTWD", "EURTWD", "JPYTWD"]

# Fallback rates (approximate, updated periodically)
_FALLBACK_RATES = {
    "USDTWD": 32.0,
    "HKDTWD": 4.1,
    "CNYTWD": 4.4,
    "SGDTWD": 24.0,
    "EURTWD": 35.0,
    "JPYTWD": 0.21,
}


class FxRateFetcher(BaseFetcher):
    """Fetch daily FX rates."""

    source_name = "fx_rate"
    default_schedule = "0 9 * * 1-5"
    target_table = "fx_rate"

    def __init__(self, pairs: list[str] | None = None):
        self.pairs = pairs or DEFAULT_PAIRS

    async def fetch(self, params: dict) -> list[dict]:
        """Fetch latest FX rates.

        Args:
            params: {"date": "2026-04-08"} — optional, defaults to today.
        """
        target_date = params.get("date", date.today().isoformat())
        results = []

        for pair in self.pairs:
            rate = await self._fetch_rate(pair, target_date)
            if rate is not None:
                results.append({
                    "pair": pair,
                    "date": target_date,
                    "rate": rate,
                    "source": "exchangerate_host",
                })

        return results

    async def _fetch_rate(self, pair: str, target_date: str) -> float | None:
        """Fetch a single pair rate with fallback."""
        base = pair[:3]
        quote = pair[3:]

        try:
            rate = await self._fetch_from_api(base, quote, target_date)
            if rate:
                return rate
        except Exception:
            logger.exception("API fetch failed for %s", pair)

        # Fallback
        fallback = _FALLBACK_RATES.get(pair)
        if fallback:
            logger.warning("Using fallback rate for %s: %s", pair, fallback)
            return fallback

        return None

    async def _fetch_from_api(
        self, base: str, quote: str, target_date: str
    ) -> float | None:
        """Fetch from exchangerate.host API."""
        url = f"https://api.exchangerate.host/{target_date}"
        params = {"base": base, "symbols": quote}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        rates = data.get("rates", {})
        return rates.get(quote)

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize to fx_rate schema."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        return df[["pair", "date", "rate", "source"]]
