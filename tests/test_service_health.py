"""Tests for service health endpoint and app creation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_200(self):
        """Health endpoint responds even without DB."""
        app = create_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in ("ok", "degraded")
        assert "version" in body
        assert "db" in body

    @pytest.mark.asyncio
    async def test_health_db_connected(self):
        """When engine exists and query succeeds, db=connected."""
        app = create_app()

        # Mock a working engine
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_engine = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=mock_conn)
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = cm

        with patch("service.routers.health.get_engine", return_value=mock_engine):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/health")

        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] == "connected"

    @pytest.mark.asyncio
    async def test_health_db_disconnected(self):
        """When engine query fails, db=disconnected."""
        app = create_app()

        mock_engine = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        cm.__aexit__ = AsyncMock(return_value=False)
        mock_engine.connect.return_value = cm

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
