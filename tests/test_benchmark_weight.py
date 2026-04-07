"""Tests for data/benchmark_weight.py — Wb auto-calculation."""

import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

from data.benchmark_weight import (
    compute_industry_weights,
    _compute_weights,
    _cache_weights,
    _get_cached_weights,
    INDUSTRY_CODE_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite with benchmark_weight table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE benchmark_weight (
            industry TEXT NOT NULL,
            date TEXT NOT NULL,
            weight REAL NOT NULL,
            market_cap INTEGER,
            fetched_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (industry, date)
        )
    """)
    return conn


def _mock_companies():
    """Mock company list data."""
    return pd.DataFrame([
        {"stock_code": "2330", "industry_code": "14", "shares": 25930380000},  # TSMC - 半導體
        {"stock_code": "2317", "industry_code": "18", "shares": 13883700000},  # 鴻海 - 電子零組件
        {"stock_code": "2882", "industry_code": "25", "shares": 12900000000},  # 國泰金 - 金融保險
        {"stock_code": "1301", "industry_code": "03", "shares": 5876100000},   # 台塑 - 塑膠
        {"stock_code": "2412", "industry_code": "17", "shares": 7757700000},   # 中華電 - 通信網路
    ])


def _mock_prices():
    """Mock stock prices data."""
    return pd.DataFrame([
        {"stock_code": "2330", "closing_price": 980.0},
        {"stock_code": "2317", "closing_price": 180.0},
        {"stock_code": "2882", "closing_price": 65.0},
        {"stock_code": "1301", "closing_price": 80.0},
        {"stock_code": "2412", "closing_price": 125.0},
    ])


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

class TestComputeWeights:
    def test_weights_sum_to_one(self):
        result = _compute_weights(_mock_companies(), _mock_prices())
        assert result["Wb"].sum() == pytest.approx(1.0, abs=0.001)

    def test_tsmc_is_largest(self):
        result = _compute_weights(_mock_companies(), _mock_prices())
        # TSMC market cap = 25.9B × 980 ≈ 25.4T
        semi = result[result["industry"] == "半導體"]
        assert len(semi) == 1
        assert semi["Wb"].iloc[0] == max(result["Wb"])

    def test_has_industry_names(self):
        result = _compute_weights(_mock_companies(), _mock_prices())
        assert "半導體" in result["industry"].values
        assert "金融保險" in result["industry"].values

    def test_market_cap_positive(self):
        result = _compute_weights(_mock_companies(), _mock_prices())
        assert (result["market_cap"] > 0).all()

    def test_correct_number_of_industries(self):
        result = _compute_weights(_mock_companies(), _mock_prices())
        # 5 stocks across 5 different industries
        assert len(result) == 5

    def test_empty_companies(self):
        result = _compute_weights(pd.DataFrame(), _mock_prices())
        assert len(result) == 0

    def test_empty_prices(self):
        result = _compute_weights(_mock_companies(), pd.DataFrame())
        assert len(result) == 0

    def test_no_matching_stocks(self):
        companies = pd.DataFrame([
            {"stock_code": "9999", "industry_code": "01", "shares": 1000000},
        ])
        prices = pd.DataFrame([
            {"stock_code": "1111", "closing_price": 100.0},
        ])
        result = _compute_weights(companies, prices)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Full compute with mocked API
# ---------------------------------------------------------------------------

class TestComputeIndustryWeights:
    @patch("data.benchmark_weight._fetch_stock_prices")
    @patch("data.benchmark_weight._fetch_company_list")
    def test_full_computation(self, mock_companies, mock_prices):
        mock_companies.return_value = _mock_companies()
        mock_prices.return_value = _mock_prices()

        result = compute_industry_weights(target_date="20260407")
        assert isinstance(result, pd.DataFrame)
        assert result["Wb"].sum() == pytest.approx(1.0, abs=0.001)

    @patch("data.benchmark_weight._fetch_stock_prices")
    @patch("data.benchmark_weight._fetch_company_list")
    def test_caches_result(self, mock_companies, mock_prices, db_conn):
        mock_companies.return_value = _mock_companies()
        mock_prices.return_value = _mock_prices()

        compute_industry_weights(conn=db_conn, target_date="20260407")

        count = db_conn.execute(
            "SELECT COUNT(*) FROM benchmark_weight WHERE date = '20260407'"
        ).fetchone()[0]
        assert count > 0

    @patch("data.benchmark_weight._fetch_stock_prices", return_value=pd.DataFrame())
    @patch("data.benchmark_weight._fetch_company_list", return_value=pd.DataFrame())
    def test_raises_when_no_data(self, mock_c, mock_p):
        with pytest.raises(ValueError, match="unavailable"):
            compute_industry_weights(target_date="20260407")

    @patch("data.benchmark_weight._fetch_stock_prices", return_value=pd.DataFrame())
    @patch("data.benchmark_weight._fetch_company_list", return_value=pd.DataFrame())
    def test_uses_expired_cache_as_fallback(self, mock_c, mock_p, db_conn):
        # Seed expired cache
        db_conn.execute(
            "INSERT INTO benchmark_weight VALUES (?, ?, ?, ?, '2020-01-01 00:00:00')",
            ("半導體", "20260407", 0.5, 25000000000000),
        )
        db_conn.execute(
            "INSERT INTO benchmark_weight VALUES (?, ?, ?, ?, '2020-01-01 00:00:00')",
            ("金融保險", "20260407", 0.5, 25000000000000),
        )
        db_conn.commit()

        result = compute_industry_weights(conn=db_conn, target_date="20260407")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Industry code mapping
# ---------------------------------------------------------------------------

class TestIndustryCodeMap:
    def test_has_semiconductor(self):
        assert INDUSTRY_CODE_MAP.get("14") == "半導體"

    def test_has_finance(self):
        assert INDUSTRY_CODE_MAP.get("25") == "金融保險"

    def test_at_least_28_entries(self):
        assert len(INDUSTRY_CODE_MAP) >= 28


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

class TestCache:
    @patch("data.benchmark_weight._fetch_stock_prices")
    @patch("data.benchmark_weight._fetch_company_list")
    def test_cache_hit_skips_api(self, mock_c, mock_p, db_conn):
        # Seed fresh cache
        db_conn.execute(
            "INSERT INTO benchmark_weight VALUES (?, ?, ?, ?, datetime('now'))",
            ("半導體", "20260407", 0.6, 25000000000000),
        )
        db_conn.execute(
            "INSERT INTO benchmark_weight VALUES (?, ?, ?, ?, datetime('now'))",
            ("金融保險", "20260407", 0.4, 15000000000000),
        )
        db_conn.commit()

        result = compute_industry_weights(conn=db_conn, target_date="20260407")
        assert len(result) == 2
        mock_c.assert_not_called()
        mock_p.assert_not_called()
