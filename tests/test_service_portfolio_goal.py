"""Tests for portfolio and goal API endpoints."""

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app

# Use a temp DB for tests
_TEST_DB = None


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path):
    """Create a fresh test database for each test."""
    global _TEST_DB
    db_path = str(tmp_path / "test.db")
    _TEST_DB = db_path

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Create tables
    conn.execute("""
        CREATE TABLE clients (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kyc_risk_level TEXT DEFAULT 'moderate',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE client_portfolios (
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            bank_name TEXT DEFAULT '',
            shares REAL NOT NULL DEFAULT 0,
            cost_basis REAL NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (client_id, fund_code, bank_name)
        )
    """)
    conn.execute("""
        CREATE TABLE client_goals (
            goal_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            goal_type TEXT NOT NULL DEFAULT 'retirement',
            target_amount REAL NOT NULL,
            target_year INTEGER NOT NULL,
            monthly_contribution REAL NOT NULL DEFAULT 0,
            risk_tolerance TEXT NOT NULL DEFAULT 'moderate',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)

    # Seed a test client
    conn.execute(
        "INSERT INTO clients (client_id, name) VALUES ('C001', '王大明')"
    )
    conn.commit()
    conn.close()

    with patch("service.services.portfolio_service._DB_PATH", db_path):
        yield

    _TEST_DB = None


def _get_app():
    return create_app()


# --- Portfolio endpoints ---

class TestPortfolioAPI:
    @pytest.mark.asyncio
    async def test_list_portfolios(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    @pytest.mark.asyncio
    async def test_create_holding(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
    async def test_create_holding_client_not_found(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/portfolio", json={
                "client_id": "NONEXIST",
                "fund_code": "0050",
                "shares": 10,
                "cost_basis": 10000,
            })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_portfolio(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Create a holding first
            await c.post("/api/portfolio", json={
                "client_id": "C001", "fund_code": "0050",
                "shares": 50, "cost_basis": 75000,
            })
            resp = await c.get("/api/portfolio/C001")
        assert resp.status_code == 200
        body = resp.json()
        assert body["client_id"] == "C001"
        assert body["total_holdings"] >= 1

    @pytest.mark.asyncio
    async def test_get_portfolio_not_found(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/portfolio/NONEXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_holding(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/portfolio", json={
                "client_id": "C001", "fund_code": "0056",
                "shares": 10, "cost_basis": 5000,
            })
            resp = await c.delete("/api/portfolio/C001/0056?bank_name=")
        assert resp.status_code == 204


# --- Goal endpoints ---

class TestGoalAPI:
    @pytest.mark.asyncio
    async def test_create_goal(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
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
        assert body["goal_id"]

    @pytest.mark.asyncio
    async def test_list_goals(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/api/goal", json={
                "client_id": "C001", "target_amount": 5000000,
                "target_year": 2035, "monthly_contribution": 20000,
            })
            resp = await c.get("/api/goal/C001")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_list_goals_client_not_found(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/goal/NONEXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_goal(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            create_resp = await c.post("/api/goal", json={
                "client_id": "C001", "target_amount": 5000000,
                "target_year": 2035, "monthly_contribution": 20000,
            })
            goal_id = create_resp.json()["goal_id"]
            resp = await c.put(f"/api/goal/{goal_id}", json={
                "target_amount": 8000000,
            })
        assert resp.status_code == 200
        assert resp.json()["target_amount"] == 8000000

    @pytest.mark.asyncio
    async def test_delete_goal(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            create_resp = await c.post("/api/goal", json={
                "client_id": "C001", "target_amount": 3000000,
                "target_year": 2030, "monthly_contribution": 10000,
            })
            goal_id = create_resp.json()["goal_id"]
            resp = await c.delete(f"/api/goal/{goal_id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_simulate_goal(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            create_resp = await c.post("/api/goal", json={
                "client_id": "C001", "target_amount": 10000000,
                "target_year": 2040, "monthly_contribution": 30000,
                "risk_tolerance": "moderate",
            })
            goal_id = create_resp.json()["goal_id"]
            resp = await c.get(f"/api/goal/{goal_id}/simulate")
        assert resp.status_code == 200
        body = resp.json()
        assert 0 <= body["success_probability"] <= 1
        assert body["median_outcome"] > 0
        assert body["years_to_goal"] > 0

    @pytest.mark.asyncio
    async def test_simulate_goal_not_found(self, setup_test_db):
        app = _get_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/goal/NONEXIST/simulate")
        assert resp.status_code == 404
