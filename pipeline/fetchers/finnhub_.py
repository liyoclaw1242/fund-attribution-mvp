"""Finnhub fetcher — offshore fund holdings.

Uses Finnhub API to fetch mutual fund holdings not covered by SITCA.
Free tier: 60 calls/min.
"""

import asyncio
import logging

import aiohttp
import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

# Rate limit: 60 calls/min → ~1 call/sec
_RATE_LIMIT_DELAY = 1.0


class FinnhubFetcher(BaseFetcher):
    """Fetch offshore fund holdings from Finnhub API."""

    source_name = "finnhub"
    default_schedule = "0 6 * * 6"
    target_table = "fund_holding"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.api_key = self.config.finnhub_api_key
        if not self.api_key:
            logger.warning("FINNHUB_API_KEY not set — fetcher will skip")

    async def fetch(self, params: dict) -> list[dict]:
        """Fetch fund holdings from Finnhub.

        Args:
            params: {"fund_ids": ["US1234567890", ...]} — list of ISIN codes.
        """
        if not self.api_key:
            logger.warning("Skipping Finnhub fetch: no API key")
            return []

        fund_ids = params.get("fund_ids", [])
        if not fund_ids:
            logger.info("No fund_ids provided, skipping")
            return []

        results = []
        async with aiohttp.ClientSession() as session:
            for fund_id in fund_ids:
                try:
                    data = await self._fetch_holdings(session, fund_id)
                    results.extend(data)
                    await asyncio.sleep(_RATE_LIMIT_DELAY)
                except Exception:
                    logger.exception("Failed to fetch holdings for %s", fund_id)

        return results

    async def _fetch_holdings(
        self, session: aiohttp.ClientSession, fund_id: str
    ) -> list[dict]:
        """Fetch holdings for a single fund."""
        url = "https://finnhub.io/api/v1/mutual-fund/holdings"
        params = {"isin": fund_id, "token": self.api_key}

        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        holdings = data.get("holdings", [])
        as_of = data.get("atDate", "")

        return [
            {
                "fund_id": fund_id,
                "as_of_date": as_of,
                "stock_id": h.get("isin", ""),
                "stock_name": h.get("name", ""),
                "weight": h.get("percent", 0) / 100 if h.get("percent") else 0,
                "asset_type": h.get("assetType", "equity"),
                "sector": h.get("sector", ""),
                "source": "finnhub",
            }
            for h in holdings
            if h.get("name")
        ]

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize Finnhub holdings to fund_holding schema."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        # Ensure required columns
        for col in ("fund_id", "as_of_date", "stock_id", "stock_name", "weight",
                     "asset_type", "sector", "source"):
            if col not in df.columns:
                df[col] = None

        return df[["fund_id", "as_of_date", "stock_id", "stock_name",
                    "weight", "asset_type", "sector", "source"]]
