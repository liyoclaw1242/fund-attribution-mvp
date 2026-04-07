"""Tests for engine/crisis_response.py — crisis response engine."""

import sqlite3

import pytest

from engine.crisis_response import (
    check_crisis_trigger,
    generate_crisis_response,
    CRISIS_THRESHOLD,
    HISTORICAL_CRASHES,
    _template_talking_point,
    _template_general_talking_points,
    _scan_affected_clients,
)
from interfaces import CrisisClient, CrisisReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite DB with schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE client_portfolios (
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            bank_name TEXT DEFAULT '',
            shares REAL NOT NULL DEFAULT 0,
            cost_basis REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (client_id, fund_code, bank_name)
        );
        CREATE TABLE fund_holdings (
            fund_code TEXT NOT NULL,
            period TEXT NOT NULL,
            industry TEXT NOT NULL,
            weight REAL NOT NULL,
            return_rate REAL,
            source TEXT DEFAULT 'sitca',
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL DEFAULT '2099-01-01',
            PRIMARY KEY (fund_code, period, industry)
        );
        CREATE TABLE benchmark_index (
            index_name TEXT NOT NULL,
            period TEXT NOT NULL,
            industry TEXT NOT NULL,
            weight REAL NOT NULL,
            return_rate REAL NOT NULL,
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL DEFAULT '2099-01-01',
            PRIMARY KEY (index_name, period, industry)
        );
    """)
    return conn


def _seed_crash_market() -> list[dict]:
    """Market data with >3% drop."""
    return [
        {"industry": "半導體", "return_rate": -0.06},
        {"industry": "金融保險", "return_rate": -0.04},
        {"industry": "電子工業", "return_rate": -0.05},
        {"industry": "鋼鐵", "return_rate": -0.02},
        {"industry": "食品", "return_rate": 0.01},
    ]


def _seed_normal_market() -> list[dict]:
    """Market data with small move."""
    return [
        {"industry": "半導體", "return_rate": 0.005},
        {"industry": "金融保險", "return_rate": -0.01},
        {"industry": "電子工業", "return_rate": 0.008},
    ]


def _seed_clients_with_exposure(conn):
    """Seed clients with portfolios exposed to crash sectors."""
    conn.execute("INSERT INTO clients VALUES ('C001', '王小明')")
    conn.execute("INSERT INTO clients VALUES ('C002', '林小華')")
    conn.execute("INSERT INTO clients VALUES ('C003', '陳小美')")

    # C001: heavily in semiconductors (high exposure)
    conn.execute(
        "INSERT INTO client_portfolios VALUES ('C001', 'FUND_A', '', 0, 2000000)"
    )
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_A", "半導體", 0.7, -0.06),
            ("FUND_A", "食品", 0.3, 0.01),
        ],
    )

    # C002: balanced (moderate exposure)
    conn.execute(
        "INSERT INTO client_portfolios VALUES ('C002', 'FUND_B', '', 0, 1000000)"
    )
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_B", "金融保險", 0.5, -0.04),
            ("FUND_B", "食品", 0.5, 0.01),
        ],
    )

    # C003: safe sectors only (no exposure to dropped sectors that are in market_data)
    conn.execute(
        "INSERT INTO client_portfolios VALUES ('C003', 'FUND_C', '', 0, 500000)"
    )
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_C", "食品", 1.0, 0.01),
        ],
    )

    conn.commit()


# ---------------------------------------------------------------------------
# Crisis trigger tests
# ---------------------------------------------------------------------------

class TestCrisisTrigger:
    def test_crash_triggers(self):
        market = _seed_crash_market()
        is_crisis, drop, dropped = check_crisis_trigger(market_data=market)

        assert is_crisis is True
        assert drop < -CRISIS_THRESHOLD

    def test_normal_does_not_trigger(self):
        market = _seed_normal_market()
        is_crisis, drop, dropped = check_crisis_trigger(market_data=market)

        assert is_crisis is False

    def test_empty_market_data(self):
        is_crisis, drop, dropped = check_crisis_trigger(market_data=[])

        assert is_crisis is False
        assert drop == 0.0
        assert dropped == []

    def test_dropped_sectors_sorted(self):
        market = _seed_crash_market()
        _, _, dropped = check_crisis_trigger(market_data=market)

        # Should be sorted by return_rate ascending (worst first)
        returns = [s["return_rate"] for s in dropped]
        assert returns == sorted(returns)

    def test_custom_threshold(self):
        # With a very low threshold, even small drops trigger
        market = [{"industry": "test", "return_rate": -0.015}]
        is_crisis, _, _ = check_crisis_trigger(market_data=market, threshold=0.01)
        assert is_crisis is True

    def test_borderline_no_trigger(self):
        # Exactly at threshold should not trigger (needs to exceed)
        market = [{"industry": "test", "return_rate": -0.03}]
        is_crisis, _, _ = check_crisis_trigger(market_data=market, threshold=0.03)
        assert is_crisis is False

    def test_borderline_trigger(self):
        # Just past threshold
        market = [{"industry": "test", "return_rate": -0.031}]
        is_crisis, _, _ = check_crisis_trigger(market_data=market, threshold=0.03)
        assert is_crisis is True


# ---------------------------------------------------------------------------
# Affected clients scan
# ---------------------------------------------------------------------------

class TestAffectedClients:
    def test_identifies_exposed_clients(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        dropped = [
            {"industry": "半導體", "return_rate": -0.06},
            {"industry": "金融保險", "return_rate": -0.04},
        ]
        affected = _scan_affected_clients(db_conn, dropped)

        # C001 and C002 have exposure, C003 does not
        client_ids = [c.client_id for c in affected]
        assert "C001" in client_ids
        assert "C002" in client_ids
        assert "C003" not in client_ids

    def test_sorted_by_exposure(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        dropped = [
            {"industry": "半導體", "return_rate": -0.06},
            {"industry": "金融保險", "return_rate": -0.04},
        ]
        affected = _scan_affected_clients(db_conn, dropped)

        # C001 (70% semi) should be first, C002 (50% finance) second
        assert affected[0].client_id == "C001"
        assert affected[0].exposure_pct > affected[1].exposure_pct

    def test_estimated_loss_positive(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        dropped = [
            {"industry": "半導體", "return_rate": -0.06},
            {"industry": "金融保險", "return_rate": -0.04},
        ]
        affected = _scan_affected_clients(db_conn, dropped)

        for client in affected:
            assert client.estimated_loss > 0

    def test_c001_loss_calculation(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        dropped = [
            {"industry": "半導體", "return_rate": -0.06},
        ]
        affected = _scan_affected_clients(db_conn, dropped)

        c001 = next(c for c in affected if c.client_id == "C001")
        # FUND_A cost_basis=2M, semi weight=0.7, drop=6%
        # Loss = 2M * 0.7 * 0.06 = 84,000
        assert c001.estimated_loss == pytest.approx(84000.0)

    def test_no_clients_returns_empty(self, db_conn):
        dropped = [{"industry": "半導體", "return_rate": -0.06}]
        affected = _scan_affected_clients(db_conn, dropped)
        assert affected == []


# ---------------------------------------------------------------------------
# Full crisis response
# ---------------------------------------------------------------------------

class TestGenerateCrisisResponse:
    def test_full_response(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        market = _seed_crash_market()

        report = generate_crisis_response(
            db_conn, market_data=market, generate_ai=False
        )

        assert isinstance(report, CrisisReport)
        assert report.market_drop_pct < 0
        assert len(report.affected_clients) >= 2
        assert len(report.historical_comparisons) == 3
        assert report.talking_points != ""

    def test_no_crisis_raises(self, db_conn):
        market = _seed_normal_market()
        with pytest.raises(ValueError, match="No crisis detected"):
            generate_crisis_response(db_conn, market_data=market, generate_ai=False)

    def test_clients_have_talking_points(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        market = _seed_crash_market()

        report = generate_crisis_response(
            db_conn, market_data=market, generate_ai=False
        )

        for client in report.affected_clients:
            assert client.talking_point != ""
            assert client.name in client.talking_point


# ---------------------------------------------------------------------------
# Historical comparisons
# ---------------------------------------------------------------------------

class TestHistoricalComparisons:
    def test_has_three_crashes(self):
        assert len(HISTORICAL_CRASHES) == 3

    def test_each_has_required_fields(self):
        for crash in HISTORICAL_CRASHES:
            assert "event" in crash
            assert "date" in crash
            assert "drop" in crash
            assert "recovery_months" in crash
            assert "description" in crash


# ---------------------------------------------------------------------------
# Template fallbacks
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_client_talking_point(self):
        client = CrisisClient(
            client_id="T001",
            name="測試客戶",
            exposure_pct=0.65,
            estimated_loss=130000,
            talking_point="",
        )
        text = _template_talking_point(client, -0.035)

        assert "測試客戶" in text
        assert "3.50%" in text
        assert "65.00%" in text
        assert "NT$130,000" in text

    def test_general_talking_points(self):
        text = _template_general_talking_points(-0.042, 15)

        assert "4.20%" in text
        assert "15" in text
        assert "2008" in text
        assert "2020" in text
        assert "2022" in text

    def test_ai_fallback_when_no_key(self, db_conn):
        _seed_clients_with_exposure(db_conn)
        market = _seed_crash_market()

        report = generate_crisis_response(
            db_conn, market_data=market, generate_ai=True, api_key=""
        )

        # Should still produce results using templates
        assert report.talking_points != ""
        for client in report.affected_clients:
            assert client.talking_point != ""
