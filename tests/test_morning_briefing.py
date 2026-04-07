"""Tests for ai/morning_briefing.py — morning briefing generator."""

import json
import sqlite3

import pytest

from ai.morning_briefing import (
    generate_briefing,
    get_briefing,
    _group_and_rank_alerts,
    _template_action,
    _template_talking_points,
    _template_summary,
)
from interfaces import AnomalyAlert, BriefingItem, MorningBriefing


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
            name TEXT NOT NULL,
            kyc_risk_level TEXT DEFAULT 'moderate',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE client_portfolios (
            client_id TEXT NOT NULL,
            fund_code TEXT NOT NULL,
            bank_name TEXT DEFAULT '',
            shares REAL NOT NULL DEFAULT 0,
            cost_basis REAL NOT NULL DEFAULT 0,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (client_id, fund_code, bank_name),
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
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
            acknowledged_at TEXT,
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        CREATE INDEX idx_alerts_client ON anomaly_alerts(client_id);
        CREATE INDEX idx_alerts_signal ON anomaly_alerts(signal_type);
        CREATE TABLE briefings (
            briefing_id TEXT PRIMARY KEY,
            date TEXT NOT NULL,
            content_json TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_briefings_date ON briefings(date);
    """)
    return conn


def _seed_three_clients(conn):
    """Seed 3 clients with different anomaly profiles.

    C001: high concentration (60% in one fund) — triggers concentration_spike
    C002: high concentration (50% in one fund) — triggers concentration_spike
    C003: balanced — no anomalies
    """
    conn.executemany("INSERT INTO clients VALUES (?, ?, 'moderate', datetime('now'))", [
        ("C001", "王小明"),
        ("C002", "林小華"),
        ("C003", "陳小美"),
    ])

    # C001: 2 funds, FUND_A is 60% concentration
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, '', 0, ?, datetime('now'))",
        [
            ("C001", "FUND_A", 600000),
            ("C001", "FUND_B", 400000),
        ],
    )

    # C002: 2 funds, FUND_C is 50% concentration
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, '', 0, ?, datetime('now'))",
        [
            ("C002", "FUND_C", 500000),
            ("C002", "FUND_D", 500000),
        ],
    )

    # C003: 3 balanced funds (each ~33%)
    conn.executemany(
        "INSERT INTO client_portfolios VALUES (?, ?, '', 0, ?, datetime('now'))",
        [
            ("C003", "FUND_E", 333000),
            ("C003", "FUND_F", 333000),
            ("C003", "FUND_G", 334000),
        ],
    )

    conn.commit()


def _make_alerts() -> list[AnomalyAlert]:
    """Create sample alerts for testing grouping/ranking."""
    return [
        AnomalyAlert(
            client_id="C001", fund_code="FUND_A",
            signal_type="concentration_spike", severity="critical",
            value=0.60, threshold=0.40,
            message="FUND_A 佔投組 60.0%，超過 40% 集中度警戒線。",
        ),
        AnomalyAlert(
            client_id="C002", fund_code="FUND_C",
            signal_type="concentration_spike", severity="warning",
            value=0.50, threshold=0.40,
            message="FUND_C 佔投組 50.0%，超過 40% 集中度警戒線。",
        ),
        AnomalyAlert(
            client_id="C001", fund_code="FUND_A",
            signal_type="pe_percentile", severity="warning",
            value=92.0, threshold=90.0,
            message="FUND_A 本益比位於歷史 92 百分位。",
        ),
        AnomalyAlert(
            client_id="C002", fund_code="FUND_C",
            signal_type="rsi_overbought", severity="info",
            value=72.0, threshold=70.0,
            message="FUND_C RSI 達 72.0。",
        ),
    ]


# ---------------------------------------------------------------------------
# Grouping and ranking
# ---------------------------------------------------------------------------

class TestGroupAndRank:
    def test_groups_by_signal_type(self):
        alerts = _make_alerts()
        grouped = _group_and_rank_alerts(alerts, top_n=10)

        signal_types = [g[0] for g in grouped]
        assert "concentration_spike" in signal_types
        assert "pe_percentile" in signal_types
        assert "rsi_overbought" in signal_types

    def test_critical_first(self):
        alerts = _make_alerts()
        grouped = _group_and_rank_alerts(alerts, top_n=10)

        # concentration_spike has a critical alert, should be first
        assert grouped[0][0] == "concentration_spike"

    def test_top_n_limits(self):
        alerts = _make_alerts()
        grouped = _group_and_rank_alerts(alerts, top_n=2)

        assert len(grouped) == 2


# ---------------------------------------------------------------------------
# Full briefing generation
# ---------------------------------------------------------------------------

class TestGenerateBriefing:
    def test_no_alerts_returns_empty_briefing(self, db_conn):
        _seed_three_clients(db_conn)
        # With default thresholds, C001 has 60% concentration which triggers
        # Use high threshold to avoid alerts
        from interfaces import AnomalyConfig
        # Pass market_data with no external signals, and balanced portfolios
        # C003 only has balanced funds, so seed only C003
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE clients (client_id TEXT PRIMARY KEY, name TEXT, kyc_risk_level TEXT DEFAULT 'moderate', created_at TEXT DEFAULT (datetime('now')));
            CREATE TABLE client_portfolios (client_id TEXT, fund_code TEXT, bank_name TEXT DEFAULT '', shares REAL DEFAULT 0, cost_basis REAL DEFAULT 0, added_at TEXT DEFAULT (datetime('now')), PRIMARY KEY (client_id, fund_code, bank_name));
            CREATE TABLE fund_holdings (fund_code TEXT, period TEXT, industry TEXT, weight REAL, return_rate REAL, source TEXT DEFAULT 'sitca', fetched_at TEXT DEFAULT (datetime('now')), expires_at TEXT DEFAULT '2099-01-01', PRIMARY KEY (fund_code, period, industry));
            CREATE TABLE benchmark_index (index_name TEXT, period TEXT, industry TEXT, weight REAL, return_rate REAL, fetched_at TEXT DEFAULT (datetime('now')), expires_at TEXT DEFAULT '2099-01-01', PRIMARY KEY (index_name, period, industry));
            CREATE TABLE anomaly_alerts (alert_id TEXT PRIMARY KEY, client_id TEXT, fund_code TEXT, signal_type TEXT, severity TEXT DEFAULT 'warning', value REAL, threshold REAL, message TEXT, detected_at TEXT DEFAULT (datetime('now')), acknowledged_at TEXT);
            CREATE TABLE briefings (briefing_id TEXT PRIMARY KEY, date TEXT, content_json TEXT, generated_at TEXT DEFAULT (datetime('now')));
        """)
        # Single client with balanced portfolio (3 funds, ~33% each)
        conn.execute("INSERT INTO clients VALUES ('C099', '平衡客戶', 'moderate', datetime('now'))")
        conn.executemany(
            "INSERT INTO client_portfolios VALUES (?, ?, '', 0, ?, datetime('now'))",
            [("C099", "F1", 333000), ("C099", "F2", 333000), ("C099", "F3", 334000)],
        )
        conn.commit()

        briefing = generate_briefing(conn, generate_ai=False, store=False)

        assert isinstance(briefing, MorningBriefing)
        assert len(briefing.items) == 0
        assert "正常" in briefing.summary

    def test_with_anomalies(self, db_conn):
        _seed_three_clients(db_conn)
        # C001 has 60% concentration → will trigger concentration_spike
        # Provide PE data to trigger pe_percentile too
        market_data = {
            "pe_data": {"FUND_A": 95.0},
        }

        briefing = generate_briefing(
            db_conn, market_data=market_data, generate_ai=False, store=False
        )

        assert isinstance(briefing, MorningBriefing)
        assert len(briefing.items) > 0
        assert briefing.summary != ""

    def test_items_have_required_fields(self, db_conn):
        _seed_three_clients(db_conn)
        briefing = generate_briefing(
            db_conn, generate_ai=False, store=False
        )

        for item in briefing.items:
            assert isinstance(item, BriefingItem)
            assert item.signal_type != ""
            assert item.severity in ("critical", "warning", "info")
            assert len(item.affected_clients) > 0
            assert len(item.affected_client_ids) > 0
            assert item.suggested_action != ""
            assert item.talking_points != ""

    def test_top_3_limit(self, db_conn):
        _seed_three_clients(db_conn)
        market_data = {
            "pe_data": {"FUND_A": 95.0, "FUND_B": 92.0, "FUND_C": 93.0},
            "rsi_data": {"FUND_A": 75.0},
        }

        briefing = generate_briefing(
            db_conn, market_data=market_data, top_n=3,
            generate_ai=False, store=False,
        )

        assert len(briefing.items) <= 3


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

class TestStorage:
    def test_store_and_retrieve(self, db_conn):
        _seed_three_clients(db_conn)
        briefing = generate_briefing(
            db_conn, generate_ai=False, store=True
        )

        retrieved = get_briefing(db_conn, briefing.date)
        assert retrieved is not None
        assert retrieved["date"] == briefing.date
        assert "items" in retrieved

    def test_retrieve_nonexistent(self, db_conn):
        result = get_briefing(db_conn, "2099-01-01")
        assert result is None


# ---------------------------------------------------------------------------
# Template fallbacks
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_template_action_critical(self):
        alerts = [_make_alerts()[0]]  # critical concentration
        action = _template_action("concentration_spike", alerts)

        assert "緊急" in action
        assert "1 位" in action

    def test_template_action_warning(self):
        alerts = [_make_alerts()[2]]  # warning PE
        action = _template_action("pe_percentile", alerts)

        assert "注意" in action

    def test_template_talking_points(self):
        alerts = [_make_alerts()[0]]
        talking = _template_talking_points(
            "concentration_spike", alerts, ["王小明"]
        )

        assert "王小明" in talking
        assert "持倉過度集中" in talking
        assert "建議話術" in talking

    def test_template_summary(self):
        items = [
            BriefingItem(
                signal_type="concentration_spike",
                severity="critical",
                affected_clients=["王小明"],
                affected_client_ids=["C001"],
                suggested_action="test",
                talking_points="test",
            ),
            BriefingItem(
                signal_type="pe_percentile",
                severity="warning",
                affected_clients=["林小華"],
                affected_client_ids=["C002"],
                suggested_action="test",
                talking_points="test",
            ),
        ]
        summary = _template_summary(items)

        assert "晨報" in summary
        assert "緊急" in summary
        assert "2 位客戶" in summary


# ---------------------------------------------------------------------------
# AI fallback
# ---------------------------------------------------------------------------

class TestAIFallback:
    def test_fallback_when_no_key(self, db_conn):
        _seed_three_clients(db_conn)
        briefing = generate_briefing(
            db_conn, generate_ai=True, api_key="", store=False
        )

        # Should still produce results using templates
        for item in briefing.items:
            assert item.suggested_action != ""
            assert item.talking_points != ""
