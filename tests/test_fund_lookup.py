"""Tests for data/fund_lookup.py and data/fund_registry.py."""

from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data.fund_lookup import lookup_fund, _merge_holdings
from data.fund_registry import (
    get_fund_info,
    search_funds,
    list_all_funds,
    FUND_REGISTRY,
)


# ---------------------------------------------------------------------------
# Fund Registry
# ---------------------------------------------------------------------------

class TestFundRegistry:
    def test_has_at_least_20_funds(self):
        assert len(FUND_REGISTRY) >= 20

    def test_0050_exists(self):
        info = get_fund_info("0050")
        assert info is not None
        assert info["fund_name"] == "元大台灣卓越50基金"
        assert info["company_code"] == "A0005"

    def test_00878_exists(self):
        info = get_fund_info("00878")
        assert info is not None
        assert "國泰" in info["company_name"]

    def test_unknown_fund(self):
        info = get_fund_info("99999")
        assert info is None

    def test_case_insensitive(self):
        info = get_fund_info("0050")
        assert info is not None

    def test_search_by_name(self):
        results = search_funds("元大")
        assert len(results) >= 3

    def test_search_by_code(self):
        results = search_funds("0050")
        assert len(results) >= 1

    def test_search_empty(self):
        results = search_funds("不存在的基金XYZ")
        assert results == []

    def test_list_all(self):
        all_funds = list_all_funds()
        assert len(all_funds) >= 20
        assert all("fund_code" in f for f in all_funds)


# ---------------------------------------------------------------------------
# Merge Holdings
# ---------------------------------------------------------------------------

class TestMergeHoldings:
    def test_basic_merge(self):
        wp = pd.DataFrame({"industry": ["半導體", "金融"], "Wp": [0.6, 0.4]})
        wb = pd.DataFrame({"industry": ["半導體", "金融"], "Wb": [0.3, 0.2]})
        rb = pd.DataFrame({"industry": ["半導體", "金融"], "Rb": [0.05, 0.02]})
        rp = pd.DataFrame({"fund_name": ["元大台灣50"], "Rp": [0.03]})

        result = _merge_holdings(wp, rp, wb, rb, "元大台灣卓越50基金")

        assert len(result) == 2
        assert list(result.columns) == ["industry", "Wp", "Wb", "Rp", "Rb"]
        assert result["Wp"].sum() == pytest.approx(1.0)

    def test_missing_wb_fills_zero(self):
        wp = pd.DataFrame({"industry": ["半導體", "新產業"], "Wp": [0.6, 0.4]})
        wb = pd.DataFrame({"industry": ["半導體"], "Wb": [0.3]})
        rb = pd.DataFrame(columns=["industry", "Rb"])
        rp = pd.DataFrame(columns=["fund_name", "Rp"])

        result = _merge_holdings(wp, rp, wb, rb, "test")
        assert result["Wb"].iloc[1] == 0.0

    def test_empty_wp_returns_empty(self):
        wp = pd.DataFrame(columns=["industry", "Wp"])
        wb = pd.DataFrame({"industry": ["半導體"], "Wb": [0.3]})
        rb = pd.DataFrame(columns=["industry", "Rb"])
        rp = pd.DataFrame(columns=["fund_name", "Rp"])

        result = _merge_holdings(wp, rp, wb, rb, "test")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Full Lookup (mocked)
# ---------------------------------------------------------------------------

class TestLookupFund:
    @patch("data.fund_lookup._fetch_rb")
    @patch("data.fund_lookup._fetch_wb")
    @patch("data.fund_lookup._fetch_rp")
    @patch("data.fund_lookup._fetch_wp")
    def test_0050_lookup(self, mock_wp, mock_rp, mock_wb, mock_rb):
        mock_wp.return_value = pd.DataFrame({
            "industry": ["半導體", "金融保險", "電子零組件"],
            "Wp": [0.42, 0.18, 0.12],
        })
        mock_rp.return_value = pd.DataFrame({
            "fund_name": ["元大台灣卓越50基金"],
            "Rp": [0.025],
        })
        mock_wb.return_value = pd.DataFrame({
            "industry": ["半導體", "金融保險", "電子零組件"],
            "Wb": [0.30, 0.13, 0.08],
        })
        mock_rb.return_value = pd.DataFrame({
            "industry": ["半導體", "金融保險", "電子零組件"],
            "Rb": [0.05, 0.02, 0.03],
        })

        result = lookup_fund("0050")

        assert len(result) == 3
        assert list(result.columns) == ["industry", "Wp", "Wb", "Rp", "Rb"]
        assert result["Wp"].sum() > 0

    def test_unknown_fund_raises(self):
        with pytest.raises(ValueError, match="查無資料"):
            lookup_fund("99999")

    @patch("data.fund_lookup._fetch_rb", return_value=pd.DataFrame(columns=["industry", "Rb"]))
    @patch("data.fund_lookup._fetch_wb", return_value=pd.DataFrame(columns=["industry", "Wb"]))
    @patch("data.fund_lookup._fetch_rp", return_value=pd.DataFrame(columns=["fund_name", "Rp"]))
    @patch("data.fund_lookup._fetch_wp", return_value=pd.DataFrame(columns=["industry", "Wp"]))
    def test_empty_data_raises(self, mock_wp, mock_rp, mock_wb, mock_rb):
        with pytest.raises(ValueError, match="資料不完整"):
            lookup_fund("0050")

    @patch("data.fund_lookup._fetch_rb")
    @patch("data.fund_lookup._fetch_wb")
    @patch("data.fund_lookup._fetch_rp")
    @patch("data.fund_lookup._fetch_wp")
    def test_result_has_five_columns(self, mock_wp, mock_rp, mock_wb, mock_rb):
        mock_wp.return_value = pd.DataFrame({"industry": ["A"], "Wp": [1.0]})
        mock_rp.return_value = pd.DataFrame({"fund_name": ["Fund"], "Rp": [0.01]})
        mock_wb.return_value = pd.DataFrame({"industry": ["A"], "Wb": [0.5]})
        mock_rb.return_value = pd.DataFrame({"industry": ["A"], "Rb": [0.02]})

        result = lookup_fund("0050")
        assert set(result.columns) == {"industry", "Wp", "Wb", "Rp", "Rb"}
