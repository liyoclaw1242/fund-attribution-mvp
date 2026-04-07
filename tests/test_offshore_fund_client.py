"""Tests for data/offshore_fund_client.py — offshore fund data client."""

import json
import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from data.offshore_fund_client import (
    search_fund,
    fetch_fund_nav,
    fetch_fund_allocation,
    normalize_sector,
    _KNOWN_FUNDS,
    _STUB_ALLOCATIONS,
    OFFSHORE_SECTOR_MAP,
    _cache_json,
    _get_cached_json,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite DB with offshore cache table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE offshore_fund_cache (
            fund_id TEXT NOT NULL,
            data_type TEXT NOT NULL,
            period TEXT DEFAULT '',
            data_json TEXT NOT NULL,
            fetched_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (fund_id, data_type, period)
        )
    """)
    return conn


# ---------------------------------------------------------------------------
# search_fund
# ---------------------------------------------------------------------------

class TestSearchFund:
    @patch("data.offshore_fund_client._search_anue", side_effect=Exception("API down"))
    def test_search_by_name(self, mock_anue):
        results = search_fund("摩根太平洋")
        assert len(results) >= 1
        assert any("摩根太平洋" in r["fund_name"] for r in results)

    @patch("data.offshore_fund_client._search_anue", side_effect=Exception("API down"))
    def test_search_by_house(self, mock_anue):
        results = search_fund("貝萊德")
        assert len(results) >= 1

    @patch("data.offshore_fund_client._search_anue", side_effect=Exception("API down"))
    def test_search_empty_keyword(self, mock_anue):
        results = search_fund("")
        assert results == []

    @patch("data.offshore_fund_client._search_anue", side_effect=Exception("API down"))
    def test_search_no_match(self, mock_anue):
        results = search_fund("不存在的基金XYZ")
        assert results == []

    @patch("data.offshore_fund_client._search_anue", side_effect=Exception("API down"))
    def test_search_returns_required_fields(self, mock_anue):
        results = search_fund("摩根")
        for r in results:
            assert "fund_id" in r
            assert "fund_name" in r
            assert "currency" in r

    def test_search_cached(self, db_conn):
        cached_results = [{"fund_id": "TEST", "fund_name": "Cached Fund"}]
        _cache_json(db_conn, "search:test", "search", "", cached_results)
        results = search_fund("test", conn=db_conn)
        assert len(results) == 1
        assert results[0]["fund_name"] == "Cached Fund"


# ---------------------------------------------------------------------------
# fetch_fund_nav
# ---------------------------------------------------------------------------

class TestFetchFundNav:
    @patch("data.offshore_fund_client._fetch_anue_nav", side_effect=Exception("API down"))
    def test_returns_dataframe(self, mock_anue):
        df = fetch_fund_nav("LU0117844026", "1y")
        assert isinstance(df, pd.DataFrame)
        assert "date" in df.columns
        assert "nav" in df.columns
        assert "return_rate" in df.columns

    @patch("data.offshore_fund_client._fetch_anue_nav", side_effect=Exception("API down"))
    def test_stub_has_data(self, mock_anue):
        df = fetch_fund_nav("LU0117844026", "1y")
        assert len(df) > 200  # ~250 business days in a year

    @patch("data.offshore_fund_client._fetch_anue_nav", side_effect=Exception("API down"))
    def test_nav_positive(self, mock_anue):
        df = fetch_fund_nav("LU0117844026", "1m")
        assert (df["nav"] > 0).all()

    @patch("data.offshore_fund_client._fetch_anue_nav", side_effect=Exception("API down"))
    def test_different_periods(self, mock_anue):
        df_1m = fetch_fund_nav("LU0117844026", "1m")
        df_1y = fetch_fund_nav("LU0117844026", "1y")
        assert len(df_1y) > len(df_1m)

    def test_cached_nav(self, db_conn):
        cached = [
            {"date": "2026-04-01", "nav": 100.0, "return_rate": 0.0},
            {"date": "2026-04-02", "nav": 101.0, "return_rate": 0.01},
        ]
        _cache_json(db_conn, "TEST_FUND", "nav", "1m", cached)
        df = fetch_fund_nav("TEST_FUND", "1m", conn=db_conn)
        assert len(df) == 2
        assert df["nav"].iloc[1] == 101.0


# ---------------------------------------------------------------------------
# fetch_fund_allocation
# ---------------------------------------------------------------------------

class TestFetchFundAllocation:
    @patch("data.offshore_fund_client._fetch_anue_allocation", side_effect=Exception("API down"))
    def test_known_fund_allocation(self, mock_anue):
        alloc = fetch_fund_allocation("LU0117844026")
        assert "as_of_date" in alloc
        assert "by_sector" in alloc
        assert "by_region" in alloc
        assert "by_asset_class" in alloc

    @patch("data.offshore_fund_client._fetch_anue_allocation", side_effect=Exception("API down"))
    def test_sector_weights_sum_approx_one(self, mock_anue):
        alloc = fetch_fund_allocation("LU0117844026")
        total = sum(s["weight"] for s in alloc["by_sector"])
        assert total == pytest.approx(1.0, abs=0.05)

    @patch("data.offshore_fund_client._fetch_anue_allocation", side_effect=Exception("API down"))
    def test_region_weights_sum_approx_one(self, mock_anue):
        alloc = fetch_fund_allocation("LU0117844026")
        total = sum(r["weight"] for r in alloc["by_region"])
        assert total == pytest.approx(1.0, abs=0.05)

    @patch("data.offshore_fund_client._fetch_anue_allocation", side_effect=Exception("API down"))
    def test_unknown_fund_raises(self, mock_anue):
        with pytest.raises(ValueError, match="No allocation data"):
            fetch_fund_allocation("UNKNOWN_FUND_XYZ")

    def test_cached_allocation(self, db_conn):
        cached = {"as_of_date": "2026-03-31", "by_sector": [{"sector": "Tech", "weight": 1.0}]}
        _cache_json(db_conn, "CACHED_FUND", "allocation", "", cached)
        result = fetch_fund_allocation("CACHED_FUND", conn=db_conn)
        assert result["by_sector"][0]["weight"] == 1.0


# ---------------------------------------------------------------------------
# normalize_sector
# ---------------------------------------------------------------------------

class TestNormalizeSector:
    def test_standard_mapping(self):
        assert normalize_sector("科技") == "資訊科技"
        assert normalize_sector("金融服務") == "金融"
        assert normalize_sector("原物料") == "原材料"

    def test_passthrough_unknown(self):
        assert normalize_sector("未知分類") == "未知分類"

    def test_already_standard(self):
        assert normalize_sector("資訊科技") == "資訊科技"
        assert normalize_sector("金融") == "金融"


# ---------------------------------------------------------------------------
# Known funds coverage
# ---------------------------------------------------------------------------

class TestKnownFunds:
    def test_at_least_ten(self):
        assert len(_KNOWN_FUNDS) >= 10

    def test_required_fields(self):
        for f in _KNOWN_FUNDS:
            assert "fund_id" in f
            assert "fund_name" in f
            assert "fund_house" in f
            assert "currency" in f

    def test_diverse_types(self):
        types = {f["fund_type"] for f in _KNOWN_FUNDS}
        assert len(types) >= 3  # at least 3 different fund types

    def test_diverse_regions(self):
        regions = {f["region"] for f in _KNOWN_FUNDS}
        assert len(regions) >= 2


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_and_retrieve(self, db_conn):
        data = {"key": "value"}
        _cache_json(db_conn, "F001", "test", "", data)
        result = _get_cached_json(db_conn, "F001", "test", "")
        assert result == data

    def test_cache_miss(self, db_conn):
        result = _get_cached_json(db_conn, "MISSING", "test", "")
        assert result is None

    def test_cache_overwrite(self, db_conn):
        _cache_json(db_conn, "F001", "test", "", {"v": 1})
        _cache_json(db_conn, "F001", "test", "", {"v": 2})
        result = _get_cached_json(db_conn, "F001", "test", "")
        assert result["v"] == 2


# ---------------------------------------------------------------------------
# Sector mapping coverage
# ---------------------------------------------------------------------------

class TestSectorMapping:
    def test_common_sectors_mapped(self):
        common = ["科技", "金融", "通訊", "原物料", "醫療保健", "能源"]
        for s in common:
            assert normalize_sector(s) in [
                "資訊科技", "金融", "通訊服務", "原材料", "醫療保健", "能源"
            ]
