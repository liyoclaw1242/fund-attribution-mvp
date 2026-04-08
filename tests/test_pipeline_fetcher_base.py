"""Tests for pipeline.fetchers.base — BaseFetcher ABC."""

from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from pipeline.fetchers.base import BaseFetcher


def _make_pool_with_conn(mock_conn):
    """Create a mock pool whose acquire() yields mock_conn as async context manager."""
    mock_pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    return mock_pool


class DummyFetcher(BaseFetcher):
    """Concrete implementation for testing."""

    source_name = "dummy"
    default_schedule = "0 * * * *"
    target_table = "stock_info"

    def __init__(self, data: list[dict] | None = None):
        self._data = [{"stock_id": "2330", "stock_name": "TSMC"}] if data is None else data

    async def fetch(self, params: dict) -> list[dict]:
        return self._data

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(raw)


class FailingFetcher(BaseFetcher):
    """Fetcher that raises on fetch()."""

    source_name = "failing"
    default_schedule = "0 0 * * *"
    target_table = "stock_info"

    async def fetch(self, params: dict) -> list[dict]:
        raise ConnectionError("API down")

    def transform(self, raw: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(raw)


class TestBaseFetcherABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            BaseFetcher()

    def test_concrete_subclass(self):
        f = DummyFetcher()
        assert f.source_name == "dummy"
        assert f.default_schedule == "0 * * * *"


class TestBaseFetcherRun:
    @pytest.mark.asyncio
    async def test_run_fetches_transforms_loads(self):
        fetcher = DummyFetcher(data=[{"stock_id": "2330", "stock_name": "TSMC"}])

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.copy_records_to_table = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})

        mock_pool = _make_pool_with_conn(mock_conn)

        count = await fetcher.run(mock_pool, {})
        assert count == 1

    @pytest.mark.asyncio
    async def test_run_empty_data(self):
        fetcher = DummyFetcher(data=[])

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})

        mock_pool = _make_pool_with_conn(mock_conn)

        count = await fetcher.run(mock_pool, {})
        assert count == 0

    @pytest.mark.asyncio
    async def test_run_logs_failure(self):
        fetcher = FailingFetcher()

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"id": 1})

        mock_pool = _make_pool_with_conn(mock_conn)

        with pytest.raises(ConnectionError, match="API down"):
            await fetcher.run(mock_pool, {})

        # Verify _log_run was called (inserts into pipeline_run)
        mock_conn.fetchrow.assert_awaited()
        sql_arg = mock_conn.fetchrow.call_args[0][0]
        assert "INSERT INTO pipeline_run" in sql_arg


class TestBaseFetcherLoad:
    @pytest.mark.asyncio
    async def test_load_uses_temp_table(self):
        fetcher = DummyFetcher()
        df = pd.DataFrame({"stock_id": ["2330"], "stock_name": ["TSMC"]})

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.copy_records_to_table = AsyncMock()

        mock_pool = _make_pool_with_conn(mock_conn)

        count = await fetcher._load(mock_pool, df)
        assert count == 1

        # Verify temp table was created
        create_call = mock_conn.execute.call_args_list[0][0][0]
        assert "CREATE TEMP TABLE" in create_call
        assert "_tmp_stock_info" in create_call

        # Verify copy was called
        mock_conn.copy_records_to_table.assert_awaited_once()

        # Verify insert with ON CONFLICT
        insert_call = mock_conn.execute.call_args_list[1][0][0]
        assert "ON CONFLICT DO NOTHING" in insert_call

    @pytest.mark.asyncio
    async def test_load_empty_df_returns_zero(self):
        fetcher = DummyFetcher()
        df = pd.DataFrame()

        mock_pool = MagicMock()
        count = await fetcher._load(mock_pool, df)
        assert count == 0
