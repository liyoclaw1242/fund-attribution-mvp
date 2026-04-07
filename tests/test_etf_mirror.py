"""Tests for engine/etf_mirror.py — 0050 ETF benchmark mirror."""

import sqlite3

import pytest

from engine.etf_mirror import (
    compare_vs_0050,
    compare_vs_0050_direct,
    _get_etf_return,
    _template_explanation,
    _template_rebalance,
)
from interfaces import ETFMirrorResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite DB with full schema."""
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


def _seed_winning_scenario(conn):
    """Client beats 0050: client 8% vs benchmark avg ~5%."""
    conn.execute("INSERT INTO clients VALUES ('W001', 'Winner')")

    # Client holds one fund with good returns
    conn.execute(
        "INSERT INTO client_portfolios VALUES ('W001', 'FUND_A', '', 0, 1000000)"
    )
    # Fund A: 60% semi (12%), 40% finance (2%) → return = 0.6*0.12 + 0.4*0.02 = 0.08
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_A", "半導體業", 0.6, 0.12),
            ("FUND_A", "金融保險業", 0.4, 0.02),
        ],
    )
    # Benchmark: avg return = (0.06 + 0.04) / 2 = 0.05
    conn.executemany(
        "INSERT INTO benchmark_index VALUES ('MI_INDEX', 'latest', ?, 0.5, ?, datetime('now'), '2099-01-01')",
        [
            ("半導體業", 0.06),
            ("金融保險業", 0.04),
        ],
    )
    conn.commit()


def _seed_losing_scenario(conn):
    """Client loses to 0050: client 2% vs benchmark avg ~6%."""
    conn.execute("INSERT INTO clients VALUES ('L001', 'Loser')")

    conn.execute(
        "INSERT INTO client_portfolios VALUES ('L001', 'FUND_B', '', 0, 1000000)"
    )
    # Fund B: 50% semi (-2%), 50% finance (6%) → return = 0.5*(-0.02) + 0.5*0.06 = 0.02
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_B", "半導體業", 0.5, -0.02),
            ("FUND_B", "金融保險業", 0.5, 0.06),
        ],
    )
    # Benchmark: avg = (0.08 + 0.04) / 2 = 0.06
    conn.executemany(
        "INSERT INTO benchmark_index VALUES ('MI_INDEX', 'latest', ?, 0.5, ?, datetime('now'), '2099-01-01')",
        [
            ("半導體業", 0.08),
            ("金融保險業", 0.04),
        ],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Winning scenario
# ---------------------------------------------------------------------------

class TestWinningScenario:
    def test_is_winning(self, db_conn):
        _seed_winning_scenario(db_conn)
        result = compare_vs_0050("W001", db_conn, generate_ai=False)

        assert isinstance(result, ETFMirrorResult)
        assert result.is_winning is True
        assert result.diff > 0

    def test_client_return_correct(self, db_conn):
        _seed_winning_scenario(db_conn)
        result = compare_vs_0050("W001", db_conn, generate_ai=False)

        # 0.6*0.12 + 0.4*0.02 = 0.08
        assert result.client_return == pytest.approx(0.08)

    def test_etf_return_correct(self, db_conn):
        _seed_winning_scenario(db_conn)
        result = compare_vs_0050("W001", db_conn, generate_ai=False)

        # avg(0.06, 0.04) = 0.05
        assert result.etf_return == pytest.approx(0.05)

    def test_no_brinson_when_winning(self, db_conn):
        """When winning, no Brinson explanation needed."""
        _seed_winning_scenario(db_conn)
        result = compare_vs_0050("W001", db_conn, generate_ai=False)

        assert result.brinson_explanation == ""
        assert result.rebalance_suggestion == ""


# ---------------------------------------------------------------------------
# Losing scenario
# ---------------------------------------------------------------------------

class TestLosingScenario:
    def test_is_losing(self, db_conn):
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=False)

        assert result.is_winning is False
        assert result.diff < 0

    def test_client_return_correct(self, db_conn):
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=False)

        # 0.5*(-0.02) + 0.5*0.06 = 0.02
        assert result.client_return == pytest.approx(0.02)

    def test_etf_return_correct(self, db_conn):
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=False)

        # avg(0.08, 0.04) = 0.06
        assert result.etf_return == pytest.approx(0.06)

    def test_has_brinson_explanation(self, db_conn):
        """When losing, Brinson explanation is provided."""
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=False)

        assert result.brinson_explanation != ""
        assert "產業配置效果" in result.brinson_explanation or "落後" in result.brinson_explanation

    def test_diff_is_negative(self, db_conn):
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=False)

        assert result.diff == pytest.approx(0.02 - 0.06)


# ---------------------------------------------------------------------------
# Direct data API (no DB)
# ---------------------------------------------------------------------------

class TestDirectAPI:
    def test_winning_direct(self):
        client = [
            {"industry": "半導體業", "weight": 0.6, "return_rate": 0.12},
            {"industry": "金融保險業", "weight": 0.4, "return_rate": 0.05},
        ]
        bench = [
            {"industry": "半導體業", "weight": 0.5, "return_rate": 0.06},
            {"industry": "金融保險業", "weight": 0.5, "return_rate": 0.04},
        ]
        result = compare_vs_0050_direct(client, bench, generate_ai=False)

        assert result.is_winning is True
        # 0.6*0.12 + 0.4*0.05 = 0.092
        assert result.client_return == pytest.approx(0.092)

    def test_losing_direct(self):
        client = [
            {"industry": "半導體業", "weight": 0.3, "return_rate": 0.01},
            {"industry": "金融保險業", "weight": 0.7, "return_rate": 0.02},
        ]
        bench = [
            {"industry": "半導體業", "weight": 0.5, "return_rate": 0.08},
            {"industry": "金融保險業", "weight": 0.5, "return_rate": 0.04},
        ]
        result = compare_vs_0050_direct(client, bench, generate_ai=False)

        assert result.is_winning is False
        assert result.brinson_explanation != ""


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_no_portfolio(self, db_conn):
        """Raise if client has no holdings."""
        db_conn.execute("INSERT INTO clients VALUES ('EMPTY', 'Empty')")
        db_conn.commit()
        with pytest.raises(ValueError, match="No portfolio found"):
            compare_vs_0050("EMPTY", db_conn, generate_ai=False)

    def test_no_benchmark_data(self, db_conn):
        """Raise if no MI_INDEX data available."""
        db_conn.execute("INSERT INTO clients VALUES ('C001', 'Test')")
        db_conn.execute(
            "INSERT INTO client_portfolios VALUES ('C001', 'FUND_A', '', 0, 1000000)"
        )
        db_conn.executemany(
            "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
            [("FUND_A", "半導體業", 1.0, 0.05)],
        )
        db_conn.commit()

        with pytest.raises(ValueError, match="No MI_INDEX"):
            compare_vs_0050("C001", db_conn, generate_ai=False)

    def test_nonexistent_client(self, db_conn):
        with pytest.raises(ValueError, match="No portfolio"):
            compare_vs_0050("GHOST", db_conn, generate_ai=False)


# ---------------------------------------------------------------------------
# Template fallbacks
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_template_explanation(self):
        text = _template_explanation(0.02, 0.06)
        assert "2.00%" in text
        assert "6.00%" in text
        assert "4.00%" in text

    def test_template_rebalance(self):
        text = _template_rebalance(0.02, 0.06)
        assert "0050" in text
        assert "4.00%" in text


# ---------------------------------------------------------------------------
# AI suggestion (template fallback)
# ---------------------------------------------------------------------------

class TestAISuggestion:
    def test_no_ai_when_winning(self, db_conn):
        _seed_winning_scenario(db_conn)
        result = compare_vs_0050("W001", db_conn, generate_ai=True, api_key="")
        assert result.rebalance_suggestion == ""

    def test_template_when_no_key(self, db_conn):
        _seed_losing_scenario(db_conn)
        result = compare_vs_0050("L001", db_conn, generate_ai=True, api_key="")
        assert "0050" in result.rebalance_suggestion
