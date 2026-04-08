"""Tests for Taiwan market fetchers — TWSE, SITCA, FinMind."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pipeline.fetchers.twse import (
    TwseCompanyInfoFetcher,
    TwseMiIndexFetcher,
    TwseStockDayAllFetcher,
    TSE_INDUSTRY_INDICES,
)
from pipeline.fetchers.sitca import SitcaFetcher
from pipeline.fetchers.finmind import FinMindStockInfoFetcher


# --- TWSE MI_INDEX ---

class TestTwseMiIndexFetcher:
    def test_source_name(self):
        f = TwseMiIndexFetcher.__new__(TwseMiIndexFetcher)
        assert f.source_name == "twse_mi_index"
        assert f.target_table == "industry_index"

    def test_transform_filters_industry_indices(self):
        f = TwseMiIndexFetcher.__new__(TwseMiIndexFetcher)
        raw = [
            {"指數": "半導體類指數", "收盤指數": "1,234.56", "漲跌百分比": "1.23"},
            {"指數": "發行量加權股價指數", "收盤指數": "20000", "漲跌百分比": "0.5"},
            {"指數": "金融保險類指數", "收盤指數": "2,000.00", "漲跌百分比": "-0.50"},
        ]
        df = f.transform(raw)
        # Composite index should be filtered out
        assert len(df) == 2
        assert set(df["industry"]) == {"半導體", "金融保險"}

    def test_transform_empty(self):
        f = TwseMiIndexFetcher.__new__(TwseMiIndexFetcher)
        df = f.transform([])
        assert df.empty

    def test_transform_handles_bad_numbers(self):
        f = TwseMiIndexFetcher.__new__(TwseMiIndexFetcher)
        raw = [{"指數": "半導體類指數", "收盤指數": "N/A", "漲跌百分比": "1.0"}]
        df = f.transform(raw)
        assert df.empty  # Bad close_index → skipped


# --- TWSE STOCK_DAY_ALL ---

class TestTwseStockDayAllFetcher:
    def test_source_name(self):
        f = TwseStockDayAllFetcher.__new__(TwseStockDayAllFetcher)
        assert f.source_name == "twse_stock_day_all"
        assert f.target_table == "stock_price"

    def test_transform_extracts_prices(self):
        f = TwseStockDayAllFetcher.__new__(TwseStockDayAllFetcher)
        raw = [
            {"Code": "2330", "ClosingPrice": "950.00", "Change": "1.5", "TradeVolume": "30,000,000"},
            {"Code": "2317", "ClosingPrice": "120.50", "Change": "-0.3", "TradeVolume": "5,000,000"},
        ]
        df = f.transform(raw)
        assert len(df) == 2
        assert list(df.columns) == ["stock_id", "date", "close_price", "change_pct", "volume", "market_cap", "source"]

    def test_transform_skips_empty_code(self):
        f = TwseStockDayAllFetcher.__new__(TwseStockDayAllFetcher)
        raw = [{"Code": "", "ClosingPrice": "100", "Change": "0", "TradeVolume": "0"}]
        df = f.transform(raw)
        assert df.empty


# --- TWSE Company Info ---

class TestTwseCompanyInfoFetcher:
    def test_source_name(self):
        f = TwseCompanyInfoFetcher.__new__(TwseCompanyInfoFetcher)
        assert f.source_name == "twse_company_info"
        assert f.target_table == "stock_info"

    def test_transform_extracts_info(self):
        f = TwseCompanyInfoFetcher.__new__(TwseCompanyInfoFetcher)
        raw = [
            {"公司代號": "2330", "公司簡稱": "台積電", "產業類別": "半導體業"},
            {"公司代號": "2317", "公司簡稱": "鴻海", "產業類別": "其他電子業"},
        ]
        df = f.transform(raw)
        assert len(df) == 2
        assert df.iloc[0]["industry_source"] == "tse28"


# --- SITCA ---

class TestSitcaFetcher:
    def test_source_name(self):
        f = SitcaFetcher()
        assert f.source_name == "sitca"
        assert f.target_table == "fund_holding"

    @pytest.mark.asyncio
    async def test_fetch_no_files(self):
        f = SitcaFetcher(sitca_dir="/nonexistent/dir")
        result = await f.fetch({})
        assert result == []

    def test_transform_empty(self):
        f = SitcaFetcher()
        df = f.transform([])
        assert df.empty

    def test_transform_normalizes(self):
        f = SitcaFetcher()
        raw = [{
            "fund_id": "0050",
            "as_of_date": "2026-04-01",
            "stock_id": None,
            "stock_name": "半導體業",
            "weight": 0.35,
            "asset_type": "equity",
            "sector": "半導體業",
            "source": "sitca",
        }]
        df = f.transform(raw)
        assert len(df) == 1
        assert list(df.columns) == [
            "fund_id", "as_of_date", "stock_id", "stock_name",
            "weight", "asset_type", "sector", "source",
        ]


# --- FinMind ---

class TestFinMindStockInfoFetcher:
    def test_source_name(self):
        f = FinMindStockInfoFetcher.__new__(FinMindStockInfoFetcher)
        assert f.source_name == "finmind_stock_info"
        assert f.target_table == "stock_info"

    def test_transform_normalizes(self):
        f = FinMindStockInfoFetcher.__new__(FinMindStockInfoFetcher)
        raw = [
            {"stock_id": "2330", "stock_name": "台積電", "type": "twse", "industry_category": "半導體業"},
            {"stock_id": "6547", "stock_name": "高端疫苗", "type": "tpex", "industry_category": "生技醫療業"},
        ]
        df = f.transform(raw)
        assert len(df) == 2
        assert df.iloc[0]["market"] == "twse"
        assert df.iloc[1]["market"] == "tpex"

    def test_transform_empty(self):
        f = FinMindStockInfoFetcher.__new__(FinMindStockInfoFetcher)
        df = f.transform([])
        assert df.empty

    @pytest.mark.asyncio
    async def test_fetch_handles_api_error(self):
        """Fetch returns empty list on API failure."""
        mock_cfg = MagicMock()
        mock_cfg.finmind_api_token = ""
        f = FinMindStockInfoFetcher(config=mock_cfg)

        with patch("pipeline.fetchers.finmind.aiohttp.ClientSession") as mock_session_cls:
            mock_session = MagicMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.get.side_effect = Exception("Network error")
            mock_session_cls.return_value = mock_session

            result = await f.fetch({})
            assert result == []


# --- TSE_INDUSTRY_INDICES ---

class TestTseIndustryIndices:
    def test_has_major_indices(self):
        assert "半導體類指數" in TSE_INDUSTRY_INDICES
        assert "金融保險類指數" in TSE_INDUSTRY_INDICES
        assert len(TSE_INDUSTRY_INDICES) >= 28
