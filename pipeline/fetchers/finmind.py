"""FinMind fetcher — Taiwan stock info with industry classification.

Uses FinMind API for TaiwanStockInfo (industry categories) as cross-reference
for TSE 28 industry mapping.
"""

import logging

import aiohttp
import pandas as pd

from pipeline.config import PipelineConfig
from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"


class FinMindStockInfoFetcher(BaseFetcher):
    """Fetch TaiwanStockInfo from FinMind — industry classification."""

    source_name = "finmind_stock_info"
    default_schedule = "0 2 * * 1"
    target_table = "stock_info"

    def __init__(self, config: PipelineConfig | None = None):
        self.config = config or PipelineConfig.from_env()
        self.token = self.config.finmind_api_token

    async def fetch(self, params: dict) -> list[dict]:
        """Fetch TaiwanStockInfo dataset from FinMind."""
        request_params = {
            "dataset": "TaiwanStockInfo",
        }
        if self.token:
            request_params["token"] = self.token

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    FINMIND_API,
                    params=request_params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except Exception:
            logger.exception("FinMind API request failed")
            return []

        records = data.get("data", [])
        if not records:
            msg = data.get("msg", "unknown")
            logger.warning("FinMind returned no data: %s", msg)

        return records

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize FinMind TaiwanStockInfo to stock_info schema."""
        if not raw:
            return pd.DataFrame()

        records = []
        for item in raw:
            stock_id = item.get("stock_id", "")
            if not stock_id:
                continue

            records.append({
                "stock_id": stock_id,
                "stock_name": item.get("stock_name", ""),
                "market": "twse" if item.get("type", "") == "twse" else "tpex",
                "industry": item.get("industry_category", ""),
                "industry_source": "finmind",
                "shares_outstanding": None,
            })

        return pd.DataFrame(records) if records else pd.DataFrame()
