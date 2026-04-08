"""Tests for pipeline.db — pool creation, schema execution, pipeline_run logging."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.db import SCHEMA_PATH, create_pool, close_pool, execute_schema, log_pipeline_run


def _make_pool_with_conn(mock_conn):
    """Create a mock pool whose acquire() yields mock_conn as async context manager."""
    mock_pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    return mock_pool


class TestSchemaPath:
    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"schema.sql not found at {SCHEMA_PATH}"

    def test_schema_is_idempotent(self):
        sql = SCHEMA_PATH.read_text()
        for line in sql.splitlines():
            stripped = line.strip().upper()
            if stripped.startswith("CREATE TABLE") and "PARTITION OF" not in stripped:
                assert "IF NOT EXISTS" in stripped, (
                    f"Non-idempotent CREATE TABLE: {line.strip()}"
                )
            elif stripped.startswith("CREATE INDEX"):
                assert "IF NOT EXISTS" in stripped, (
                    f"Non-idempotent CREATE INDEX: {line.strip()}"
                )

    def test_schema_has_all_tables(self):
        sql = SCHEMA_PATH.read_text().lower()
        required = [
            "stock_info", "stock_price", "industry_index", "industry_weight",
            "fund_info", "fund_holding", "fund_nav", "fx_rate", "pipeline_run",
        ]
        for table in required:
            assert f"create table if not exists {table}" in sql, (
                f"Missing table: {table}"
            )


class TestCreatePool:
    @pytest.mark.asyncio
    async def test_create_pool_calls_asyncpg(self):
        mock_pool = AsyncMock()
        with patch("pipeline.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create:
            pool = await create_pool("postgresql://test@localhost/db")
            mock_create.assert_awaited_once_with(
                "postgresql://test@localhost/db", min_size=2, max_size=10,
            )
            assert pool is mock_pool

    @pytest.mark.asyncio
    async def test_create_pool_custom_kwargs(self):
        mock_pool = AsyncMock()
        with patch("pipeline.db.asyncpg.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create:
            await create_pool("postgresql://x@y/z", min_size=1, max_size=5)
            mock_create.assert_awaited_once_with(
                "postgresql://x@y/z", min_size=1, max_size=5,
            )


class TestClosePool:
    @pytest.mark.asyncio
    async def test_close_pool(self):
        mock_pool = AsyncMock()
        await close_pool(mock_pool)
        mock_pool.close.assert_awaited_once()


class TestExecuteSchema:
    @pytest.mark.asyncio
    async def test_execute_schema_reads_and_runs_sql(self):
        mock_conn = AsyncMock()
        mock_pool = _make_pool_with_conn(mock_conn)

        await execute_schema(mock_pool)

        mock_conn.execute.assert_awaited_once()
        sql_arg = mock_conn.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS stock_info" in sql_arg


class TestLogPipelineRun:
    @pytest.mark.asyncio
    async def test_log_success(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 42})
        mock_pool = _make_pool_with_conn(mock_conn)

        result = await log_pipeline_run(mock_pool, "twse", "success", rows_count=100)

        assert result == 42
        mock_conn.fetchrow.assert_awaited_once()
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO pipeline_run" in sql_arg

    @pytest.mark.asyncio
    async def test_log_running_has_no_finished_at(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})
        mock_pool = _make_pool_with_conn(mock_conn)

        await log_pipeline_run(mock_pool, "finnhub", "running")

        call_args = mock_conn.fetchrow.call_args[0]
        # finished_at is the 3rd positional arg ($3)
        finished_at_arg = call_args[3]
        assert finished_at_arg is None

    @pytest.mark.asyncio
    async def test_log_failed_has_finished_at(self):
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 2})
        mock_pool = _make_pool_with_conn(mock_conn)

        await log_pipeline_run(
            mock_pool, "finnhub", "failed", error_msg="Connection refused"
        )

        call_args = mock_conn.fetchrow.call_args[0]
        finished_at_arg = call_args[3]
        assert finished_at_arg is not None
