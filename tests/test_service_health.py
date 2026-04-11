"""Tests for service health endpoint and app creation."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app
from service.routers.health import FRESHNESS_DATE_COLUMNS, FRESHNESS_WINDOW_DAYS, _is_fresh


def _fresh_engine_mock(latest_dates: dict[str, date], pipeline_last_run=None):
    """Build an engine mock whose connect() yields a context-manager conn.

    Each call to conn.execute(text(...)) returns a result whose .first()
    yields the next queued row. Order matches the health endpoint:
        1. SELECT 1                            -> (1,)
        2. SELECT MAX(finished_at) ...         -> (pipeline_last_run,)
        3. SELECT MAX(<col>) FROM stock_price  -> (latest_dates['stock_price'],)
        4. SELECT MAX(<col>) FROM industry_index
        5. SELECT MAX(<col>) FROM fx_rate
        6. SELECT MAX(<col>) FROM fund_holding
    """
    queue: list[tuple] = [
        (1,),
        (pipeline_last_run,),
    ]
    for table in FRESHNESS_DATE_COLUMNS:
        queue.append((latest_dates.get(table),))

    async def fake_execute(*_args, **_kwargs):
        row = queue.pop(0) if queue else (None,)
        result = MagicMock()
        result.first.return_value = row
        return result

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=fake_execute)

    mock_engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect.return_value = cm
    return mock_engine


class TestIsFresh:
    def test_none_is_not_fresh(self):
        assert _is_fresh("stock_price", None, today=date(2026, 4, 11)) is False

    def test_within_window_is_fresh(self):
        today = date(2026, 4, 11)
        latest = today - timedelta(days=FRESHNESS_WINDOW_DAYS["stock_price"])
        assert _is_fresh("stock_price", latest, today=today) is True

    def test_outside_window_is_stale(self):
        today = date(2026, 4, 11)
        latest = today - timedelta(days=FRESHNESS_WINDOW_DAYS["stock_price"] + 1)
        assert _is_fresh("stock_price", latest, today=today) is False

    def test_fund_holding_uses_longer_window(self):
        today = date(2026, 4, 11)
        latest = today - timedelta(days=30)
        # Within 35 day window
        assert _is_fresh("fund_holding", latest, today=today) is True


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200_when_db_unavailable(self):
        """Health endpoint responds even with no engine initialized."""
        app = create_app()

        with patch("service.routers.health.get_engine", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] == "disconnected"
        assert "version" in body
        assert "checks" in body
        assert "data_freshness" in body["checks"]

    @pytest.mark.asyncio
    async def test_health_healthy_when_all_fresh(self):
        """status=healthy when DB connected AND all data within window."""
        today = date.today()
        latest_dates = {
            "stock_price": today,
            "industry_index": today,
            "fx_rate": today,
            "fund_holding": today,
        }
        engine = _fresh_engine_mock(latest_dates, pipeline_last_run=None)

        app = create_app()
        with patch("service.routers.health.get_engine", return_value=engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "healthy"
        assert body["db"] == "connected"
        for table in FRESHNESS_DATE_COLUMNS:
            assert body["checks"]["data_freshness"][table]["fresh"] is True

    @pytest.mark.asyncio
    async def test_health_degraded_when_data_stale(self):
        """status=degraded when DB is connected but a table is stale."""
        today = date.today()
        latest_dates = {
            "stock_price": today,
            "industry_index": today,
            "fx_rate": today,
            "fund_holding": today - timedelta(days=60),  # past 35-day window
        }
        engine = _fresh_engine_mock(latest_dates)

        app = create_app()
        with patch("service.routers.health.get_engine", return_value=engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "degraded"
        assert body["db"] == "connected"
        assert body["checks"]["data_freshness"]["fund_holding"]["fresh"] is False
        assert body["checks"]["data_freshness"]["stock_price"]["fresh"] is True

    @pytest.mark.asyncio
    async def test_health_degraded_when_table_empty(self):
        """Empty tables (no rows) should be reported as not fresh."""
        today = date.today()
        latest_dates = {
            "stock_price": today,
            "industry_index": today,
            "fx_rate": None,  # empty
            "fund_holding": today,
        }
        engine = _fresh_engine_mock(latest_dates)

        app = create_app()
        with patch("service.routers.health.get_engine", return_value=engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert body["status"] == "degraded"
        assert body["checks"]["data_freshness"]["fx_rate"]["latest"] is None
        assert body["checks"]["data_freshness"]["fx_rate"]["fresh"] is False

    @pytest.mark.asyncio
    async def test_health_db_query_failure(self):
        """When the connection itself raises, db=disconnected."""
        mock_engine = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = cm

        app = create_app()
        with patch("service.routers.health.get_engine", return_value=mock_engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert body["status"] == "degraded"
        assert body["db"] == "disconnected"


class TestAppCreation:
    def test_app_has_cors(self):
        app = create_app()
        middleware_classes = [m.cls.__name__ for m in app.user_middleware]
        assert "CORSMiddleware" in middleware_classes

    def test_app_includes_health_router(self):
        app = create_app()
        routes = [r.path for r in app.routes]
        assert "/api/health" in routes


class TestSchemas:
    def test_pagination_params(self):
        from service.schemas.common import PaginationParams
        p = PaginationParams(page=2, page_size=10)
        assert p.offset == 10

    def test_pagination_params_defaults(self):
        from service.schemas.common import PaginationParams
        p = PaginationParams()
        assert p.page == 1
        assert p.page_size == 20
        assert p.offset == 0

    def test_error_response(self):
        from service.schemas.common import ErrorResponse
        e = ErrorResponse(error="not_found", message="Resource not found")
        assert e.error == "not_found"
        assert e.details == []
