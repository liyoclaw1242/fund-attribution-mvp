"""Tests for fund lookup, search, and attribution API endpoints.

The service layer now talks to Postgres via async SQLAlchemy. These
tests replace `service.services.fund_service.get_engine` with a fake
engine driven by a queue of canned rows — no real DB required.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from service.main import create_app
from service.services.fund_service import detect_identifier_type


# --- Identifier detection ---------------------------------------------------

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


# --- Fake engine helper -----------------------------------------------------

class _FakeResult:
    """Minimal stand-in for a SQLAlchemy Result object."""

    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


def _fake_engine(response_queue):
    """Build a mock async engine whose connect().execute() pops from a queue.

    Each queue entry is a list (possibly empty) of row tuples. The order of
    entries must match the order of SQL statements the code under test runs.
    """

    async def fake_execute(*_args, **_kwargs):
        rows = response_queue.pop(0) if response_queue else []
        return _FakeResult(rows)

    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(side_effect=fake_execute)

    mock_engine = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_engine.connect.return_value = cm
    return mock_engine


@pytest.fixture
def canned_fund_db():
    """Patch fund_service.get_engine with a scripted fake engine.

    Yields a `dict` with a `queue` list the test can populate before each
    HTTP call to stage responses for the expected SQL statements.
    """
    state = {"queue": []}
    engine = _fake_engine(state["queue"])
    with patch("service.services.fund_service.get_engine", return_value=engine):
        yield state


# --- Fund endpoints ---------------------------------------------------------


class TestFundEndpoints:
    @pytest.mark.asyncio
    async def test_get_fund_returns_aggregated_industries(self, canned_fund_db):
        # 1st call: fund_info lookup; 2nd: holdings aggregated by sector.
        canned_fund_db["queue"].extend([
            [("0050", "Yuanta 0050", "tw_etf", "TWD", "tw", "pipeline")],
            [
                ("Semiconductor", 0.55, date(2026, 3, 31)),
                ("Finance", 0.25, date(2026, 3, 31)),
                ("Electronic Components", 0.20, date(2026, 3, 31)),
            ],
        ])
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/0050")

        assert resp.status_code == 200
        body = resp.json()
        assert body["fund_id"] == "0050"
        assert body["fund_name"] == "Yuanta 0050"
        assert len(body["holdings"]) == 3
        assert body["holdings"][0]["stock_name"] == "Semiconductor"
        assert body["as_of_date"] == "2026-03-31"

    @pytest.mark.asyncio
    async def test_get_fund_not_found_returns_404(self, canned_fund_db):
        # fund_info lookup empty; identifier does not match ISIN pattern so
        # the registry fallback is skipped.
        canned_fund_db["queue"].extend([[]])

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/9999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_search_funds_by_fund_id(self, canned_fund_db):
        canned_fund_db["queue"].extend([[
            ("0050", "Yuanta 0050", "tw_etf", "TWD", "tw", "pipeline"),
        ]])

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=0050")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert body["results"][0]["fund_id"] == "0050"

    @pytest.mark.asyncio
    async def test_search_falls_back_to_isin_registry(self, canned_fund_db):
        # No postgres match — the registry fallback should still turn up a
        # Chinese offshore-fund result keyed on "摩根".
        canned_fund_db["queue"].extend([[]])

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=摩根")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @pytest.mark.asyncio
    async def test_search_empty_query_rejected(self, canned_fund_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/api/fund/search?q=")
        assert resp.status_code == 422  # min_length=1


# --- Attribution endpoint ---------------------------------------------------


class TestAttributionEndpoint:
    @pytest.mark.asyncio
    async def test_attribution_success(self, canned_fund_db):
        # Order: fund_info, holdings (per-fund), benchmark.
        canned_fund_db["queue"].extend([
            [("0050", "Yuanta 0050", "tw_etf", "TWD", "tw", "pipeline")],
            [
                ("Semiconductor", 0.55, date(2026, 3, 31)),
                ("Finance", 0.25, date(2026, 3, 31)),
                ("Electronic Components", 0.20, date(2026, 3, 31)),
            ],
            [
                ("Semiconductor", 0.40, 0.065),
                ("Finance", 0.30, 0.028),
                ("Electronic Components", 0.20, 0.041),
                ("Plastics", 0.10, -0.008),
            ],
        ])

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
    async def test_attribution_bf3(self, canned_fund_db):
        canned_fund_db["queue"].extend([
            [("0050", "Yuanta 0050", "tw_etf", "TWD", "tw", "pipeline")],
            [
                ("Semiconductor", 0.55, date(2026, 3, 31)),
                ("Finance", 0.25, date(2026, 3, 31)),
                ("Electronic Components", 0.20, date(2026, 3, 31)),
            ],
            [
                ("Semiconductor", 0.40, 0.065),
                ("Finance", 0.30, 0.028),
                ("Electronic Components", 0.20, 0.041),
                ("Plastics", 0.10, -0.008),
            ],
        ])

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "0050"}],
                "mode": "BF3",
            })
        assert resp.status_code == 200
        assert resp.json()["brinson_mode"] == "BF3"

    @pytest.mark.asyncio
    async def test_attribution_unknown_fund(self, canned_fund_db):
        # fund_info empty — identifier looks like US stock so no ISIN fallback
        # fires. `run_attribution` then raises ValueError → 422.
        canned_fund_db["queue"].extend([[]])

        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "NONEXIST_9999"}],
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_attribution_invalid_mode(self, canned_fund_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [{"identifier": "0050"}],
                "mode": "INVALID",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_attribution_empty_holdings(self, canned_fund_db):
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post("/api/attribution", json={
                "holdings": [],
            })
        assert resp.status_code == 422
