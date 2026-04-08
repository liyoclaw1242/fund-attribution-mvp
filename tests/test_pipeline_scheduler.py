"""Tests for pipeline.scheduler — APScheduler orchestration + health endpoint."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.scheduler import (
    SCHEDULE_REGISTRY,
    PipelineScheduler,
    _parse_cron,
    _try_import_fetcher,
)


class TestParseCron:
    def test_five_fields(self):
        result = _parse_cron("*/30 9-14 * * 1-5")
        assert result == {
            "minute": "*/30",
            "hour": "9-14",
            "day": "*",
            "month": "*",
            "day_of_week": "1-5",
        }

    def test_simple_cron(self):
        result = _parse_cron("0 16 * * 1-5")
        assert result["minute"] == "0"
        assert result["hour"] == "16"

    def test_monthly_cron(self):
        result = _parse_cron("0 9 20 * *")
        assert result["day"] == "20"


class TestTryImportFetcher:
    def test_existing_module(self):
        cls = _try_import_fetcher("pipeline.config", "PipelineConfig")
        assert cls is not None
        from pipeline.config import PipelineConfig
        assert cls is PipelineConfig

    def test_missing_module(self):
        cls = _try_import_fetcher("pipeline.fetchers.nonexistent", "Foo")
        assert cls is None

    def test_missing_class(self):
        cls = _try_import_fetcher("pipeline.config", "NonExistentClass")
        assert cls is None


class TestScheduleRegistry:
    def test_registry_has_all_entries(self):
        """Registry should have all 9 scheduled fetchers."""
        assert len(SCHEDULE_REGISTRY) == 9

    def test_registry_entries_have_required_keys(self):
        for entry in SCHEDULE_REGISTRY:
            assert "name" in entry
            assert "cron" in entry
            assert "module" in entry
            assert "class" in entry

    def test_all_crons_are_parseable(self):
        for entry in SCHEDULE_REGISTRY:
            result = _parse_cron(entry["cron"])
            assert len(result) == 5


def _make_pool_mock():
    """Create a mock pool whose acquire() yields a mock conn."""
    mock_conn = AsyncMock()
    mock_pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    mock_pool.close = AsyncMock()
    return mock_pool


class TestPipelineScheduler:
    @pytest.mark.asyncio
    async def test_start_initializes_pool_and_schema(self):
        """start() creates pool and runs schema migration."""
        mock_pool = _make_pool_mock()

        with patch("pipeline.scheduler.create_pool", new_callable=AsyncMock, return_value=mock_pool) as mock_create, \
             patch("pipeline.scheduler.execute_schema", new_callable=AsyncMock) as mock_schema, \
             patch("pipeline.scheduler._try_import_fetcher", return_value=None):

            sched = PipelineScheduler()
            # Patch health server to avoid binding port
            sched._start_health_server = AsyncMock()

            await sched.start()

            mock_create.assert_awaited_once()
            mock_schema.assert_awaited_once_with(mock_pool)

            await sched.stop()

    @pytest.mark.asyncio
    async def test_start_registers_available_fetchers(self):
        """start() registers only fetchers whose modules can be imported."""
        mock_pool = _make_pool_mock()

        # Simulate only 2 fetchers being importable
        call_count = 0
        def fake_import(module, cls):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                mock_fetcher_cls = MagicMock()
                mock_fetcher_cls.return_value = MagicMock()
                return mock_fetcher_cls
            return None

        with patch("pipeline.scheduler.create_pool", new_callable=AsyncMock, return_value=mock_pool), \
             patch("pipeline.scheduler.execute_schema", new_callable=AsyncMock), \
             patch("pipeline.scheduler._try_import_fetcher", side_effect=fake_import):

            sched = PipelineScheduler()
            sched._start_health_server = AsyncMock()

            await sched.start()

            assert len(sched._registered_fetchers) == 2

            await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_pool(self):
        """stop() closes the connection pool."""
        mock_pool = _make_pool_mock()

        with patch("pipeline.scheduler.create_pool", new_callable=AsyncMock, return_value=mock_pool), \
             patch("pipeline.scheduler.execute_schema", new_callable=AsyncMock), \
             patch("pipeline.scheduler._try_import_fetcher", return_value=None):

            sched = PipelineScheduler()
            sched._start_health_server = AsyncMock()

            await sched.start()
            await sched.stop()

            mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_run_fetcher_isolates_errors(self):
        """_run_fetcher catches exceptions — scheduler continues."""
        mock_pool = _make_pool_mock()

        sched = PipelineScheduler()
        sched.pool = mock_pool

        # Fetcher that raises
        failing_fetcher = MagicMock()
        failing_fetcher.run = AsyncMock(side_effect=ConnectionError("API down"))

        # Should not raise — error is isolated
        await sched._run_fetcher(failing_fetcher, "test_fetcher")

        # last_run_time should still be set
        assert sched._last_run_time is not None

    @pytest.mark.asyncio
    async def test_run_fetcher_success_updates_last_run(self):
        """_run_fetcher updates last_run_time on success."""
        mock_pool = _make_pool_mock()

        sched = PipelineScheduler()
        sched.pool = mock_pool

        fetcher = MagicMock()
        fetcher.run = AsyncMock(return_value=42)

        await sched._run_fetcher(fetcher, "test_fetcher")

        assert sched._last_run_time is not None
        fetcher.run.assert_awaited_once_with(mock_pool)


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_handler_returns_ok(self):
        """Health handler returns JSON with status ok."""
        sched = PipelineScheduler()
        sched._registered_fetchers = ["twse_mi_index", "fx_rates"]
        sched._last_run_time = "2026-04-08T10:00:00+00:00"

        request = MagicMock()
        response = await sched._health_handler(request)

        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["fetchers"] == 2
        assert body["registered"] == ["twse_mi_index", "fx_rates"]
        assert body["last_run"] == "2026-04-08T10:00:00+00:00"
        assert "h" in body["uptime"]

    @pytest.mark.asyncio
    async def test_health_handler_no_runs_yet(self):
        """Health handler works before any fetcher has run."""
        sched = PipelineScheduler()
        sched._registered_fetchers = []
        sched._last_run_time = None

        request = MagicMock()
        response = await sched._health_handler(request)

        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["fetchers"] == 0
        assert body["last_run"] is None
