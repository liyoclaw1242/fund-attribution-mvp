"""BaseFetcher — abstract base class for all data pipeline fetchers."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import asyncpg
import pandas as pd


class BaseFetcher(ABC):
    """Abstract base class for pipeline data fetchers.

    Subclasses must define ``source_name``, ``default_schedule``,
    and implement ``fetch()`` and ``transform()``.  The ``run()``
    method orchestrates Fetch -> Transform -> Load and logs the
    result to ``pipeline_run``.
    """

    source_name: str          # e.g. "twse", "finnhub"
    default_schedule: str     # cron expression e.g. "0 16 * * 1-5"

    # Subclasses set the target table name for _load()
    target_table: str = ""

    @abstractmethod
    async def fetch(self, params: dict) -> list[dict]:
        """Fetch raw data from the external source.

        Returns a list of raw record dicts.
        """

    @abstractmethod
    def transform(self, raw: list[dict]) -> pd.DataFrame:
        """Clean and normalize raw data to the target table schema.

        Returns a DataFrame whose columns match the target table.
        """

    async def run(self, db_pool: asyncpg.Pool, params: dict | None = None) -> int:
        """Fetch -> Transform -> Load.  Returns row count."""
        if params is None:
            params = {}

        started_at = datetime.now(timezone.utc)
        try:
            raw = await self.fetch(params)
            df = self.transform(raw)
            count = await self._load(db_pool, df)
            await self._log_run(db_pool, count, started_at=started_at)
            return count
        except Exception as exc:
            await self._log_run(
                db_pool, 0, error_msg=str(exc), status="failed",
                started_at=started_at,
            )
            raise

    async def _load(self, pool: asyncpg.Pool, df: pd.DataFrame) -> int:
        """Bulk-insert a DataFrame into ``self.target_table``.

        Uses asyncpg ``copy_records_to_table`` for speed.
        Rows that violate unique constraints are skipped (ON CONFLICT DO NOTHING
        is not available via COPY, so we use a temp table approach).
        """
        if df.empty or not self.target_table:
            return 0

        columns = list(df.columns)
        records = [tuple(row) for row in df.itertuples(index=False, name=None)]

        async with pool.acquire() as conn:
            # Temp table -> COPY -> INSERT ... ON CONFLICT DO NOTHING
            tmp = f"_tmp_{self.target_table}"
            await conn.execute(
                f"CREATE TEMP TABLE {tmp} (LIKE {self.target_table} INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            await conn.copy_records_to_table(tmp, records=records, columns=columns)
            cols_csv = ", ".join(columns)
            result = await conn.execute(
                f"INSERT INTO {self.target_table} ({cols_csv}) "
                f"SELECT {cols_csv} FROM {tmp} "
                f"ON CONFLICT DO NOTHING"
            )
            # result is e.g. "INSERT 0 42"
            count = int(result.split()[-1])
            return count

    async def _log_run(
        self,
        pool: asyncpg.Pool,
        rows_count: int,
        error_msg: str | None = None,
        status: str = "success",
        started_at: datetime | None = None,
    ) -> int:
        """Log this run to pipeline_run table."""
        from pipeline.db import log_pipeline_run

        return await log_pipeline_run(
            pool,
            fetcher=self.source_name,
            status=status,
            rows_count=rows_count,
            error_msg=error_msg,
            started_at=started_at,
        )
