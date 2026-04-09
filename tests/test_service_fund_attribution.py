"""Tests for fund lookup, search, and attribution API endpoints."""

import sqlite3
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app
from service.services.fund_service import detect_identifier_type


# --- Identifier detection ---

class TestIdentifierDetection:
    def test_tw_etf(self):
        assert detect_identifier_type("0050") == "tw_etf"
        assert detect_identifier_type("2330") == "tw_etf"

    def test_isin(self):
        assert detect_identifier_type("LU0117844026") == "offshore_fund"
        assert detect_identifier_type("IE00B11XZ541") == "offshore_fund"

    def test_us_stock(self):
        assert detect_identifier_type("AAPL") == "us_stock"
        assert detect_identifier_type("MSFT") == "us_stock"

    def test_unknown(self):
        assert detect_identifier_type("something weird 123") == "unknown"


# --- Fund endpoints ---

@pytest.fixture
def test_db(tmp_path):
    """Create a test SQLite DB with fund data."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE fund_holdings (
            fund_code TEXT NOT NULL,
            period TEXT NOT NULL,
            industry TEXT NOT NULL,
            weight REAL NOT NULL,
            return_rate REAL,
            source TEXT DEFAULT 'sitca',
            fetched_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT DEFAULT (datetime('now', '+1 day')),
            PRIMARY KEY (fund_code, period, industry)
        )
    """)
    conn.execute("""
        CREATE TABLE benchmark_index (
            index_name TEXT NOT NULL,
            period TEXT NOT NULL,
            industry TEXT NOT NULL,
            weight REAL NOT NULL,
            return_rate REAL NOT NULL,
            fetched_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT DEFAULT (datetime('now', '+1 day')),
            PRIMARY KEY (index_name, period, industry)
        )
    """)

    # Seed fund data (weights sum to 1.0)
    conn.executemany(
        "INSERT INTO fund_holdings (fund_code, period, industry, weight, return_rate) VALUES (?, ?, ?, ?, ?)",
        [
            ("0050", "latest", "半導體業", 0.50, 0.12),
            ("0050", "latest", "金融保險業", 0.30, 0.05),
            ("0050", "latest", "電子零組件業", 0.20, 0.08),
        ],
    )

    # Seed benchmark (weights sum to 1.0)
    conn.executemany(
        "INSERT INTO benchmark_index (index_name, period, industry, weight, return_rate) VALUES (?, ?, ?, ?, ?)",
        [
            ("MI_INDEX", "latest", "半導體業", 0.50, 0.10),
            ("MI_INDEX", "latest", "金融保險業", 0.30, 0.04),
            ("MI_INDEX", "latest", "電子零組件業", 0.20, 0.06),
        ],
    )

    conn.commit()
    conn.close()

    with patch("service.services.fund_service._DB_PATH", db_path):
        yield db_path


class TestFundEndpoints:
    @pytest.mark.asyncio
    async def test_get_fund(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/0050")
        assert resp.status_code == 200
        body = resp.json()
        assert body["fund_id"] == "0050"
        assert len(body["holdings"]) == 3

    @pytest.mark.asyncio
    async def test_get_fund_not_found(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_search_funds(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=0050")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_offshore(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=摩根")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_empty_query(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=")
        assert resp.status_code == 422  # min_length=1


class TestAttributionEndpoint:
    @pytest.mark.asyncio
    async def test_attribution_success(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "0050", "shares": 100}],
                "mode": "BF2",
            })
        assert resp.status_code == 200
        body = resp.json()
        assert "fund_return" in body
        assert "excess_return" in body
        assert body["brinson_mode"] == "BF2"
        assert len(body["detail"]) > 0

    @pytest.mark.asyncio
    async def test_attribution_bf3(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "0050"}],
                "mode": "BF3",
            })
        assert resp.status_code == 200
        assert resp.json()["brinson_mode"] == "BF3"

    @pytest.mark.asyncio
    async def test_attribution_unknown_fund(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "NONEXIST_9999"}],
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_attribution_invalid_mode(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "0050"}],
                "mode": "INVALID",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_attribution_empty_holdings(self, test_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [],
            })
        assert resp.status_code == 422
