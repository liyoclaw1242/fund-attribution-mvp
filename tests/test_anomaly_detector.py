"""Tests for engine/anomaly_detector.py — anomaly detection engine."""

import sqlite3

import pytest

from engine.anomaly_detector import (
    scan_all_clients,
    scan_client,
    get_alerts_for_client,
    acknowledge_alert,
    _check_concentration,
    _check_pe_percentile,
    _check_rsi_overbought,
    _check_fund_outflow,
    _check_foreign_selling,
    _check_style_drift,
)
from interfaces import AnomalyAlert, AnomalyConfig


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
            name TEXT NOT NULL
        );
        CREATE TABLE client_portfolios (
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            bank_name TEXT DEFAULT '',
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
        CREATE TABLE anomaly_alerts (
            alert_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            value REAL,
            threshold REAL,
            message TEXT,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            acknowledged_at TEXT
        );
    """)
    return conn


def _seed_basic(conn):
    """Two clients with different portfolios."""
    conn.execute("INSERT INTO clients VALUES ('C001', 'Client A')")
    conn.execute("INSERT INTO clients VALUES ('C002', 'Client B')")
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, '', ?)",
        [
            ("C001", "0050", 800000),  # 80% concentrated
            ("C001", "00687B", 200000),
            ("C002", "0050", 300000),  # 30% — ok
            ("C002", "0056", 300000),
            ("C002", "00687B", 400000),
        ],
    )
    conn.commit()


def _seed_style_drift(conn):
    """Fund holdings + benchmark for style drift detection."""
    conn.execute("INSERT INTO clients VALUES ('S001', 'Drifter')")
    conn.execute("INSERT INTO client_portfolios VALUES ('S001', 'FUND_X', '', 1000000)")

    # Fund: heavy in semi, light in finance
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("FUND_X", "半導體業", 0.70, 0.08),
            ("FUND_X", "金融保險業", 0.10, 0.03),
            ("FUND_X", "其他", 0.20, 0.01),
        ],
    )
    # Benchmark: balanced
    conn.executemany(
        "INSERT INTO benchmark_index VALUES ('MI_INDEX', 'latest', ?, ?, ?, datetime('now'), '2099-01-01')",
        [
            ("半導體業", 0.30, 0.08),
            ("金融保險業", 0.40, 0.03),
            ("其他", 0.30, 0.01),
        ],
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Signal 1: PE Percentile
# ---------------------------------------------------------------------------

class TestPEPercentile:
    def test_triggers_above_threshold(self):
        config = AnomalyConfig(pe_percentile=90)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        pe_data = {"0050": 92}

        alerts = _check_pe_percentile("C001", holdings, config, pe_data)
        assert len(alerts) == 1
        assert alerts[0].signal_type == "pe_percentile"
        assert alerts[0].severity == "warning"

    def test_critical_above_95(self):
        config = AnomalyConfig(pe_percentile=90)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        pe_data = {"0050": 97}

        alerts = _check_pe_percentile("C001", holdings, config, pe_data)
        assert alerts[0].severity == "critical"

    def test_no_alert_below_threshold(self):
        config = AnomalyConfig(pe_percentile=90)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        pe_data = {"0050": 85}

        alerts = _check_pe_percentile("C001", holdings, config, pe_data)
        assert len(alerts) == 0

    def test_no_data_no_alert(self):
        config = AnomalyConfig()
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]

        alerts = _check_pe_percentile("C001", holdings, config, {})
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Signal 2: RSI Overbought
# ---------------------------------------------------------------------------

class TestRSIOverbought:
    def test_triggers_above_threshold(self):
        config = AnomalyConfig(rsi_overbought=70)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        rsi_data = {"0050": 75}

        alerts = _check_rsi_overbought("C001", holdings, config, rsi_data)
        assert len(alerts) == 1
        assert alerts[0].signal_type == "rsi_overbought"
        assert "超買" in alerts[0].message


# ---------------------------------------------------------------------------
# Signal 3: Fund Outflow
# ---------------------------------------------------------------------------

class TestFundOutflow:
    def test_triggers_on_consecutive_days(self):
        config = AnomalyConfig(outflow_consecutive_days=5)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        flow_data = {"0050": 7}

        alerts = _check_fund_outflow("C001", holdings, config, flow_data)
        assert len(alerts) == 1
        assert "7 日" in alerts[0].message

    def test_no_alert_below_threshold(self):
        config = AnomalyConfig(outflow_consecutive_days=5)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        flow_data = {"0050": 3}

        alerts = _check_fund_outflow("C001", holdings, config, flow_data)
        assert len(alerts) == 0


# ---------------------------------------------------------------------------
# Signal 4: Foreign Selling
# ---------------------------------------------------------------------------

class TestForeignSelling:
    def test_triggers_on_consecutive_days(self):
        config = AnomalyConfig(foreign_sell_consecutive_days=5)
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        foreign_data = {"0050": 6}

        alerts = _check_foreign_selling("C001", holdings, config, foreign_data)
        assert len(alerts) == 1
        assert "外資" in alerts[0].message


# ---------------------------------------------------------------------------
# Signal 5: Concentration Spike (local data)
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_triggers_above_40pct(self):
        config = AnomalyConfig(concentration_threshold=0.40)
        holdings = [
            {"fund_code": "0050", "cost_basis": 800000},
            {"fund_code": "00687B", "cost_basis": 200000},
        ]

        alerts = _check_concentration("C001", holdings, 1000000, config)
        assert len(alerts) == 1
        assert alerts[0].fund_code == "0050"
        assert alerts[0].signal_type == "concentration_spike"
        assert "80.0%" in alerts[0].message

    def test_critical_above_60pct(self):
        config = AnomalyConfig(concentration_threshold=0.40)
        holdings = [
            {"fund_code": "0050", "cost_basis": 900000},
            {"fund_code": "00687B", "cost_basis": 100000},
        ]
        alerts = _check_concentration("C001", holdings, 1000000, config)
        assert alerts[0].severity == "critical"

    def test_no_alert_below_threshold(self):
        config = AnomalyConfig(concentration_threshold=0.40)
        holdings = [
            {"fund_code": "0050", "cost_basis": 300000},
            {"fund_code": "0056", "cost_basis": 300000},
            {"fund_code": "00687B", "cost_basis": 400000},
        ]

        alerts = _check_concentration("C001", holdings, 1000000, config)
        assert len(alerts) == 0

    def test_aggregates_same_fund_across_banks(self):
        config = AnomalyConfig(concentration_threshold=0.40)
        holdings = [
            {"fund_code": "0050", "cost_basis": 300000},
            {"fund_code": "0050", "cost_basis": 300000},  # same fund, diff bank
            {"fund_code": "00687B", "cost_basis": 400000},
        ]

        alerts = _check_concentration("C001", holdings, 1000000, config)
        assert len(alerts) == 1
        assert alerts[0].fund_code == "0050"


# ---------------------------------------------------------------------------
# Signal 6: Style Drift (local data)
# ---------------------------------------------------------------------------

class TestStyleDrift:
    def test_triggers_on_drift(self, db_conn):
        _seed_style_drift(db_conn)
        config = AnomalyConfig(style_drift_threshold=0.15)
        holdings = [{"fund_code": "FUND_X", "cost_basis": 1000000}]

        alerts = _check_style_drift("S001", holdings, db_conn, config)
        assert len(alerts) == 1
        assert alerts[0].signal_type == "style_drift"
        assert "偏移" in alerts[0].message

    def test_no_drift_when_aligned(self, db_conn):
        """Fund matching benchmark → no drift."""
        db_conn.execute("INSERT INTO clients VALUES ('A001', 'Aligned')")
        db_conn.execute("INSERT INTO client_portfolios VALUES ('A001', 'FUND_Y', '', 1000000)")
        db_conn.executemany(
            "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, 0, 'test', datetime('now'), '2099-01-01')",
            [
                ("FUND_Y", "半導體業", 0.30),
                ("FUND_Y", "金融保險業", 0.40),
                ("FUND_Y", "其他", 0.30),
            ],
        )
        db_conn.executemany(
            "INSERT OR IGNORE INTO benchmark_index VALUES ('MI_INDEX', 'latest', ?, ?, ?, datetime('now'), '2099-01-01')",
            [
                ("半導體業", 0.30, 0.08),
                ("金融保險業", 0.40, 0.03),
                ("其他", 0.30, 0.01),
            ],
        )
        db_conn.commit()

        config = AnomalyConfig(style_drift_threshold=0.15)
        holdings = [{"fund_code": "FUND_Y", "cost_basis": 1000000}]
        alerts = _check_style_drift("A001", holdings, db_conn, config)
        assert len(alerts) == 0

    def test_no_conn_returns_empty(self):
        config = AnomalyConfig()
        holdings = [{"fund_code": "0050", "cost_basis": 1000000}]
        alerts = _check_style_drift("C001", holdings, None, config)
        assert alerts == []


# ---------------------------------------------------------------------------
# Full scan
# ---------------------------------------------------------------------------

class TestScanAllClients:
    def test_scans_all_clients(self, db_conn):
        _seed_basic(db_conn)
        alerts = scan_all_clients(db_conn, store_alerts=False)

        # C001 has 80% concentration → at least 1 alert
        c001_alerts = [a for a in alerts if a.client_id == "C001"]
        assert len(c001_alerts) >= 1

    def test_alerts_stored_in_db(self, db_conn):
        _seed_basic(db_conn)
        scan_all_clients(db_conn, store_alerts=True)

        stored = get_alerts_for_client(db_conn, "C001")
        assert len(stored) >= 1

    def test_with_market_data(self, db_conn):
        _seed_basic(db_conn)
        market_data = {
            "pe_data": {"0050": 92},
            "rsi_data": {"0050": 75},
        }
        alerts = scan_all_clients(db_conn, market_data=market_data, store_alerts=False)

        signal_types = {a.signal_type for a in alerts}
        assert "pe_percentile" in signal_types
        assert "rsi_overbought" in signal_types

    def test_no_clients_returns_empty(self, db_conn):
        alerts = scan_all_clients(db_conn, store_alerts=False)
        assert alerts == []


# ---------------------------------------------------------------------------
# Alert CRUD
# ---------------------------------------------------------------------------

class TestAlertCRUD:
    def test_acknowledge_alert(self, db_conn):
        _seed_basic(db_conn)
        scan_all_clients(db_conn, store_alerts=True)

        alerts = get_alerts_for_client(db_conn, "C001")
        assert len(alerts) >= 1

        alert_id = alerts[0]["alert_id"]
        assert acknowledge_alert(db_conn, alert_id) is True

        # Should no longer appear in unacknowledged
        remaining = get_alerts_for_client(db_conn, "C001")
        remaining_ids = {a["alert_id"] for a in remaining}
        assert alert_id not in remaining_ids

    def test_acknowledge_nonexistent(self, db_conn):
        assert acknowledge_alert(db_conn, "FAKE") is False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_custom_thresholds(self):
        config = AnomalyConfig(concentration_threshold=0.30)
        holdings = [
            {"fund_code": "0050", "cost_basis": 350000},
            {"fund_code": "00687B", "cost_basis": 650000},
        ]
        alerts = _check_concentration("C001", holdings, 1000000, config)
        assert len(alerts) == 2  # both exceed 30%

    def test_default_config(self):
        config = AnomalyConfig()
        assert config.pe_percentile == 90.0
        assert config.concentration_threshold == 0.40


# ---------------------------------------------------------------------------
# Alert structure
# ---------------------------------------------------------------------------

class TestAlertStructure:
    def test_alert_fields(self):
        config = AnomalyConfig(concentration_threshold=0.40)
        holdings = [
            {"fund_code": "0050", "cost_basis": 800000},
            {"fund_code": "00687B", "cost_basis": 200000},
        ]
        alerts = _check_concentration("C001", holdings, 1000000, config)

        a = alerts[0]
        assert isinstance(a, AnomalyAlert)
        assert a.client_id == "C001"
        assert a.fund_code == "0050"
        assert a.signal_type == "concentration_spike"
        assert a.severity in ("warning", "critical")
        assert a.value > 0
        assert a.threshold == 0.40
        assert len(a.message) > 0
