"""Tests for Finnhub fund fetcher, ISIN registry, and sector mapping."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from pipeline.fetchers.finnhub_ import FinnhubFundFetcher, FinnhubFetcher
from pipeline.fetchers.fund_isin_registry import (
    FUND_ISIN_MAP,
    get_all_isins,
    lookup_isin,
    lookup_name,
)
from pipeline.transformers.industry_mapper import FINNHUB_SECTOR_MAP, map_industry


# --- ISIN Registry ---

class TestFundIsinRegistry:
    def test_has_50_plus_entries(self):
        assert len(FUND_ISIN_MAP) >= 50

    def test_lookup_exact(self):
        assert lookup_isin("摩根太平洋科技基金") == "LU0117844026"
        assert lookup_isin("安聯收益成長基金-AM穩定月收類股") == "LU0689472784"

    def test_lookup_contains(self):
        result = lookup_isin("摩根太平洋科技")
        assert result == "LU0117844026"

    def test_lookup_unknown(self):
        assert lookup_isin("不存在的基金") is None

    def test_reverse_lookup(self):
        assert lookup_name("LU0117844026") == "摩根太平洋科技基金"
        assert lookup_name("XXXXXXXXXXXX") is None

    def test_get_all_isins(self):
        isins = get_all_isins()
        assert len(isins) >= 50
        assert "LU0117844026" in isins

    def test_all_isins_valid_format(self):
        """ISIN codes should match standard format."""
        for name, isin in FUND_ISIN_MAP.items():
            assert len(isin) == 12, f"Invalid ISIN length for {name}: {isin}"
            assert isin[:2].isalpha(), f"Invalid ISIN prefix for {name}: {isin}"

    def test_major_fund_houses_covered(self):
        """Registry should cover major offshore fund houses."""
        names = list(FUND_ISIN_MAP.keys())
        all_names = " ".join(names)
        assert "摩根" in all_names
        assert "安聯" in all_names
        assert "富達" in all_names
        assert "貝萊德" in all_names
        assert "富蘭克林" in all_names


# --- FinnhubFundFetcher ---

class TestFinnhubFundFetcher:
    def test_source_name(self):
        assert FinnhubFundFetcher.source_name == "finnhub"
        assert FinnhubFundFetcher.target_table == "fund_holding"

    def test_backward_compat_alias(self):
        assert FinnhubFetcher is FinnhubFundFetcher

    @pytest.mark.asyncio
    async def test_skip_without_api_key(self):
        mock_cfg = MagicMock()
        mock_cfg.finnhub_api_key = ""
        f = FinnhubFundFetcher(config=mock_cfg)
        result = await f.fetch({})
        assert result == []

    @pytest.mark.asyncio
    async def test_uses_registry_when_no_fund_ids(self):
        mock_cfg = MagicMock()
        mock_cfg.finnhub_api_key = "test_key"
        f = FinnhubFundFetcher(config=mock_cfg)

        # Mock _fetch_fund to return empty
        f._fetch_fund = AsyncMock(return_value=[])

        with patch("pipeline.fetchers.finnhub_.get_all_isins", return_value=["LU001", "LU002"]):
            result = await f.fetch({})

        assert f._fetch_fund.await_count == 2

    def test_transform_empty(self):
        f = FinnhubFundFetcher.__new__(FinnhubFundFetcher)
        df = f.transform([])
        assert df.empty

    def test_transform_drops_record_type(self):
        f = FinnhubFundFetcher.__new__(FinnhubFundFetcher)
        raw = [{
            "fund_id": "LU001",
            "as_of_date": "2026-03-31",
            "stock_id": "US0378331005",
            "stock_name": "Apple Inc",
            "weight": 0.05,
            "asset_type": "equity",
            "sector": "Technology",
            "source": "finnhub",
            "_record_type": "holding",
        }]
        df = f.transform(raw)
        assert "_record_type" not in df.columns
        assert len(df) == 1

    def test_transform_maps_sector(self):
        f = FinnhubFundFetcher.__new__(FinnhubFundFetcher)
        raw = [{
            "fund_id": "LU001",
            "as_of_date": "2026-03-31",
            "stock_id": None,
            "stock_name": "Technology",
            "weight": 0.30,
            "asset_type": "sector_aggregate",
            "sector": "Technology",
            "source": "finnhub_sector",
            "_record_type": "sector",
        }]
        df = f.transform(raw)
        # Sector should be mapped to Chinese
        assert df.iloc[0]["sector"] == "資訊科技"

    def test_transform_schema_columns(self):
        f = FinnhubFundFetcher.__new__(FinnhubFundFetcher)
        raw = [{
            "fund_id": "LU001",
            "as_of_date": "2026-03-31",
            "stock_id": "X",
            "stock_name": "Test",
            "weight": 0.1,
            "asset_type": "equity",
            "sector": "Unknown",
            "source": "finnhub",
            "_record_type": "holding",
        }]
        df = f.transform(raw)
        expected = ["fund_id", "as_of_date", "stock_id", "stock_name",
                    "weight", "asset_type", "sector", "source"]
        assert list(df.columns) == expected


# --- Finnhub Sector Mapping ---

class TestFinnhubSectorMapping:
    def test_finnhub_map_has_all_sectors(self):
        required = ["Technology", "Financial Services", "Healthcare",
                     "Consumer Cyclical", "Industrials", "Energy"]
        for sector in required:
            assert sector in FINNHUB_SECTOR_MAP, f"Missing sector: {sector}"

    def test_map_industry_finnhub_source(self):
        assert map_industry("Technology", source="finnhub") == "資訊科技"
        assert map_industry("Healthcare", source="finnhub") == "醫療保健"
        assert map_industry("Consumer Cyclical", source="finnhub") == "消費循環"

    def test_map_industry_finnhub_auto(self):
        """Auto source should also pick up Finnhub mapping."""
        assert map_industry("Technology") == "資訊科技"
        assert map_industry("Financial Services") is not None

    def test_map_industry_finnhub_special_types(self):
        assert map_industry("Bonds", source="finnhub") == "債券"
        assert map_industry("Cash", source="finnhub") == "現金"
