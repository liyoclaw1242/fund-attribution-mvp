"""Tests for engine/health_check.py — cross-bank portfolio health check."""

import sqlite3

import pytest

from engine.health_check import (
    check_portfolio_health,
    check_portfolio_health_direct,
    classify_fund,
    CONCENTRATION_THRESHOLD,
)
from interfaces import HealthCheckResult, HealthIssue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            kyc_risk_level TEXT DEFAULT 'moderate'
        );
        CREATE TABLE client_portfolios (
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            bank_name TEXT DEFAULT '',
            shares REAL NOT NULL DEFAULT 0,
            cost_basis REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (client_id, fund_code, bank_name)
        );
    """)
    return conn


def _seed_diversified(conn):
    """Well-diversified multi-bank portfolio — no issues expected."""
    conn.execute("INSERT INTO clients VALUES ('D001', 'Diversified', 'moderate')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, ?, 0, ?)",
        [
            ("D001", "0050", "國泰世華", 300000),    # equity 30%
            ("D001", "0056", "中國信託", 200000),    # equity 20%
            ("D001", "00687B", "國泰世華", 300000),  # bond 30%
            ("D001", "00679B", "富邦", 200000),      # bond 20%
        ],
    )
    conn.commit()


def _seed_concentrated(conn):
    """Single fund > 40% — concentration warning."""
    conn.execute("INSERT INTO clients VALUES ('C001', 'Concentrated', 'moderate')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, ?, 0, ?)",
        [
            ("C001", "0050", "國泰世華", 800000),    # 80% in one fund
            ("C001", "00687B", "中國信託", 200000),   # 20%
        ],
    )
    conn.commit()


def _seed_equity_only(conn):
    """All equity, no bonds — missing asset class."""
    conn.execute("INSERT INTO clients VALUES ('E001', 'EquityOnly', 'moderate')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, ?, 0, ?)",
        [
            ("E001", "0050", "國泰世華", 500000),
            ("E001", "0056", "中國信託", 500000),
        ],
    )
    conn.commit()


def _seed_kyc_mismatch(conn):
    """Conservative KYC but aggressive portfolio."""
    conn.execute("INSERT INTO clients VALUES ('K001', 'KYCMismatch', 'conservative')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, ?, 0, ?)",
        [
            ("K001", "0050", "國泰世華", 700000),    # equity
            ("K001", "0056", "中國信託", 300000),     # equity
        ],
    )
    conn.commit()


def _seed_multi_bank(conn):
    """Same fund across multiple banks."""
    conn.execute("INSERT INTO clients VALUES ('M001', 'MultiBank', 'moderate')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, ?, 0, ?)",
        [
            ("M001", "0050", "國泰世華", 300000),
            ("M001", "0050", "中國信託", 200000),
            ("M001", "00687B", "富邦", 500000),
        ],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Cross-bank aggregation
# ---------------------------------------------------------------------------

class TestCrossBankAggregation:
    def test_bank_breakdown(self, db_conn):
        _seed_multi_bank(db_conn)
        result = check_portfolio_health("M001", db_conn)

        assert result.total_value == pytest.approx(1000000)
        assert "國泰世華" in result.bank_breakdown
        assert "中國信託" in result.bank_breakdown
        assert "富邦" in result.bank_breakdown
        assert result.bank_breakdown["國泰世華"] == pytest.approx(300000)
        assert result.bank_breakdown["中國信託"] == pytest.approx(200000)

    def test_same_fund_aggregated_for_concentration(self, db_conn):
        """Same fund across banks should be aggregated for concentration check."""
        _seed_multi_bank(db_conn)
        result = check_portfolio_health("M001", db_conn)

        # 0050: 300K + 200K = 500K / 1M = 50% → concentration warning
        # 00687B: 500K / 1M = 50% → also concentration warning
        conc_issues = [i for i in result.issues if i.check_type == "concentration"]
        assert len(conc_issues) == 2
        conc_funds = {i.description.split(" ")[1] for i in conc_issues}
        assert "0050" in conc_funds


# ---------------------------------------------------------------------------
# Concentration check
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_no_concentration_issue(self, db_conn):
        _seed_diversified(db_conn)
        result = check_portfolio_health("D001", db_conn)

        conc = [i for i in result.issues if i.check_type == "concentration"]
        assert len(conc) == 0

    def test_concentration_warning(self, db_conn):
        _seed_concentrated(db_conn)
        result = check_portfolio_health("C001", db_conn)

        conc = [i for i in result.issues if i.check_type == "concentration"]
        assert len(conc) == 1
        assert conc[0].severity == "warning"
        assert "80.0%" in conc[0].description
        assert "0050" in conc[0].description


# ---------------------------------------------------------------------------
# Asset class check
# ---------------------------------------------------------------------------

class TestAssetClass:
    def test_no_missing_classes(self, db_conn):
        _seed_diversified(db_conn)
        result = check_portfolio_health("D001", db_conn)

        ac = [i for i in result.issues if i.check_type == "asset_class"]
        assert len(ac) == 0

    def test_missing_bond(self, db_conn):
        _seed_equity_only(db_conn)
        result = check_portfolio_health("E001", db_conn)

        ac = [i for i in result.issues if i.check_type == "asset_class"]
        assert len(ac) == 1
        assert "債券型" in ac[0].description


# ---------------------------------------------------------------------------
# KYC mismatch
# ---------------------------------------------------------------------------

class TestKYCMismatch:
    def test_no_mismatch(self, db_conn):
        _seed_diversified(db_conn)
        result = check_portfolio_health("D001", db_conn)

        kyc = [i for i in result.issues if i.check_type == "kyc_mismatch"]
        assert len(kyc) == 0

    def test_aggressive_for_conservative_client(self, db_conn):
        _seed_kyc_mismatch(db_conn)
        result = check_portfolio_health("K001", db_conn)

        kyc = [i for i in result.issues if i.check_type == "kyc_mismatch"]
        assert len(kyc) == 1
        assert kyc[0].severity == "critical"
        assert "保守型" in kyc[0].description


# ---------------------------------------------------------------------------
# Direct API
# ---------------------------------------------------------------------------

class TestDirectAPI:
    def test_direct_health_check(self):
        holdings = [
            {"fund_code": "0050", "cost_basis": 800000, "bank_name": "國泰世華"},
            {"fund_code": "00687B", "cost_basis": 200000, "bank_name": "富邦"},
        ]
        result = check_portfolio_health_direct("C001", holdings)

        assert isinstance(result, HealthCheckResult)
        assert result.total_value == pytest.approx(1000000)
        # 0050 at 80% → concentration warning
        conc = [i for i in result.issues if i.check_type == "concentration"]
        assert len(conc) == 1


# ---------------------------------------------------------------------------
# Fund classification
# ---------------------------------------------------------------------------

class TestClassifyFund:
    def test_known_etf(self):
        assert classify_fund("0050") == "equity"
        assert classify_fund("00687B") == "bond"

    def test_bond_suffix(self):
        assert classify_fund("99999B") == "bond"

    def test_four_digit_numeric(self):
        assert classify_fund("2330") == "equity"

    def test_unknown_mutual_fund(self):
        assert classify_fund("NN1001") == "unknown"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_unknown_client(self, db_conn):
        with pytest.raises(ValueError, match="not found"):
            check_portfolio_health("GHOST", db_conn)

    def test_no_holdings(self, db_conn):
        db_conn.execute("INSERT INTO clients VALUES ('EMPTY', 'Empty', 'moderate')")
        db_conn.commit()
        with pytest.raises(ValueError, match="No holdings"):
            check_portfolio_health("EMPTY", db_conn)

    def test_empty_direct(self):
        with pytest.raises(ValueError, match="No holdings"):
            check_portfolio_health_direct("C001", [])


# ---------------------------------------------------------------------------
# Issue structure
# ---------------------------------------------------------------------------

class TestIssueStructure:
    def test_issue_has_chinese_text(self, db_conn):
        _seed_concentrated(db_conn)
        result = check_portfolio_health("C001", db_conn)

        for issue in result.issues:
            assert isinstance(issue, HealthIssue)
            assert len(issue.description) > 0
            assert len(issue.suggestion) > 0
            assert issue.check_type in ("concentration", "asset_class", "kyc_mismatch")
            assert issue.severity in ("warning", "critical")
