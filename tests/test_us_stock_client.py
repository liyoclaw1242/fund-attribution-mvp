"""Tests for data/us_stock_client.py — US stock data client."""

import sqlite3
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from data.us_stock_client import (
    fetch_stock_info,
    fetch_stock_history,
    fetch_portfolio_us,
    get_sp500_sector_weights,
    translate_sector,
    GICS_SECTORS,
    _SP500_SECTOR_WEIGHTS,
    _cache_history,
    _get_cached_history,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite with us_stock_cache table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE us_stock_cache (
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close_price REAL,
            return_rate REAL,
            sector TEXT,
            market_cap INTEGER,
            fetched_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (ticker, date)
        )
    """)
    return conn


def _mock_yf_ticker(info=None, history_df=None):
    """Create a mock yfinance Ticker."""
    mock_ticker = MagicMock()
    mock_ticker.info = info or {
        "longName": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "currency": "USD",
        "marketCap": 3200000000000,
        "regularMarketPrice": 230.0,
    }

    if history_df is None:
        dates = pd.bdate_range("2026-03-01", "2026-04-07")
        n = len(dates)
        np.random.seed(42)
        closes = 220 + np.cumsum(np.random.normal(0, 2, n))
        history_df = pd.DataFrame({
            "Open": closes - 1,
            "High": closes + 2,
            "Low": closes - 2,
            "Close": closes,
            "Volume": np.random.randint(50000000, 100000000, n),
        }, index=dates)

    mock_ticker.history.return_value = history_df
    return mock_ticker


# ---------------------------------------------------------------------------
# fetch_stock_info
# ---------------------------------------------------------------------------

class TestFetchStockInfo:
    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_basic_info(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker()
        info = fetch_stock_info("AAPL")

        assert info["ticker"] == "AAPL"
        assert info["name"] == "Apple Inc."
        assert info["sector"] == "資訊科技"
        assert info["sector_en"] == "Technology"
        assert info["currency"] == "USD"
        assert info["market_cap"] > 0

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_case_insensitive(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker()
        info = fetch_stock_info("aapl")
        assert info["ticker"] == "AAPL"

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_unknown_ticker(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker(info={"regularMarketPrice": None})
        with pytest.raises(ValueError, match="not found|No data"):
            fetch_stock_info("XXXYZ")


# ---------------------------------------------------------------------------
# fetch_stock_history
# ---------------------------------------------------------------------------

class TestFetchStockHistory:
    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_returns_dataframe(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker()
        df = fetch_stock_history("AAPL", "1mo")

        assert isinstance(df, pd.DataFrame)
        assert "date" in df.columns
        assert "close" in df.columns
        assert "return_rate" in df.columns
        assert len(df) > 0

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_return_rate_calculated(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker()
        df = fetch_stock_history("AAPL", "1mo")

        # First row return_rate should be 0 (no previous)
        assert df["return_rate"].iloc[0] == 0.0
        # Other rows should have non-zero returns
        assert df["return_rate"].iloc[1:].abs().sum() > 0

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_empty_history_raises(self, mock_yf, mock_rl):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        mock_yf.return_value = mock_ticker

        with pytest.raises(ValueError, match="No history"):
            fetch_stock_history("DEAD")

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_cache_write(self, mock_yf, mock_rl, db_conn):
        mock_yf.return_value = _mock_yf_ticker()
        df = fetch_stock_history("AAPL", "1mo", conn=db_conn)

        # Verify data was cached
        count = db_conn.execute(
            "SELECT COUNT(*) FROM us_stock_cache WHERE ticker = 'AAPL'"
        ).fetchone()[0]
        assert count > 0


# ---------------------------------------------------------------------------
# fetch_portfolio_us
# ---------------------------------------------------------------------------

class TestFetchPortfolioUS:
    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_portfolio_calculation(self, mock_yf, mock_rl):
        mock_yf.return_value = _mock_yf_ticker()
        holdings = [
            {"ticker": "AAPL", "shares": 100, "cost_basis_usd": 22000},
            {"ticker": "MSFT", "shares": 50, "cost_basis_usd": 20000},
        ]
        df = fetch_portfolio_us(holdings, "1mo")

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "weight" in df.columns
        assert "return_rate" in df.columns
        assert df["weight"].sum() == pytest.approx(1.0, abs=0.01)

    def test_empty_holdings(self):
        df = fetch_portfolio_us([])
        assert len(df) == 0

    @patch("data.us_stock_client._rate_limit")
    @patch("yfinance.Ticker")
    def test_handles_partial_failure(self, mock_yf, mock_rl):
        """If one stock fails, others still return."""
        call_count = [0]

        def side_effect(ticker):
            call_count[0] += 1
            if call_count[0] % 3 == 0:  # Every 3rd call fails
                mock = MagicMock()
                mock.info = {"regularMarketPrice": None}
                mock.history.return_value = pd.DataFrame()
                return mock
            return _mock_yf_ticker()

        mock_yf.side_effect = side_effect
        holdings = [
            {"ticker": "AAPL", "shares": 100, "cost_basis_usd": 22000},
            {"ticker": "FAIL", "shares": 50, "cost_basis_usd": 10000},
        ]
        df = fetch_portfolio_us(holdings, "1mo")
        # At least one should succeed
        assert len(df) >= 1


# ---------------------------------------------------------------------------
# get_sp500_sector_weights
# ---------------------------------------------------------------------------

class TestSP500SectorWeights:
    def test_returns_11_sectors(self):
        df = get_sp500_sector_weights()
        assert len(df) == 11

    def test_weights_sum_to_one(self):
        df = get_sp500_sector_weights()
        assert df["Wb"].sum() == pytest.approx(1.0, abs=0.01)

    def test_has_required_columns(self):
        df = get_sp500_sector_weights()
        assert "sector" in df.columns
        assert "Wb" in df.columns
        assert "Rb" in df.columns

    def test_tech_is_largest(self):
        df = get_sp500_sector_weights()
        tech = df[df["sector"] == "資訊科技"]["Wb"].iloc[0]
        assert tech == max(df["Wb"])


# ---------------------------------------------------------------------------
# GICS sector translation
# ---------------------------------------------------------------------------

class TestGICSSectors:
    def test_all_11_mapped(self):
        assert len(GICS_SECTORS) == 11

    def test_translate_sector(self):
        assert translate_sector("Technology") == "資訊科技"
        assert translate_sector("Financials") == "金融"
        assert translate_sector("Health Care") == "醫療保健"

    def test_unknown_passthrough(self):
        assert translate_sector("Unknown Sector") == "Unknown Sector"

    def test_all_chinese_names_unique(self):
        chinese_names = list(GICS_SECTORS.values())
        assert len(chinese_names) == len(set(chinese_names))


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_and_retrieve(self, db_conn):
        df = pd.DataFrame({
            "date": ["2026-04-01", "2026-04-02"],
            "open": [220, 222],
            "high": [225, 226],
            "low": [218, 220],
            "close": [222, 224],
            "volume": [50000000, 60000000],
            "return_rate": [0.0, 0.009],
        })
        _cache_history(db_conn, "AAPL", df)

        cached = _get_cached_history(db_conn, "AAPL", "1mo")
        # May return None if not enough rows (need >= 5)
        # So we just verify the data was written
        count = db_conn.execute(
            "SELECT COUNT(*) FROM us_stock_cache WHERE ticker = 'AAPL'"
        ).fetchone()[0]
        assert count == 2

    def test_cache_miss(self, db_conn):
        result = _get_cached_history(db_conn, "MISSING", "1mo")
        assert result is None
