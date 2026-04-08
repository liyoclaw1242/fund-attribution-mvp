"""PostgreSQL async connection pool and helpers."""

import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def create_pool(dsn: str, **kwargs) -> asyncpg.Pool:
    """Create an asyncpg connection pool.

    Args:
        dsn: PostgreSQL connection string.
        **kwargs: Extra args forwarded to asyncpg.create_pool
                  (min_size, max_size, etc.).
    """
    defaults = {"min_size": 2, "max_size": 10}
    defaults.update(kwargs)
    return await asyncpg.create_pool(dsn, **defaults)


async def close_pool(pool: asyncpg.Pool) -> None:
    """Gracefully close the connection pool."""
    await pool.close()


async def execute_schema(pool: asyncpg.Pool) -> None:
    """Run schema.sql against the database (idempotent)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def log_pipeline_run(
    pool: asyncpg.Pool,
    fetcher: str,
    status: str,
    rows_count: int = 0,
    error_msg: str | None = None,
    started_at: datetime | None = None,
    params_json: dict | None = None,
) -> int:
    """Insert a record into pipeline_run and return its id.

    Args:
        pool: asyncpg connection pool.
        fetcher: Name of the fetcher (e.g. 'twse', 'finnhub').
        status: Run status — 'success', 'failed', 'partial', 'running'.
        rows_count: Number of rows written.
        error_msg: Error message if status is 'failed'.
        started_at: When the run started (defaults to now).
        params_json: Optional parameters dict stored as JSONB.

    Returns:
        The id of the inserted pipeline_run record.
    """
    if started_at is None:
        started_at = datetime.now(timezone.utc)

    finished_at = None
    if status in ("success", "failed", "partial"):
        finished_at = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pipeline_run
                (fetcher, started_at, finished_at, status, rows_count, error_msg, params_json)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            RETURNING id
            """,
            fetcher,
            started_at,
            finished_at,
            status,
            rows_count,
            error_msg,
            __import__("json").dumps(params_json) if params_json else None,
        )
        return row["id"]
