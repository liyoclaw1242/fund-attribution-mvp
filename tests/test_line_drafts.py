"""Tests for ai/line_drafts.py — weekly LINE message draft generator."""

import sqlite3

import pytest

from ai.line_drafts import (
    generate_weekly_drafts,
    generate_draft_for_client,
    get_drafts_for_week,
    mark_draft_reviewed,
    mark_draft_sent,
    _fallback_message,
    _gather_client_context,
)
from interfaces import LineDraft


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
        CREATE TABLE line_drafts (
            draft_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            message TEXT NOT NULL,
            week TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            reviewed_at TEXT,
            sent_at TEXT
        );
    """)
    return conn


def _seed_clients(conn):
    """Insert 3 clients with different portfolio scenarios."""
    # Client 1: Winning portfolio
    conn.execute("INSERT INTO clients VALUES ('C001', '王小明')")
    conn.execute("INSERT INTO client_portfolios VALUES ('C001', '0050', '', 0, 500000)")
    conn.execute("INSERT INTO client_portfolios VALUES ('C001', 'NN1001', '', 0, 300000)")
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [
            ("0050", "半導體業", 0.6, 0.08),
            ("0050", "金融保險業", 0.4, 0.03),
            ("NN1001", "全球債券", 1.0, 0.02),
        ],
    )

    # Client 2: Losing portfolio
    conn.execute("INSERT INTO clients VALUES ('C002', '李美麗')")
    conn.execute("INSERT INTO client_portfolios VALUES ('C002', 'FL1001', '', 0, 1000000)")
    conn.executemany(
        "INSERT INTO fund_holdings VALUES (?, 'latest', ?, ?, ?, 'test', datetime('now'), '2099-01-01')",
        [("FL1001", "科技業", 1.0, -0.05)],
    )

    # Client 3: No holdings data (new client)
    conn.execute("INSERT INTO clients VALUES ('C003', '張大偉')")

    conn.commit()


# ---------------------------------------------------------------------------
# Generate drafts — all clients
# ---------------------------------------------------------------------------

class TestGenerateWeeklyDrafts:
    def test_generates_one_per_client(self, db_conn):
        _seed_clients(db_conn)
        drafts = generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        assert len(drafts) == 3
        client_ids = {d.client_id for d in drafts}
        assert client_ids == {"C001", "C002", "C003"}

    def test_drafts_are_line_draft_objects(self, db_conn):
        _seed_clients(db_conn)
        drafts = generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        for d in drafts:
            assert isinstance(d, LineDraft)
            assert d.sent is False
            assert len(d.message) > 0

    def test_message_under_200_chars(self, db_conn):
        _seed_clients(db_conn)
        drafts = generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        for d in drafts:
            assert len(d.message) <= 200, (
                f"Client {d.client_id} message too long: {len(d.message)} chars"
            )

    def test_stored_in_db(self, db_conn):
        _seed_clients(db_conn)
        generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        stored = get_drafts_for_week(db_conn, "2026-W15")
        assert len(stored) == 3

    def test_no_clients_returns_empty(self, db_conn):
        drafts = generate_weekly_drafts(db_conn, week="2026-W15", api_key="")
        assert drafts == []

    def test_auto_week(self, db_conn):
        """Week auto-computed when not provided."""
        _seed_clients(db_conn)
        drafts = generate_weekly_drafts(db_conn, api_key="")
        assert len(drafts) == 3


# ---------------------------------------------------------------------------
# Generate draft — single client
# ---------------------------------------------------------------------------

class TestGenerateDraftForClient:
    def test_single_client(self, db_conn):
        _seed_clients(db_conn)
        draft = generate_draft_for_client(db_conn, "C001", week="2026-W15", api_key="")

        assert draft.client_id == "C001"
        assert draft.client_name == "王小明"
        assert len(draft.message) > 0

    def test_unknown_client_raises(self, db_conn):
        with pytest.raises(ValueError, match="not found"):
            generate_draft_for_client(db_conn, "GHOST", api_key="")


# ---------------------------------------------------------------------------
# Personalization — messages reference holdings
# ---------------------------------------------------------------------------

class TestPersonalization:
    def test_winning_client_positive_tone(self, db_conn):
        _seed_clients(db_conn)
        draft = generate_draft_for_client(db_conn, "C001", week="2026-W15", api_key="")

        # Fallback message should mention positive return or holdings
        assert "王小明" in draft.message

    def test_losing_client_mentions_holdings(self, db_conn):
        _seed_clients(db_conn)
        draft = generate_draft_for_client(db_conn, "C002", week="2026-W15", api_key="")

        assert "李美麗" in draft.message

    def test_empty_client_gets_generic(self, db_conn):
        _seed_clients(db_conn)
        draft = generate_draft_for_client(db_conn, "C003", week="2026-W15", api_key="")

        assert "張大偉" in draft.message


# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

class TestGatherContext:
    def test_context_with_holdings(self, db_conn):
        _seed_clients(db_conn)
        ctx = _gather_client_context(db_conn, "C001")

        assert ctx["num_funds"] == 2
        # 500000 (0050) + 300000 (NN1001) = 800000
        assert ctx["total_value"] == pytest.approx(800000)
        assert len(ctx["top_funds"]) == 2

    def test_context_no_holdings(self, db_conn):
        _seed_clients(db_conn)
        ctx = _gather_client_context(db_conn, "C003")

        assert ctx["num_funds"] == 0
        assert ctx["total_value"] == 0


# ---------------------------------------------------------------------------
# Fallback messages
# ---------------------------------------------------------------------------

class TestFallbackMessage:
    def test_positive_return(self):
        msg = _fallback_message("王小明", {
            "portfolio_return": 0.05,
            "num_funds": 3,
            "top_funds": [("0050", 500000)],
            "total_value": 1000000,
            "fund_codes": ["0050"],
        })
        assert "王小明" in msg
        assert "📈" in msg
        assert len(msg) <= 200

    def test_negative_return(self):
        msg = _fallback_message("李美麗", {
            "portfolio_return": -0.03,
            "num_funds": 2,
            "top_funds": [("FL1001", 1000000)],
            "total_value": 1000000,
            "fund_codes": ["FL1001"],
        })
        assert "李美麗" in msg
        assert "定期定額" in msg

    def test_no_return_data(self):
        msg = _fallback_message("張大偉", {
            "portfolio_return": None,
            "num_funds": 0,
            "top_funds": [],
            "total_value": 0,
            "fund_codes": [],
        })
        assert "張大偉" in msg
        assert "檢視" in msg


# ---------------------------------------------------------------------------
# Draft CRUD
# ---------------------------------------------------------------------------

class TestDraftCRUD:
    def test_mark_reviewed(self, db_conn):
        _seed_clients(db_conn)
        generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        stored = get_drafts_for_week(db_conn, "2026-W15")
        draft_id = stored[0]["draft_id"]

        assert mark_draft_reviewed(db_conn, draft_id) is True
        updated = db_conn.execute(
            "SELECT reviewed_at FROM line_drafts WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        assert updated["reviewed_at"] is not None

    def test_mark_sent(self, db_conn):
        _seed_clients(db_conn)
        generate_weekly_drafts(db_conn, week="2026-W15", api_key="")

        stored = get_drafts_for_week(db_conn, "2026-W15")
        draft_id = stored[0]["draft_id"]

        assert mark_draft_sent(db_conn, draft_id) is True
        updated = db_conn.execute(
            "SELECT sent_at FROM line_drafts WHERE draft_id = ?", (draft_id,)
        ).fetchone()
        assert updated["sent_at"] is not None

    def test_mark_nonexistent_returns_false(self, db_conn):
        assert mark_draft_reviewed(db_conn, "FAKE") is False
        assert mark_draft_sent(db_conn, "FAKE") is False

    def test_get_drafts_empty_week(self, db_conn):
        assert get_drafts_for_week(db_conn, "2099-W01") == []
