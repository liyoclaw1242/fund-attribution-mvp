"""Tests for data/asset_resolver.py — smart asset identification."""

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data.asset_resolver import resolve_asset, resolve_portfolio


# ---------------------------------------------------------------------------
# resolve_asset — type identification
# ---------------------------------------------------------------------------

class TestResolveAsset:
    def test_tw_stock_4digit(self):
        result = resolve_asset("2330")
        assert result["type"] == "tw_stock"
        assert result["code"] == "2330"
        assert result["market"] == "TWSE"

    def test_tw_etf_0050(self):
        result = resolve_asset("0050")
        assert result["type"] == "tw_stock"  # 4 digits
        assert result["code"] == "0050"

    def test_tw_etf_00878(self):
        result = resolve_asset("00878")
        assert result["type"] == "tw_etf"
        assert result["code"] == "00878"

    def test_us_stock(self):
        result = resolve_asset("AAPL")
        assert result["type"] == "us_stock"
        assert result["ticker"] == "AAPL"
        assert result["market"] == "US"

    def test_us_stock_lowercase(self):
        result = resolve_asset("nvda")
        assert result["type"] == "us_stock"
        assert result["ticker"] == "NVDA"

    def test_offshore_fund_chinese(self):
        result = resolve_asset("摩根太平洋科技")
        assert result["type"] == "offshore_fund"
        assert result["keyword"] == "摩根太平洋科技"

    def test_isin_lu(self):
        result = resolve_asset("LU0117844026")
        assert result["type"] == "offshore_fund"
        assert result["fund_id"] == "LU0117844026"

    def test_isin_ie(self):
        result = resolve_asset("IE00B4L5Y983")
        assert result["type"] == "offshore_fund"

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="不可為空"):
            resolve_asset("")

    def test_whitespace_stripped(self):
        result = resolve_asset("  AAPL  ")
        assert result["ticker"] == "AAPL"

    def test_six_digit_tw(self):
        result = resolve_asset("006208")
        assert result["type"] in ("tw_stock", "tw_etf")


# ---------------------------------------------------------------------------
# resolve_portfolio — batch resolution
# ---------------------------------------------------------------------------

class TestResolvePortfolio:
    @patch("data.asset_resolver._fetch_asset_data")
    def test_mixed_portfolio(self, mock_fetch):
        mock_fetch.side_effect = lambda asset, item, conn, bc: {
            "name": asset.get("code") or asset.get("ticker") or asset.get("name", ""),
            "identifier": asset.get("code") or asset.get("ticker", ""),
            "asset_type": asset["type"],
            "market": asset["market"],
            "currency": "TWD" if asset["market"] == "TWSE" else "USD",
            "shares": item.get("shares", 0),
            "cost_basis_twd": 100000,
            "market_value_twd": 100000,
            "sector": "資訊科技",
            "region": "台灣" if asset["market"] == "TWSE" else "美國",
            "asset_class": "股票",
            "weight": 0,
            "return_rate_local": 0.03,
            "return_rate_twd": 0.03,
            "fx_contribution": 0.0,
        }

        items = [
            {"identifier": "0050", "shares": 100},
            {"identifier": "AAPL", "shares": 50},
            {"identifier": "摩根太平洋科技", "amount_twd": 100000},
        ]

        df = resolve_portfolio(items)

        assert len(df) == 3
        assert df["weight"].sum() == pytest.approx(1.0, abs=0.01)
        assert "asset_type" in df.columns

    def test_empty_items(self):
        df = resolve_portfolio([])
        assert len(df) == 0

    @patch("data.asset_resolver._fetch_asset_data", side_effect=Exception("fail"))
    def test_all_failures_returns_empty(self, mock_fetch):
        items = [{"identifier": "FAIL1"}, {"identifier": "FAIL2"}]
        df = resolve_portfolio(items)
        assert len(df) == 0

    @patch("data.asset_resolver._fetch_asset_data")
    def test_partial_failure(self, mock_fetch):
        call_count = [0]

        def side_effect(asset, item, conn, bc):
            call_count[0] += 1
            if call_count[0] == 2:
                raise Exception("fail")
            return {
                "name": "OK", "identifier": "OK", "asset_type": "tw_stock",
                "market": "TWSE", "currency": "TWD", "shares": 100,
                "cost_basis_twd": 100000, "market_value_twd": 100000,
                "sector": "A", "region": "台灣", "asset_class": "股票",
                "weight": 0, "return_rate_local": 0.02,
                "return_rate_twd": 0.02, "fx_contribution": 0.0,
            }

        mock_fetch.side_effect = side_effect
        items = [
            {"identifier": "0050", "shares": 100},
            {"identifier": "FAIL", "shares": 50},
            {"identifier": "0056", "shares": 200},
        ]
        df = resolve_portfolio(items)
        assert len(df) == 2  # 1 failed, 2 succeeded

    @patch("data.asset_resolver._fetch_asset_data")
    def test_weights_computed(self, mock_fetch):
        mock_fetch.side_effect = lambda asset, item, conn, bc: {
            "name": "A", "identifier": "A", "asset_type": "tw_stock",
            "market": "TWSE", "currency": "TWD", "shares": 0,
            "cost_basis_twd": item.get("amount_twd", 100000),
            "market_value_twd": item.get("amount_twd", 100000),
            "sector": "A", "region": "台灣", "asset_class": "股票",
            "weight": 0, "return_rate_local": 0.0,
            "return_rate_twd": 0.0, "fx_contribution": 0.0,
        }

        items = [
            {"identifier": "A", "amount_twd": 300000},
            {"identifier": "B", "amount_twd": 100000},
        ]
        df = resolve_portfolio(items)
        assert df["weight"].iloc[0] == pytest.approx(0.75)
        assert df["weight"].iloc[1] == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# Integration: resolve_asset → type coverage
# ---------------------------------------------------------------------------

class TestAssetTypeCoverage:
    def test_common_tw_etfs(self):
        for code in ["0050", "0056", "00878", "00919", "006208"]:
            result = resolve_asset(code)
            assert result["market"] == "TWSE"

    def test_common_us_stocks(self):
        for ticker in ["AAPL", "MSFT", "NVDA", "TSLA", "GOOG"]:
            result = resolve_asset(ticker)
            assert result["type"] == "us_stock"
            assert result["market"] == "US"

    def test_common_offshore_funds(self):
        for name in ["摩根太平洋科技", "安聯收益成長", "富蘭克林坦伯頓"]:
            result = resolve_asset(name)
            assert result["type"] == "offshore_fund"
