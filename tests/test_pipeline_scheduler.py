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
        assert body["seed"] == "idle"

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
        assert body["seed"] == "idle"


class TestInitialSeed:
    @pytest.mark.asyncio
    async def test_skips_seed_when_db_has_data(self):
        """_maybe_initial_seed must NOT run fetchers when tables already have rows."""
        mock_pool = _make_pool_mock()
        sched = PipelineScheduler()
        sched.pool = mock_pool

        fetcher = MagicMock()
        fetcher.run = AsyncMock(return_value=10)
        sched._registered_jobs = [(fetcher, "twse_mi_index")]

        with patch("pipeline.scheduler.is_empty", new_callable=AsyncMock, return_value=False) as mock_empty, \
             patch("pipeline.scheduler.log_pipeline_run", new_callable=AsyncMock) as mock_log:
            await sched._maybe_initial_seed()

        mock_empty.assert_awaited()  # at least one check
        fetcher.run.assert_not_awaited()
        mock_log.assert_not_awaited()
        assert sched._seed_status == "skipped"

    @pytest.mark.asyncio
    async def test_runs_seed_when_db_empty(self):
        """When all seed-check tables are empty, every registered fetcher runs once."""
        mock_pool = _make_pool_mock()
        sched = PipelineScheduler()
        sched.pool = mock_pool

        f1 = MagicMock(); f1.run = AsyncMock(return_value=5)
        f2 = MagicMock(); f2.run = AsyncMock(return_value=8)
        sched._registered_jobs = [(f1, "twse_mi_index"), (f2, "fx_rates")]

        with patch("pipeline.scheduler.is_empty", new_callable=AsyncMock, return_value=True), \
             patch("pipeline.scheduler.log_pipeline_run", new_callable=AsyncMock) as mock_log:
            await sched._maybe_initial_seed()

        f1.run.assert_awaited_once_with(mock_pool)
        f2.run.assert_awaited_once_with(mock_pool)
        assert sched._seed_status == "completed"
        # Two log entries: running marker + final success
        assert mock_log.await_count == 2

    @pytest.mark.asyncio
    async def test_seed_continues_on_fetcher_error(self):
        """One failing fetcher should not abort the rest of the seed."""
        mock_pool = _make_pool_mock()
        sched = PipelineScheduler()
        sched.pool = mock_pool

        good = MagicMock(); good.run = AsyncMock(return_value=3)
        bad = MagicMock(); bad.run = AsyncMock(side_effect=ConnectionError("API down"))
        sched._registered_jobs = [(bad, "broken"), (good, "ok_fetcher")]

        with patch("pipeline.scheduler.is_empty", new_callable=AsyncMock, return_value=True), \
             patch("pipeline.scheduler.log_pipeline_run", new_callable=AsyncMock) as mock_log:
            await sched._maybe_initial_seed()

        good.run.assert_awaited_once()
        bad.run.assert_awaited_once()
        assert sched._seed_status == "completed"
        # Final log call should record partial status
        final_call_kwargs = mock_log.await_args_list[-1].kwargs
        assert final_call_kwargs["status"] == "partial"

    @pytest.mark.asyncio
    async def test_is_db_empty_short_circuits(self):
        """_is_db_empty returns False as soon as one table has rows."""
        mock_pool = _make_pool_mock()
        sched = PipelineScheduler()
        sched.pool = mock_pool

        # First table empty, second non-empty -> overall not empty
        with patch("pipeline.scheduler.is_empty", new_callable=AsyncMock, side_effect=[True, False]):
            result = await sched._is_db_empty()
        assert result is False
