"""Tests for data/cache.py — WAL mode, TTL, CRUD, concurrency."""

import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from data.cache import (
    get_connection,
    init_db,
    get_fund_holdings,
    upsert_fund_holdings,
    get_benchmark_index,
    upsert_benchmark_index,
    get_industry_mapping,
    upsert_industry_mapping,
    get_all_industry_mappings,
    log_unmapped_category,
    get_unmapped_categories,
    log_report,
    get_report,
    purge_expired,
)


@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like temp database."""
    db_path = str(tmp_path / "test_cache.db")
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


class TestWALMode:
    def test_wal_enabled(self, db):
        mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout(self, db):
        timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout == 5000


class TestFundHoldings:
    HOLDINGS = [
        {"industry": "半導體", "weight": 0.35, "return_rate": 0.12},
        {"industry": "金融保險", "weight": 0.15, "return_rate": 0.05},
    ]

    def test_upsert_and_get(self, db):
        upsert_fund_holdings(db, "0050", "2026-03", self.HOLDINGS)
        result = get_fund_holdings(db, "0050", "2026-03")
        assert result is not None
        assert len(result) == 2
        assert result[0]["industry"] == "半導體"
        assert result[0]["weight"] == 0.35

    def test_missing_returns_none(self, db):
        assert get_fund_holdings(db, "9999", "2026-03") is None

    def test_expired_returns_none(self, db):
        upsert_fund_holdings(db, "0050", "2026-03", self.HOLDINGS, ttl_hours=0)
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        with patch("data.cache._utcnow", return_value=future):
            result = get_fund_holdings(db, "0050", "2026-03")
        assert result is None

    def test_fresh_entry_returns_data(self, db):
        upsert_fund_holdings(db, "0050", "2026-03", self.HOLDINGS, ttl_hours=24)
        result = get_fund_holdings(db, "0050", "2026-03")
        assert result is not None
        assert len(result) == 2


class TestBenchmarkIndex:
    DATA = [
        {"industry": "半導體", "weight": 0.40, "return_rate": 0.10},
        {"industry": "金融保險", "weight": 0.20, "return_rate": 0.03},
    ]

    def test_upsert_and_get(self, db):
        upsert_benchmark_index(db, "TAIEX", "2026-03", self.DATA)
        result = get_benchmark_index(db, "TAIEX", "2026-03")
        assert result is not None
        assert len(result) == 2

    def test_expired_returns_none(self, db):
        upsert_benchmark_index(db, "TAIEX", "2026-03", self.DATA, ttl_hours=0)
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        with patch("data.cache._utcnow", return_value=future):
            result = get_benchmark_index(db, "TAIEX", "2026-03")
        assert result is None


class TestIndustryMap:
    def test_upsert_and_get(self, db):
        upsert_industry_mapping(db, "半導體業", "半導體")
        assert get_industry_mapping(db, "半導體業") == "半導體"

    def test_missing_returns_none(self, db):
        assert get_industry_mapping(db, "不存在") is None

    def test_get_all(self, db):
        upsert_industry_mapping(db, "半導體業", "半導體")
        upsert_industry_mapping(db, "金融業", "金融保險")
        mappings = get_all_industry_mappings(db)
        assert len(mappings) == 2
        assert mappings["半導體業"] == "半導體"


class TestUnmappedCategories:
    def test_log_and_get(self, db):
        log_unmapped_category(db, "未知產業", "0050", "2026-03", 0.02)
        results = get_unmapped_categories(db)
        assert len(results) == 1
        assert results[0]["raw_name"] == "未知產業"


class TestReportLog:
    def test_log_and_get(self, db):
        log_report(db, "rpt-001", "0050", "2026-03", "BF2", "Advisor A", "/tmp/report.pdf")
        report = get_report(db, "rpt-001")
        assert report is not None
        assert report["fund_code"] == "0050"
        assert report["brinson_mode"] == "BF2"

    def test_missing_returns_none(self, db):
        assert get_report(db, "nonexistent") is None


class TestPurgeExpired:
    def test_purge_removes_expired(self, db):
        upsert_fund_holdings(
            db, "0050", "2026-03",
            [{"industry": "半導體", "weight": 0.35, "return_rate": 0.12}],
            ttl_hours=0,
        )
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=1)
        with patch("data.cache._utcnow", return_value=future):
            deleted = purge_expired(db)
        assert deleted == 1


class TestConcurrency:
    def test_concurrent_writes(self, tmp_path):
        """5 threads writing concurrently should not deadlock."""
        db_path = str(tmp_path / "concurrent.db")
        init_db(db_path)

        errors = []

        def writer(thread_id):
            try:
                conn = get_connection(db_path)
                for i in range(10):
                    upsert_fund_holdings(
                        conn,
                        f"fund-{thread_id}",
                        "2026-03",
                        [{"industry": f"ind-{i}", "weight": 0.1, "return_rate": 0.05}],
                    )
                conn.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Concurrent write errors: {errors}"

        # Verify data integrity
        conn = get_connection(db_path)
        for i in range(5):
            result = get_fund_holdings(conn, f"fund-{i}", "2026-03")
            assert result is not None
        conn.close()
