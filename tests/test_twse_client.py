"""Tests for data/twse_client.py — TWSE API client, rate limiting, cache, fallback."""

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from data.twse_client import (
    RateLimiter,
    fetch_mi_index,
    get_industry_indices,
    _parse_mi_index,
    _load_fallback_csv,
)

# Sample MI_INDEX API response (minimal subset)
SAMPLE_MI_INDEX_RAW = [
    {"日期": "1150402", "指數": "發行量加權股價指數", "收盤指數": "32572.43", "漲跌": "-", "漲跌點數": "602.39", "漲跌百分比": "-1.82", "特殊處理註記": ""},
    {"日期": "1150402", "指數": "半導體類指數", "收盤指數": "1,067.63", "漲跌": "-", "漲跌點數": "25.02", "漲跌百分比": "-2.29", "特殊處理註記": ""},
    {"日期": "1150402", "指數": "金融保險類指數", "收盤指數": "2,441.93", "漲跌": "+", "漲跌點數": "1.31", "漲跌百分比": "0.05", "特殊處理註記": ""},
    {"日期": "1150402", "指數": "航運類指數", "收盤指數": "176.99", "漲跌": "-", "漲跌點數": "1.96", "漲跌百分比": "-1.10", "特殊處理註記": ""},
    {"日期": "1150402", "指數": "臺灣50指數", "收盤指數": "29566.99", "漲跌": "-", "漲跌點數": "644.98", "漲跌百分比": "-2.13", "特殊處理註記": ""},
]


class TestRateLimiter:
    def test_enforces_delay(self):
        limiter = RateLimiter(min_delay=0.1)
        limiter.wait()
        t0 = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.09  # allow tiny tolerance

    def test_no_delay_on_first_call(self):
        limiter = RateLimiter(min_delay=1.0)
        t0 = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1  # first call should be instant


class TestParseMiIndex:
    def test_filters_industry_indices(self):
        records = _parse_mi_index(SAMPLE_MI_INDEX_RAW)
        # Should include 半導體, 金融保險, 航運 but NOT 發行量加權 or 臺灣50
        industries = {r["industry"] for r in records}
        assert "半導體" in industries
        assert "金融保險" in industries
        assert "航運" in industries
        assert len(records) == 3

    def test_parses_closing_price(self):
        records = _parse_mi_index(SAMPLE_MI_INDEX_RAW)
        semi = next(r for r in records if r["industry"] == "半導體")
        assert semi["closing_price"] == 1067.63

    def test_converts_change_pct_to_decimal(self):
        records = _parse_mi_index(SAMPLE_MI_INDEX_RAW)
        semi = next(r for r in records if r["industry"] == "半導體")
        assert semi["return_rate"] == pytest.approx(-0.0229)

    def test_handles_comma_in_numbers(self):
        records = _parse_mi_index(SAMPLE_MI_INDEX_RAW)
        fin = next(r for r in records if r["industry"] == "金融保險")
        assert fin["closing_price"] == 2441.93


class TestFallbackCSV:
    @pytest.fixture
    def csv_file(self, tmp_path):
        path = tmp_path / "fallback.csv"
        path.write_text("industry,weight,return_rate\n半導體,0.40,0.08\n金融保險,0.14,0.03\n")
        return path

    def test_loads_csv(self, csv_file):
        records = _load_fallback_csv(csv_file)
        assert len(records) == 2
        assert records[0]["industry"] == "半導體"
        assert records[0]["weight"] == 0.40

    def test_missing_csv_raises(self):
        with pytest.raises(FileNotFoundError):
            _load_fallback_csv("/nonexistent/file.csv")

    def test_empty_csv_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("industry,weight,return_rate\n")
        with pytest.raises(ValueError, match="empty"):
            _load_fallback_csv(path)


class TestGetIndustryIndices:
    def test_cache_hit_skips_api(self):
        """When cache has data, no HTTP request should be made."""
        from data.cache import get_connection, init_db, upsert_benchmark_index

        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test.db")
            init_db(db_path)
            conn = get_connection(db_path)

            # Pre-populate cache
            cached_data = [
                {"industry": "半導體", "weight": 0.40, "return_rate": 0.08},
                {"industry": "金融保險", "weight": 0.14, "return_rate": 0.03},
            ]
            upsert_benchmark_index(conn, "MI_INDEX", "latest", cached_data, ttl_hours=24)

            # Should return cached data without calling API
            with patch("data.twse_client.fetch_mi_index") as mock_fetch:
                result = get_industry_indices(conn=conn)
                mock_fetch.assert_not_called()

            assert len(result) == 2
            conn.close()

    def test_api_failure_uses_fallback(self, tmp_path):
        """When API fails, fallback CSV should be used."""
        csv_path = tmp_path / "fallback.csv"
        csv_path.write_text("industry,weight,return_rate\n半導體,0.40,0.08\n")

        with patch("data.twse_client.fetch_mi_index", side_effect=Exception("API down")):
            result = get_industry_indices(conn=None, fallback_csv=csv_path)

        assert len(result) == 1
        assert result[0]["industry"] == "半導體"

    def test_api_failure_no_fallback_raises(self):
        """When API fails and no fallback, should raise."""
        with patch("data.twse_client.fetch_mi_index", side_effect=Exception("API down")):
            with pytest.raises(Exception, match="API down"):
                get_industry_indices(conn=None, fallback_csv=None)


class TestRateLimitIntegration:
    def test_rapid_calls_are_throttled(self):
        """10 rapid calls with 0.05s delay should take at least 0.45s total."""
        limiter = RateLimiter(min_delay=0.05)
        t0 = time.monotonic()
        for _ in range(10):
            limiter.wait()
        elapsed = time.monotonic() - t0
        # 9 waits × 0.05s = 0.45s minimum (first call is instant)
        assert elapsed >= 0.40  # allow small tolerance
