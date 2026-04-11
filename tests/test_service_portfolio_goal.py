"""Tests for portfolio and goal API endpoints.

The service layer now talks to Postgres via async SQLAlchemy. Rather
than spinning up a real DB in unit tests, each test patches the
`portfolio_service` functions with `AsyncMock`s that return canned
values. SQL correctness is exercised separately by the live Docker
smoke documented in the PR for #129.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app


@pytest.fixture
def fake_svc():
    """Patch every portfolio_service function used by the routers.

    Test bodies can set `fake_svc["<name>"].return_value = ...` (or
    `side_effect = ...`) to script the next call.
    """
    names = [
        "get_client",
        "create_client",
        "list_portfolios",
        "get_portfolio",
        "create_holding",
        "update_holding",
        "delete_holding",
        "list_goals",
        "get_goal",
        "create_goal",
        "update_goal",
        "delete_goal",
    ]
    patches = {name: patch(f"service.services.portfolio_service.{name}", new=AsyncMock()) for name in names}
    mocks = {name: p.start() for name, p in patches.items()}
    yield mocks
    for p in patches.values():
        p.stop()


def _app():
    return create_app()


# --- Portfolio endpoints ---------------------------------------------------


class TestPortfolioAPI:
    @pytest.mark.asyncio
    async def test_list_portfolios(self, fake_svc):
        fake_svc["list_portfolios"].return_value = [
            {"client_id": "C001", "name": "王大明", "holding_count": 2},
        ]
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["client_id"] == "C001"

    @pytest.mark.asyncio
    async def test_create_holding(self, fake_svc):
        fake_svc["get_client"].return_value = {
            "client_id": "C001",
            "name": "王大明",
            "kyc_risk_level": "moderate",
            "created_at": "2026-04-11T00:00:00+00:00",
        }
        fake_svc["create_holding"].return_value = {
            "client_id": "C001",
            "fund_code": "0050",
            "bank_name": "國泰",
            "shares": 100.0,
            "cost_basis": 150000.0,
            "added_at": "2026-04-11T00:00:00+00:00",
        }
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.post("/api/portfolio", json={
                "client_id": "C001",
                "fund_code": "0050",
                "bank_name": "國泰",
                "shares": 100,
                "cost_basis": 150000,
            })
        assert resp.status_code == 201
        body = resp.json()
        assert body["fund_code"] == "0050"
        assert body["shares"] == 100

    @pytest.mark.asyncio
    async def test_create_holding_client_not_found(self, fake_svc):
        fake_svc["get_client"].return_value = None
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.post("/api/portfolio", json={
                "client_id": "NONEXIST",
                "fund_code": "0050",
                "shares": 10,
                "cost_basis": 10000,
            })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_portfolio(self, fake_svc):
        fake_svc["get_client"].return_value = {
            "client_id": "C001", "name": "王大明",
            "kyc_risk_level": "moderate", "created_at": "2026-04-11T00:00:00+00:00",
        }
        fake_svc["get_portfolio"].return_value = [
            {
                "client_id": "C001", "fund_code": "0050", "bank_name": "",
                "shares": 50.0, "cost_basis": 75000.0,
                "added_at": "2026-04-11T00:00:00+00:00",
            },
        ]
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/C001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_id"] == "C001"
        assert body["total_holdings"] == 1

    @pytest.mark.asyncio
    async def test_get_portfolio_not_found(self, fake_svc):
        fake_svc["get_client"].return_value = None
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/NONEXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_holding(self, fake_svc):
        fake_svc["delete_holding"].return_value = True
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.delete("/api/portfolio/C001/0056?bank_name=")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_holding_not_found(self, fake_svc):
        fake_svc["delete_holding"].return_value = False
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.delete("/api/portfolio/C001/NOPE?bank_name=")
        assert resp.status_code == 404


# --- Goal endpoints --------------------------------------------------------


_CLIENT = {
    "client_id": "C001", "name": "王大明",
    "kyc_risk_level": "moderate", "created_at": "2026-04-11T00:00:00+00:00",
}

_GOAL = {
    "goal_id": "g0000001",
    "client_id": "C001",
    "goal_type": "retirement",
    "target_amount": 10000000.0,
    "target_year": 2040,
    "monthly_contribution": 30000.0,
    "risk_tolerance": "moderate",
    "created_at": "2026-04-11T00:00:00+00:00",
    "updated_at": "2026-04-11T00:00:00+00:00",
}


class TestGoalAPI:
    @pytest.mark.asyncio
    async def test_create_goal(self, fake_svc):
        fake_svc["get_client"].return_value = _CLIENT
        fake_svc["create_goal"].return_value = dict(_GOAL)
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.post("/api/goal", json={
                "client_id": "C001",
                "goal_type": "retirement",
                "target_amount": 10000000,
                "target_year": 2040,
                "monthly_contribution": 30000,
                "risk_tolerance": "moderate",
            })
        assert resp.status_code == 201
        body = resp.json()
        assert body["target_amount"] == 10000000
        assert body["goal_id"] == "g0000001"

    @pytest.mark.asyncio
    async def test_list_goals(self, fake_svc):
        fake_svc["get_client"].return_value = _CLIENT
        fake_svc["list_goals"].return_value = [dict(_GOAL)]
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/goal/C001")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    @pytest.mark.asyncio
    async def test_list_goals_client_not_found(self, fake_svc):
        fake_svc["get_client"].return_value = None
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/goal/NONEXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_goal(self, fake_svc):
        updated = dict(_GOAL)
        updated["target_amount"] = 8000000.0
        fake_svc["update_goal"].return_value = updated
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.put("/api/goal/g0000001", json={"target_amount": 8000000})
        assert resp.status_code == 200
        assert resp.json()["target_amount"] == 8000000

    @pytest.mark.asyncio
    async def test_update_goal_not_found(self, fake_svc):
        fake_svc["update_goal"].return_value = None
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.put("/api/goal/NOPE", json={"target_amount": 1})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_goal(self, fake_svc):
        fake_svc["delete_goal"].return_value = True
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.delete("/api/goal/g0000001")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_simulate_goal(self, fake_svc):
        fake_svc["get_goal"].return_value = dict(_GOAL)
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/goal/g0000001/simulate")
        assert resp.status_code == 200
        body = resp.json()
        assert 0 <= body["success_probability"] <= 1
        assert body["median_outcome"] > 0
        assert body["years_to_goal"] > 0

    @pytest.mark.asyncio
    async def test_simulate_goal_not_found(self, fake_svc):
        fake_svc["get_goal"].return_value = None
        async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://test") as c:
            resp = await c.get("/api/goal/NONEXIST/simulate")
        assert resp.status_code == 404
