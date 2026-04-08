"""Weight calculator — compute daily industry market cap weights.

Reads stock_price.market_cap + stock_info.industry, groups by industry,
and writes to industry_weight.
"""

import logging
from datetime import date

import asyncpg
import pandas as pd

from pipeline.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)


class WeightCalculator(BaseFetcher):
    """Calculate industry market cap weights for each market."""

    source_name = "weight_calculator"
    default_schedule = "0 17 * * 1-5"
    target_table = "industry_weight"

    async def fetch(self, params: dict) -> list[dict]:
        """Read stock_price + stock_info from DB to compute weights.

        This fetcher reads from the database rather than an external API.
        The db_pool is passed via params["_pool"] by the scheduler.
        """
        pool = params.get("_pool")
        if pool is None:
            raise ValueError("WeightCalculator requires '_pool' in params")

        target_date = params.get("date", date.today().isoformat())
        markets = params.get("markets", ["twse", "us"])

        results = []
        for market in markets:
            rows = await self._compute_weights(pool, market, target_date)
            results.extend(rows)

        return results

    async def _compute_weights(
        self, pool: asyncpg.Pool, market: str, target_date: str
    ) -> list[dict]:
        """Compute industry weights for a single market on a given date."""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT si.industry, SUM(sp.market_cap) AS total_cap
                FROM stock_price sp
                JOIN stock_info si ON sp.stock_id = si.stock_id
                WHERE si.market = $1
                  AND sp.date = $2
                  AND sp.market_cap IS NOT NULL
                  AND si.industry IS NOT NULL
                GROUP BY si.industry
                """,
                market,
                target_date,
            )

        if not rows:
            logger.warning("No market cap data for %s on %s", market, target_date)
            return []

        total_market_cap = sum(r["total_cap"] for r in rows)
        if total_market_cap == 0:
            return []

        return [
            {
                "industry": r["industry"],
                "date": target_date,
                "market": market,
                "weight": float(r["total_cap"]) / float(total_market_cap),
                "market_cap": int(r["total_cap"]),
            }
            for r in rows
        ]

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Normalize to industry_weight schema."""
        if not raw:
            return pd.DataFrame()

        df = pd.DataFrame(raw)
        return df[["industry", "date", "market", "weight", "market_cap"]]

    async def run(self, db_pool: asyncpg.Pool, params: dict | None = None) -> int:
        """Override run() to inject pool into params for fetch()."""
        if params is None:
            params = {}
        params["_pool"] = db_pool
        return await super().run(db_pool, params)
