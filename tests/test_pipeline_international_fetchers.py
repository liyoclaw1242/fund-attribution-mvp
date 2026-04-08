"""Tests for international fetchers — Finnhub, yfinance, FX."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pipeline.fetchers.finnhub_ import FinnhubFetcher
from pipeline.fetchers.yfinance_ import YfinanceFetcher, YfinanceInfoFetcher, GICS_TO_UNIFIED
from pipeline.fetchers.fx import FxRateFetcher, DEFAULT_PAIRS


def _make_pool_with_conn(mock_conn):
    mock_pool = MagicMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire.return_value = cm
    return mock_pool


# --- Finnhub ---

class TestFinnhubFetcher:
    def test_init_warns_without_key(self):
        with patch("pipeline.fetchers.finnhub_.PipelineConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.finnhub_api_key = ""
            mock_cfg_cls.from_env.return_value = mock_cfg
            f = FinnhubFetcher(config=mock_cfg)
            assert f.api_key == ""

    @pytest.mark.asyncio
    async def test_fetch_skips_without_key(self):
        with patch("pipeline.fetchers.finnhub_.PipelineConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.finnhub_api_key = ""
            mock_cfg_cls.from_env.return_value = mock_cfg
            f = FinnhubFetcher(config=mock_cfg)
            result = await f.fetch({"fund_ids": ["US123"]})
            assert result == []

    @pytest.mark.asyncio
    async def test_fetch_skips_without_fund_ids(self):
        with patch("pipeline.fetchers.finnhub_.PipelineConfig") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.finnhub_api_key = "test_key"
            mock_cfg_cls.from_env.return_value = mock_cfg
            f = FinnhubFetcher(config=mock_cfg)
            result = await f.fetch({})
            assert result == []

    def test_transform_empty(self):
        f = FinnhubFetcher.__new__(FinnhubFetcher)
        df = f.transform([])
        assert df.empty

    def test_transform_normalizes_columns(self):
        f = FinnhubFetcher.__new__(FinnhubFetcher)
        raw = [{
            "fund_id": "US123",
            "as_of_date": "2026-03-31",
            "stock_id": "AAPL",
            "stock_name": "Apple Inc",
            "weight": 0.05,
            "asset_type": "equity",
            "sector": "Technology",
            "source": "finnhub",
        }]
        df = f.transform(raw)
        assert list(df.columns) == [
            "fund_id", "as_of_date", "stock_id", "stock_name",
            "weight", "asset_type", "sector", "source",
        ]
        assert len(df) == 1

    def test_source_name(self):
        assert FinnhubFetcher.source_name == "finnhub"
        assert FinnhubFetcher.target_table == "fund_holding"


# --- yfinance ---

class TestYfinanceFetcher:
    def test_default_tickers(self):
        f = YfinanceFetcher()
        assert len(f.tickers) > 0
        assert "AAPL" in f.tickers

    def test_custom_tickers(self):
        f = YfinanceFetcher(tickers=["TSLA", "NVDA"])
        assert f.tickers == ["TSLA", "NVDA"]

    def test_transform_empty(self):
        f = YfinanceFetcher()
        df = f.transform([])
        assert df.empty

    def test_transform_normalizes_columns(self):
        f = YfinanceFetcher()
        raw = [{
            "stock_id": "US_AAPL",
            "date": "2026-04-07",
            "close_price": 195.50,
            "change_pct": 0.012,
            "volume": 50000000,
            "market_cap": None,
            "source": "yfinance",
        }]
        df = f.transform(raw)
        assert list(df.columns) == [
            "stock_id", "date", "close_price", "change_pct",
            "volume", "market_cap", "source",
        ]

    def test_source_name(self):
        assert YfinanceFetcher.source_name == "yfinance"
        assert YfinanceFetcher.target_table == "stock_price"


class TestYfinanceInfoFetcher:
    def test_source_name(self):
        assert YfinanceInfoFetcher.source_name == "yfinance_info"
        assert YfinanceInfoFetcher.target_table == "stock_info"

    def test_gics_mapping_has_entries(self):
        assert len(GICS_TO_UNIFIED) > 0
        assert "Technology" in GICS_TO_UNIFIED


# --- FX ---

class TestFxRateFetcher:
    def test_default_pairs(self):
        f = FxRateFetcher()
        assert "USDTWD" in f.pairs
        assert len(f.pairs) == len(DEFAULT_PAIRS)

    def test_custom_pairs(self):
        f = FxRateFetcher(pairs=["USDTWD", "EURTWD"])
        assert f.pairs == ["USDTWD", "EURTWD"]

    def test_transform_empty(self):
        f = FxRateFetcher()
        df = f.transform([])
        assert df.empty

    def test_transform_normalizes_columns(self):
        f = FxRateFetcher()
        raw = [{"pair": "USDTWD", "date": "2026-04-08", "rate": 32.15, "source": "exchangerate_host"}]
        df = f.transform(raw)
        assert list(df.columns) == ["pair", "date", "rate", "source"]
        assert len(df) == 1

    @pytest.mark.asyncio
    async def test_fetch_rate_uses_fallback(self):
        """When API fails, fallback rates are used."""
        f = FxRateFetcher(pairs=["USDTWD"])

        with patch.object(f, "_fetch_from_api", new_callable=AsyncMock, side_effect=Exception("API down")):
            rate = await f._fetch_rate("USDTWD", "2026-04-08")

        assert rate is not None
        assert rate > 0

    def test_source_name(self):
        assert FxRateFetcher.source_name == "fx_rate"
        assert FxRateFetcher.target_table == "fx_rate"
