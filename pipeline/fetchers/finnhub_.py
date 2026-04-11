"""Finnhub fund fetcher — offshore fund holdings, profiles, sectors, and countries.

Uses Finnhub API to fetch mutual fund data not covered by SITCA.
Free tier: 60 calls/min. Each fund = up to 4 calls → 1 call/sec with 5s batch intervals.

Endpoints:
  - /mutual-fund/profile    → fund_info
  - /mutual-fund/holdings   → fund_holding
  - /mutual-fund/sector     → Brinson sector weights
  - /mutual-fund/country    → region dimension (future)
"""

import asyncio
import logging

import aiohttp
import pandas as pd

from pipeline._dates import coerce_date
from pipeline.config import PipelineConfig
from pipeline.fetchers.base import BaseFetcher
from pipeline.fetchers.fund_isin_registry import get_all_isins, lookup_name

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"

# Rate limit: 60 calls/min → 1 call/sec, 5s between funds
_CALL_DELAY = 1.0
_BATCH_DELAY = 5.0


class FinnhubFundFetcher(BaseFetcher):
    """Fetch offshore fund data from Finnhub API.

    Fetches holdings + sector data for all funds in the ISIN registry.
    Writes to fund_holding (holdings) and fund_info (profiles).
    """

    source_name = "finnhub"
    default_schedule = "0 6 * * 6"
    target_table = "fund_holding"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.api_key = self.config.finnhub_api_key
        if not self.api_key:
            logger.warning("FINNHUB_API_KEY not set — fetcher will skip")

    async def fetch(self, params: dict) -> list[dict]:
        """Fetch holdings + sector for all registered funds.

        Args:
            params: {"fund_ids": [...]} — optional ISIN list override.
                    If not provided, uses all ISINs from fund_isin_registry.
        """
        if not self.api_key:
            logger.warning("Skipping Finnhub fetch: no API key")
            return []

        fund_ids = params.get("fund_ids") or get_all_isins()
        logger.info("Fetching %d funds from Finnhub", len(fund_ids))

        results = []
        async with aiohttp.ClientSession() as session:
            for i, isin in enumerate(fund_ids):
                try:
                    fund_data = await self._fetch_fund(session, isin)
                    results.extend(fund_data)
                except Exception:
                    logger.exception("Failed to fetch fund %s", isin)

                if (i + 1) % 10 == 0:
                    logger.info("Progress: %d/%d funds", i + 1, len(fund_ids))
                    await asyncio.sleep(_BATCH_DELAY)

        logger.info("Fetched %d total records from Finnhub", len(results))
        return results

    async def _fetch_fund(self, session: aiohttp.ClientSession, isin: str) -> list[dict]:
        """Fetch all data for a single fund (holdings + sector)."""
        records = []

        # 1. Holdings
        holdings = await self._api_get(session, "/mutual-fund/holdings", {"isin": isin})
        if holdings:
            as_of = coerce_date(holdings.get("atDate") or None)
            for h in holdings.get("holdings", []):
                if not h.get("name"):
                    continue
                records.append({
                    "fund_id": isin,
                    "as_of_date": as_of,
                    "stock_id": h.get("isin", ""),
                    "stock_name": h.get("name", ""),
                    "weight": h.get("percent", 0) / 100 if h.get("percent") else 0,
                    "asset_type": h.get("assetType", "equity"),
                    "sector": h.get("sector", ""),
                    "source": "finnhub",
                    "_record_type": "holding",
                })

        # 2. Sector exposure
        sector_data = await self._api_get(session, "/mutual-fund/sector", {"isin": isin})
        if sector_data:
            as_of = coerce_date(sector_data.get("atDate") or None)
            for s in sector_data.get("sectorExposure", []):
                records.append({
                    "fund_id": isin,
                    "as_of_date": as_of,
                    "stock_id": None,
                    "stock_name": s.get("sector", ""),
                    "weight": s.get("exposure", 0) / 100 if s.get("exposure") else 0,
                    "asset_type": "sector_aggregate",
                    "sector": s.get("sector", ""),
                    "source": "finnhub_sector",
                    "_record_type": "sector",
                })

        return records

    async def _api_get(self, session: aiohttp.ClientSession, path: str, params: dict) -> dict | None:
        """Make a GET request to Finnhub API with rate limiting."""
        await asyncio.sleep(_CALL_DELAY)
        url = f"{FINNHUB_BASE}{path}"
        params["token"] = self.api_key

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 429:
                    logger.warning("Finnhub rate limited — sleeping 30s")
                    await asyncio.sleep(30)
                    return None
                resp.raise_for_status()
                return await resp.json()
        except Exception:
            logger.exception("Finnhub API error: %s %s", path, params.get("isin", ""))
            return None

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize to fund_holding schema, applying sector name mapping."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)

        # Apply Finnhub sector → unified industry mapping
        from pipeline.transformers.industry_mapper import map_industry
        df["sector"] = df["sector"].apply(
            lambda x: map_industry(str(x), source="finnhub") or x if pd.notna(x) else x
        )

        # Drop internal _record_type column
        if "_record_type" in df.columns:
            df = df.drop(columns=["_record_type"])

        # Ensure schema columns
        schema_cols = ["fund_id", "as_of_date", "stock_id", "stock_name",
                       "weight", "asset_type", "sector", "source"]
        for col in schema_cols:
            if col not in df.columns:
                df[col] = None

        return df[schema_cols]


# Keep backward compat alias
FinnhubFetcher = FinnhubFundFetcher
