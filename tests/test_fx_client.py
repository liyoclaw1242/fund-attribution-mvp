"""Tests for data/fx_client.py — FX rate client."""

import sqlite3
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data.fx_client import (
    get_exchange_rate,
    convert_amount,
    get_fx_history,
    adjust_returns_for_fx,
    SUPPORTED_CURRENCIES,
    _FALLBACK_RATES,
    _cache_rate,
    _get_cached_rate,
    _validate_currency,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite DB with fx_rate_cache table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE fx_rate_cache (
            pair TEXT NOT NULL,
            date TEXT NOT NULL,
            rate REAL NOT NULL,
            fetched_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (pair, date)
        )
    """)
    return conn


@pytest.fixture
def seeded_conn(db_conn):
    """DB with pre-cached rates."""
    rates = [
        ("USDTWD", "20260407", 32.50),
        ("USDTWD", "20260406", 32.45),
        ("USDTWD", "20260405", 32.40),
        ("EURTWD", "20260407", 35.20),
        ("JPYTWD", "20260407", 0.218),
        ("CNYTWD", "20260407", 4.48),
        ("HKDTWD", "20260407", 4.16),
        ("GBPTWD", "20260407", 41.30),
    ]
    for pair, dt, rate in rates:
        _cache_rate(db_conn, pair, dt, rate)
    return db_conn


# ---------------------------------------------------------------------------
# Currency validation
# ---------------------------------------------------------------------------

class TestCurrencyValidation:
    def test_all_supported(self):
        for code in SUPPORTED_CURRENCIES:
            _validate_currency(code)  # should not raise

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported currency"):
            _validate_currency("XYZ")

    def test_lowercase_rejected(self):
        # get_exchange_rate uppercases, but _validate_currency expects uppercase
        with pytest.raises(ValueError):
            _validate_currency("usd")


# ---------------------------------------------------------------------------
# get_exchange_rate
# ---------------------------------------------------------------------------

class TestGetExchangeRate:
    def test_same_currency(self):
        assert get_exchange_rate("USD", "USD") == 1.0
        assert get_exchange_rate("TWD", "TWD") == 1.0

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_usd_to_twd_from_cache(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("USD", "TWD", "20260407", seeded_conn)
        assert rate == pytest.approx(32.50)

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_eur_to_twd_from_cache(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("EUR", "TWD", "20260407", seeded_conn)
        assert rate == pytest.approx(35.20)

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_twd_to_usd_inverse(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("TWD", "USD", "20260407", seeded_conn)
        assert rate == pytest.approx(1.0 / 32.50)

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_cross_rate(self, mock_bot, seeded_conn):
        # USD/EUR via TWD: USD→TWD / EUR→TWD
        rate = get_exchange_rate("USD", "EUR", "20260407", seeded_conn)
        expected = 32.50 / 35.20
        assert rate == pytest.approx(expected, rel=1e-4)

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_jpy_to_twd(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("JPY", "TWD", "20260407", seeded_conn)
        assert rate == pytest.approx(0.218)

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_case_insensitive(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("usd", "twd", "20260407", seeded_conn)
        assert rate == pytest.approx(32.50)

    def test_unsupported_currency_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_exchange_rate("BTC", "TWD")

    def test_fallback_when_no_cache_no_api(self):
        """When no cache and API fails, use fallback rates."""
        with patch("data.fx_client._fetch_bot_rate", side_effect=Exception("API down")):
            rate = get_exchange_rate("USD", "TWD", "20260407")
            assert 28.0 <= rate <= 40.0  # fallback should be reasonable

    @patch("data.fx_client._fetch_bot_rate", side_effect=Exception("no network"))
    def test_rate_in_reasonable_range(self, mock_bot, seeded_conn):
        rate = get_exchange_rate("USD", "TWD", "20260407", seeded_conn)
        assert 28.0 <= rate <= 40.0


# ---------------------------------------------------------------------------
# convert_amount
# ---------------------------------------------------------------------------

class TestConvertAmount:
    def test_usd_to_twd(self, seeded_conn):
        result = convert_amount(100.0, "USD", "TWD", "20260407", seeded_conn)
        assert result == pytest.approx(3250.0)

    def test_twd_to_usd(self, seeded_conn):
        result = convert_amount(3250.0, "TWD", "USD", "20260407", seeded_conn)
        assert result == pytest.approx(100.0, rel=1e-4)

    def test_same_currency_no_change(self):
        assert convert_amount(500.0, "TWD", "TWD") == 500.0

    def test_zero_amount(self, seeded_conn):
        assert convert_amount(0.0, "USD", "TWD", "20260407", seeded_conn) == 0.0


# ---------------------------------------------------------------------------
# adjust_returns_for_fx
# ---------------------------------------------------------------------------

class TestAdjustReturnsForFx:
    def test_same_currency_no_adjustment(self):
        df = pd.DataFrame({
            "date": ["20260407"],
            "return_rate": [0.05],
        })
        result = adjust_returns_for_fx(df, "TWD", "TWD")

        assert result["return_rate_twd"].iloc[0] == pytest.approx(0.05)
        assert result["fx_contribution"].iloc[0] == pytest.approx(0.0)

    def test_precise_formula(self, seeded_conn):
        """Verify (1 + R_foreign) * (1 + R_fx) - 1."""
        df = pd.DataFrame({
            "date": ["20260406", "20260407"],
            "return_rate": [0.0, 0.02],  # 2% foreign return on day 2
        })
        result = adjust_returns_for_fx(df, "USD", "TWD", seeded_conn)

        # Day 1: no prev rate, fx_contribution = 0
        assert result["fx_contribution"].iloc[0] == pytest.approx(0.0)

        # Day 2: fx change = (32.50 - 32.45) / 32.45
        r_fx = (32.50 - 32.45) / 32.45
        r_twd = (1 + 0.02) * (1 + r_fx) - 1
        fx_contrib = r_twd - 0.02

        assert result["return_rate_twd"].iloc[1] == pytest.approx(r_twd, rel=1e-4)
        assert result["fx_contribution"].iloc[1] == pytest.approx(fx_contrib, rel=1e-4)

    def test_approx_vs_precise_small_error(self, seeded_conn):
        """Approximation error should be < 0.01%."""
        df = pd.DataFrame({
            "date": ["20260406", "20260407"],
            "return_rate": [0.0, 0.03],
        })
        result = adjust_returns_for_fx(df, "USD", "TWD", seeded_conn)

        r_foreign = 0.03
        r_fx = (32.50 - 32.45) / 32.45
        r_twd_precise = (1 + r_foreign) * (1 + r_fx) - 1
        r_twd_approx = r_foreign + r_fx

        error = abs(r_twd_precise - r_twd_approx)
        assert error < 0.0001  # < 0.01%

    def test_output_columns(self, seeded_conn):
        df = pd.DataFrame({
            "date": ["20260407"],
            "return_rate": [0.01],
        })
        result = adjust_returns_for_fx(df, "USD", "TWD", seeded_conn)

        assert "return_rate_foreign" in result.columns
        assert "fx_rate" in result.columns
        assert "return_rate_twd" in result.columns
        assert "fx_contribution" in result.columns


# ---------------------------------------------------------------------------
# Cache operations
# ---------------------------------------------------------------------------

class TestCache:
    def test_cache_and_retrieve(self, db_conn):
        _cache_rate(db_conn, "USDTWD", "20260407", 32.50)
        cached = _get_cached_rate(db_conn, "USDTWD", "20260407")
        assert cached == pytest.approx(32.50)

    def test_cache_miss(self, db_conn):
        cached = _get_cached_rate(db_conn, "USDTWD", "20260407")
        assert cached is None

    def test_cache_update(self, db_conn):
        _cache_rate(db_conn, "USDTWD", "20260407", 32.50)
        _cache_rate(db_conn, "USDTWD", "20260407", 32.55)
        cached = _get_cached_rate(db_conn, "USDTWD", "20260407")
        assert cached == pytest.approx(32.55)


# ---------------------------------------------------------------------------
# Supported currencies count
# ---------------------------------------------------------------------------

class TestSupportedCurrencies:
    def test_at_least_seven(self):
        assert len(SUPPORTED_CURRENCIES) >= 7

    def test_twd_included(self):
        assert "TWD" in SUPPORTED_CURRENCIES

    def test_major_currencies(self):
        for code in ["USD", "EUR", "JPY", "CNY", "HKD", "GBP"]:
            assert code in SUPPORTED_CURRENCIES


# ---------------------------------------------------------------------------
# Fallback rates sanity
# ---------------------------------------------------------------------------

class TestFallbackRates:
    def test_usd_twd_reasonable(self):
        assert 28.0 <= _FALLBACK_RATES["USDTWD"] <= 40.0

    def test_jpy_twd_reasonable(self):
        assert 0.15 <= _FALLBACK_RATES["JPYTWD"] <= 0.35

    def test_all_pairs_have_fallback(self):
        for code in ["USD", "EUR", "JPY", "CNY", "HKD", "GBP"]:
            assert f"{code}TWD" in _FALLBACK_RATES
