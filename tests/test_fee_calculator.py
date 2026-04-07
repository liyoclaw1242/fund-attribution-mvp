"""Tests for engine/fee_calculator.py — fee transparency calculator."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from engine.fee_calculator import (
    calculate_fees,
    calculate_fees_from_holdings,
    _load_fee_data,
    _suggest_alternatives,
)
from interfaces import FeeReport, FundFee, Alternative


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fees_json(tmp_path):
    """Create a minimal fund_fees.json for testing."""
    data = {
        "_description": "test",
        "funds": {
            "NN1001": {"name": "聯博全球高收益債券基金", "ter": 0.0175, "type": "mutual_fund"},
            "FL1001": {"name": "富蘭克林坦伯頓成長基金", "ter": 0.0185, "type": "mutual_fund"},
            "0050": {"name": "元大台灣50", "ter": 0.0043, "type": "etf"},
            "0056": {"name": "元大高股息", "ter": 0.0045, "type": "etf"},
        },
        "alternatives": [
            {
                "category": "台股大盤",
                "suggested_fund": "006208",
                "suggested_name": "富邦台50",
                "suggested_ter": 0.0035,
                "replaces_types": ["mutual_fund"],
                "description": "低成本替代",
            },
            {
                "category": "高股息",
                "suggested_fund": "0056",
                "suggested_name": "元大高股息",
                "suggested_ter": 0.0045,
                "replaces_types": ["mutual_fund"],
                "description": "高股息替代",
            },
            {
                "category": "全球債券",
                "suggested_fund": "00687B",
                "suggested_name": "國泰20年美債",
                "suggested_ter": 0.0020,
                "replaces_types": ["mutual_fund"],
                "description": "債券替代",
            },
        ],
    }
    path = tmp_path / "fund_fees.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


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
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (client_id, fund_code, bank_name)
        );
    """)
    return conn


def _seed_client(conn, client_id, name, holdings):
    """Insert a client and their holdings."""
    conn.execute("INSERT INTO clients (client_id, name) VALUES (?, ?)", (client_id, name))
    for h in holdings:
        conn.execute(
            "INSERT INTO client_portfolios (client_id, fund_code, cost_basis) VALUES (?, ?, ?)",
            (client_id, h["fund_code"], h["cost_basis"]),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Happy path — DB-based
# ---------------------------------------------------------------------------

class TestCalculateFees:
    def test_basic_two_funds(self, db_conn, fees_json):
        """Two mutual funds: correct weighted TER and annual fees."""
        _seed_client(db_conn, "C001", "Test Client", [
            {"fund_code": "NN1001", "cost_basis": 500000},
            {"fund_code": "FL1001", "cost_basis": 500000},
        ])
        report = calculate_fees("C001", db_conn, fees_path=fees_json)

        assert isinstance(report, FeeReport)
        assert report.client_id == "C001"
        assert len(report.fund_fees) == 2
        assert report.total_market_value == pytest.approx(1000000)

        # NN1001: 500000 * 0.0175 = 8750
        # FL1001: 500000 * 0.0185 = 9250
        assert report.total_annual_fee == pytest.approx(18000)

        # Weighted TER: 18000 / 1000000 = 0.018
        assert report.weighted_ter == pytest.approx(0.018)

    def test_mixed_etf_and_mutual_fund(self, db_conn, fees_json):
        """ETF + mutual fund: ETF has low TER, should lower weighted avg."""
        _seed_client(db_conn, "C002", "Mixed Client", [
            {"fund_code": "0050", "cost_basis": 700000},
            {"fund_code": "NN1001", "cost_basis": 300000},
        ])
        report = calculate_fees("C002", db_conn, fees_path=fees_json)

        assert len(report.fund_fees) == 2
        # 0050: 700000 * 0.0043 = 3010
        # NN1001: 300000 * 0.0175 = 5250
        expected_total_fee = 3010 + 5250
        assert report.total_annual_fee == pytest.approx(expected_total_fee)
        assert report.weighted_ter == pytest.approx(expected_total_fee / 1000000)

    def test_single_fund(self, db_conn, fees_json):
        """Single fund: weighted TER equals fund TER."""
        _seed_client(db_conn, "C003", "Single", [
            {"fund_code": "0050", "cost_basis": 1000000},
        ])
        report = calculate_fees("C003", db_conn, fees_path=fees_json)

        assert len(report.fund_fees) == 1
        assert report.weighted_ter == pytest.approx(0.0043)
        assert report.total_annual_fee == pytest.approx(4300)

    def test_fund_fee_details(self, db_conn, fees_json):
        """FundFee objects have correct fields."""
        _seed_client(db_conn, "C004", "Detail", [
            {"fund_code": "NN1001", "cost_basis": 200000},
        ])
        report = calculate_fees("C004", db_conn, fees_path=fees_json)

        ff = report.fund_fees[0]
        assert ff.fund_code == "NN1001"
        assert ff.fund_name == "聯博全球高收益債券基金"
        assert ff.ter == pytest.approx(0.0175)
        assert ff.market_value == pytest.approx(200000)
        assert ff.annual_fee == pytest.approx(3500)


# ---------------------------------------------------------------------------
# Happy path — holdings-based (no DB)
# ---------------------------------------------------------------------------

class TestCalculateFeesFromHoldings:
    def test_basic(self, fees_json):
        """Direct holdings input works without DB."""
        holdings = [
            {"fund_code": "NN1001", "cost_basis": 500000},
            {"fund_code": "FL1001", "cost_basis": 500000},
        ]
        report = calculate_fees_from_holdings("C001", holdings, fees_path=fees_json)

        assert report.client_id == "C001"
        assert report.total_annual_fee == pytest.approx(18000)

    def test_market_value_key(self, fees_json):
        """Accepts market_value key as alternative to cost_basis."""
        holdings = [
            {"fund_code": "NN1001", "market_value": 500000},
        ]
        report = calculate_fees_from_holdings("C001", holdings, fees_path=fees_json)
        assert report.total_annual_fee == pytest.approx(8750)


# ---------------------------------------------------------------------------
# Alternatives
# ---------------------------------------------------------------------------

class TestAlternatives:
    def test_mutual_fund_gets_alternatives(self, db_conn, fees_json):
        """Mutual funds with TER > 1% get alternative suggestions."""
        _seed_client(db_conn, "C005", "Alt Client", [
            {"fund_code": "NN1001", "cost_basis": 1000000},
        ])
        report = calculate_fees("C005", db_conn, fees_path=fees_json)

        assert len(report.alternatives) >= 3
        for alt in report.alternatives:
            assert alt.current_fund == "NN1001"
            assert alt.ter_savings > 0
            assert alt.annual_savings > 0

    def test_etf_no_alternatives(self, db_conn, fees_json):
        """ETFs (TER <= 1%) should not get alternative suggestions."""
        _seed_client(db_conn, "C006", "ETF Client", [
            {"fund_code": "0050", "cost_basis": 1000000},
        ])
        report = calculate_fees("C006", db_conn, fees_path=fees_json)

        assert len(report.alternatives) == 0

    def test_alternative_savings_calculation(self, db_conn, fees_json):
        """Annual savings calculated correctly."""
        _seed_client(db_conn, "C007", "Savings", [
            {"fund_code": "NN1001", "cost_basis": 1000000},
        ])
        report = calculate_fees("C007", db_conn, fees_path=fees_json)

        # NN1001 TER=0.0175, 006208 TER=0.0035 → savings=0.014
        alt_006208 = next(
            (a for a in report.alternatives if a.suggested_fund == "006208"), None
        )
        assert alt_006208 is not None
        assert alt_006208.ter_savings == pytest.approx(0.014)
        assert alt_006208.annual_savings == pytest.approx(14000)

    def test_alternatives_sorted_by_savings(self, db_conn, fees_json):
        """Alternatives sorted by annual savings descending."""
        _seed_client(db_conn, "C008", "Sorted", [
            {"fund_code": "NN1001", "cost_basis": 1000000},
        ])
        report = calculate_fees("C008", db_conn, fees_path=fees_json)

        for i in range(len(report.alternatives) - 1):
            assert report.alternatives[i].annual_savings >= report.alternatives[i + 1].annual_savings


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_no_holdings(self, db_conn, fees_json):
        """Raise ValueError for client with no holdings."""
        conn = db_conn
        conn.execute("INSERT INTO clients (client_id, name) VALUES ('EMPTY', 'Empty')")
        conn.commit()

        with pytest.raises(ValueError, match="No holdings found"):
            calculate_fees("EMPTY", conn, fees_path=fees_json)

    def test_unknown_client(self, db_conn, fees_json):
        """Raise ValueError for nonexistent client (no rows)."""
        with pytest.raises(ValueError, match="No holdings found"):
            calculate_fees("NONEXISTENT", db_conn, fees_path=fees_json)

    def test_all_funds_unknown(self, db_conn, fees_json):
        """Raise if all holdings have unknown fund codes."""
        _seed_client(db_conn, "C009", "Unknown Funds", [
            {"fund_code": "UNKNOWN1", "cost_basis": 100000},
            {"fund_code": "UNKNOWN2", "cost_basis": 200000},
        ])
        with pytest.raises(ValueError, match="none have TER data"):
            calculate_fees("C009", db_conn, fees_path=fees_json)

    def test_skip_unknown_fund_gracefully(self, db_conn, fees_json):
        """Unknown funds are skipped; known ones still calculated."""
        _seed_client(db_conn, "C010", "Partial", [
            {"fund_code": "NN1001", "cost_basis": 500000},
            {"fund_code": "UNKNOWN", "cost_basis": 500000},
        ])
        report = calculate_fees("C010", db_conn, fees_path=fees_json)

        assert len(report.fund_fees) == 1
        assert report.fund_fees[0].fund_code == "NN1001"
        # Market value only includes known funds
        assert report.total_market_value == pytest.approx(500000)

    def test_empty_holdings_list(self, fees_json):
        """Empty holdings list raises ValueError."""
        with pytest.raises(ValueError):
            calculate_fees_from_holdings("C001", [], fees_path=fees_json)


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

class TestReferenceData:
    def test_load_real_fees_json(self):
        """The actual data/fund_fees.json is valid and loadable."""
        data = _load_fee_data()
        assert "funds" in data
        assert "alternatives" in data
        assert len(data["funds"]) > 0
        assert len(data["alternatives"]) >= 3

    def test_all_ters_are_positive(self):
        """All TERs in reference data are positive decimals < 0.10."""
        data = _load_fee_data()
        for code, info in data["funds"].items():
            assert 0 < info["ter"] < 0.10, f"Fund {code} TER {info['ter']} out of range"
