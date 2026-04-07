"""Tests for data/sitca_scraper.py — SITCA fund holdings scraper."""

import sqlite3
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data.sitca_scraper import (
    fetch_fund_holdings,
    fetch_fund_returns,
    list_companies,
    list_fund_types,
    _parse_holdings_html,
    _parse_returns_html,
    _normalize_holdings_df,
    COMPANY_CODES,
    FUND_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite with fund_holdings table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
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
        )
    """)
    return conn


# Sample HTML mimicking SITCA table structure
SAMPLE_HOLDINGS_HTML = """
<html><body>
<table class="grid">
<tr><th>基金名稱</th><th>產業</th><th>比重(%)</th></tr>
<tr><td>元大台灣50</td><td>半導體業</td><td>42.5</td></tr>
<tr><td>元大台灣50</td><td>金融保險業</td><td>18.3</td></tr>
<tr><td>元大台灣50</td><td>電子零組件業</td><td>12.1</td></tr>
<tr><td>元大台灣50</td><td>其他</td><td>27.1</td></tr>
</table>
</body></html>
"""

SAMPLE_RETURNS_HTML = """
<html><body>
<table class="grid">
<tr><th>基金名稱</th><th>一個月</th><th>三個月</th><th>六個月</th><th>一年</th></tr>
<tr><td>元大台灣50</td><td>2.5%</td><td>8.1%</td><td>12.3%</td><td>18.5%</td></tr>
<tr><td>元大高股息</td><td>1.2%</td><td>3.5%</td><td>6.8%</td><td>10.2%</td></tr>
</table>
</body></html>
"""


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class TestParseHoldingsHtml:
    def test_parses_table(self):
        df = _parse_holdings_html(SAMPLE_HOLDINGS_HTML)
        assert len(df) == 4
        assert "industry" in df.columns
        assert "weight" in df.columns

    def test_weights_are_decimal(self):
        df = _parse_holdings_html(SAMPLE_HOLDINGS_HTML)
        # 42.5% → 0.425
        semi = df[df["industry"] == "半導體業"]["weight"].iloc[0]
        assert semi == pytest.approx(0.425)

    def test_weights_sum_reasonable(self):
        df = _parse_holdings_html(SAMPLE_HOLDINGS_HTML)
        total = df["weight"].sum()
        assert total == pytest.approx(1.0, abs=0.05)

    def test_fund_name_present(self):
        df = _parse_holdings_html(SAMPLE_HOLDINGS_HTML)
        assert "fund_name" in df.columns
        assert "元大台灣50" in df["fund_name"].values


class TestParseReturnsHtml:
    def test_parses_returns(self):
        df = _parse_returns_html(SAMPLE_RETURNS_HTML)
        assert len(df) == 2
        assert "fund_name" in df.columns

    def test_return_columns(self):
        df = _parse_returns_html(SAMPLE_RETURNS_HTML)
        assert "return_1m" in df.columns
        assert "return_1y" in df.columns

    def test_returns_are_decimal(self):
        df = _parse_returns_html(SAMPLE_RETURNS_HTML)
        r1m = df[df["fund_name"].str.contains("台灣50")]["return_1m"].iloc[0]
        assert r1m == pytest.approx(0.025)


# ---------------------------------------------------------------------------
# Normalize DataFrame
# ---------------------------------------------------------------------------

class TestNormalizeHoldingsDf:
    def test_percentage_to_decimal(self):
        raw = pd.DataFrame({
            "基金名稱": ["Fund A"],
            "產業": ["Tech"],
            "比重(%)": ["45.2%"],
        })
        result = _normalize_holdings_df(raw)
        assert result["weight"].iloc[0] == pytest.approx(0.452)

    def test_filters_zero_weight(self):
        raw = pd.DataFrame({
            "基金名稱": ["Fund A", "Fund A"],
            "產業": ["Tech", "Cash"],
            "比重(%)": ["95.0", "0"],
        })
        result = _normalize_holdings_df(raw)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Company and fund type lookups
# ---------------------------------------------------------------------------

class TestLookups:
    def test_has_companies(self):
        companies = list_companies()
        assert len(companies) >= 5
        assert "A0005" in companies  # 元大

    def test_has_fund_types(self):
        types = list_fund_types()
        assert len(types) >= 3
        assert "AA1" in types  # 國內股票型


# ---------------------------------------------------------------------------
# Fetch with mock scraper
# ---------------------------------------------------------------------------

class TestFetchFundHoldings:
    @patch("data.sitca_scraper._scrape_holdings")
    def test_returns_from_scraper(self, mock_scrape):
        mock_scrape.return_value = pd.DataFrame({
            "fund_name": ["元大台灣50", "元大台灣50"],
            "industry": ["半導體業", "金融保險業"],
            "weight": [0.425, 0.183],
        })
        df = fetch_fund_holdings("A0005", period="202603")
        assert len(df) == 2
        assert df["weight"].sum() > 0

    @patch("data.sitca_scraper._scrape_holdings", side_effect=Exception("SITCA down"))
    @patch("data.sitca_scraper._fallback_holdings")
    def test_fallback_on_failure(self, mock_fallback, mock_scrape):
        mock_fallback.return_value = pd.DataFrame({
            "fund_name": ["Fallback Fund"],
            "industry": ["Tech"],
            "weight": [1.0],
        })
        df = fetch_fund_holdings("A0005", period="202603")
        assert len(df) == 1
        mock_fallback.assert_called_once()

    @patch("data.sitca_scraper._scrape_holdings")
    def test_cache_write(self, mock_scrape, db_conn):
        mock_scrape.return_value = pd.DataFrame({
            "fund_name": ["Fund"],
            "industry": ["半導體業"],
            "weight": [0.5],
        })
        fetch_fund_holdings("A0005", period="202603", conn=db_conn)

        count = db_conn.execute(
            "SELECT COUNT(*) FROM fund_holdings WHERE fund_code = 'A0005'"
        ).fetchone()[0]
        assert count > 0


class TestFetchFundReturns:
    @patch("data.sitca_scraper._scrape_returns")
    def test_returns_from_scraper(self, mock_scrape):
        mock_scrape.return_value = pd.DataFrame({
            "fund_name": ["元大台灣50"],
            "return_1m": [0.025],
            "return_3m": [0.081],
            "return_6m": [0.123],
            "return_1y": [0.185],
        })
        df = fetch_fund_returns("A0005", period="202603")
        assert len(df) == 1
        assert "return_1m" in df.columns

    @patch("data.sitca_scraper._scrape_returns", side_effect=Exception("SITCA down"))
    def test_empty_on_failure(self, mock_scrape):
        df = fetch_fund_returns("A0005", period="202603")
        assert len(df) == 0
        assert "fund_name" in df.columns


# ---------------------------------------------------------------------------
# Company codes coverage
# ---------------------------------------------------------------------------

class TestCompanyCodes:
    def test_at_least_five(self):
        assert len(COMPANY_CODES) >= 5

    def test_yuanta(self):
        assert "A0005" in COMPANY_CODES
        assert "元大" in COMPANY_CODES["A0005"]

    def test_fubon(self):
        assert "A0010" in COMPANY_CODES
        assert "富邦" in COMPANY_CODES["A0010"]
