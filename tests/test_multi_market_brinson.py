"""Tests for engine/multi_market_brinson.py — multi-market Brinson engine."""

import pandas as pd
import pytest

from engine.multi_market_brinson import (
    compute_multi_market_attribution,
    build_blended_benchmark,
    map_to_unified_sector,
    UNIFIED_SECTORS,
    _SECTOR_REVERSE_MAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_tw_us_portfolio():
    """Mixed TW + US portfolio."""
    return pd.DataFrame([
        {"name": "0050", "asset_class": "股票", "region": "台灣", "sector": "資訊科技",
         "weight": 0.30, "return_rate": 0.05, "currency": "TWD", "fx_contribution": 0.0},
        {"name": "0050-金融", "asset_class": "股票", "region": "台灣", "sector": "金融",
         "weight": 0.20, "return_rate": 0.02, "currency": "TWD", "fx_contribution": 0.0},
        {"name": "AAPL", "asset_class": "股票", "region": "美國", "sector": "資訊科技",
         "weight": 0.25, "return_rate": 0.08, "currency": "USD", "fx_contribution": 0.005},
        {"name": "JNJ", "asset_class": "股票", "region": "美國", "sector": "醫療保健",
         "weight": 0.15, "return_rate": 0.03, "currency": "USD", "fx_contribution": 0.005},
        {"name": "Cash", "asset_class": "現金", "region": "台灣", "sector": "現金",
         "weight": 0.10, "return_rate": 0.001, "currency": "TWD", "fx_contribution": 0.0},
    ])


def _make_benchmark():
    """Blended benchmark (50% TW / 50% US)."""
    return pd.DataFrame([
        {"name": "TAIEX:資訊科技", "asset_class": "股票", "region": "台灣", "sector": "資訊科技",
         "weight": 0.20, "return_rate": 0.04, "currency": "TWD", "fx_contribution": 0.0},
        {"name": "TAIEX:金融", "asset_class": "股票", "region": "台灣", "sector": "金融",
         "weight": 0.10, "return_rate": 0.015, "currency": "TWD", "fx_contribution": 0.0},
        {"name": "TAIEX:其他", "asset_class": "股票", "region": "台灣", "sector": "其他",
         "weight": 0.20, "return_rate": 0.025, "currency": "TWD", "fx_contribution": 0.0},
        {"name": "SP500:資訊科技", "asset_class": "股票", "region": "美國", "sector": "資訊科技",
         "weight": 0.25, "return_rate": 0.06, "currency": "USD", "fx_contribution": 0.003},
        {"name": "SP500:醫療保健", "asset_class": "股票", "region": "美國", "sector": "醫療保健",
         "weight": 0.15, "return_rate": 0.02, "currency": "USD", "fx_contribution": 0.003},
        {"name": "Cash", "asset_class": "現金", "region": "台灣", "sector": "現金",
         "weight": 0.10, "return_rate": 0.001, "currency": "TWD", "fx_contribution": 0.0},
    ])


# ---------------------------------------------------------------------------
# Core attribution
# ---------------------------------------------------------------------------

class TestMultiMarketAttribution:
    def test_returns_dict(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark()
        )
        assert isinstance(result, dict)
        assert "portfolio_return" in result
        assert "benchmark_return" in result
        assert "excess_return" in result

    def test_excess_return_correct(self):
        portfolio = _make_tw_us_portfolio()
        benchmark = _make_benchmark()
        result = compute_multi_market_attribution(portfolio, benchmark)

        expected_p = (portfolio["weight"] * portfolio["return_rate"]).sum()
        expected_b = (benchmark["weight"] * benchmark["return_rate"]).sum()

        assert result["portfolio_return"] == pytest.approx(expected_p, abs=1e-10)
        assert result["benchmark_return"] == pytest.approx(expected_b, abs=1e-10)
        assert result["excess_return"] == pytest.approx(expected_p - expected_b, abs=1e-10)

    def test_has_dimension_attributions(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark()
        )
        assert "by_asset_class" in result
        assert "by_region" in result
        assert "by_sector" in result

    def test_asset_class_attribution(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark(),
            dimensions=["asset_class"],
        )
        attr = result["by_asset_class"]
        assert "allocation_total" in attr
        assert "selection_total" in attr

    def test_region_attribution(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark(),
            dimensions=["region"],
        )
        attr = result["by_region"]
        assert "allocation_total" in attr

    def test_sector_attribution(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark(),
            dimensions=["sector"],
        )
        attr = result["by_sector"]
        assert "allocation_total" in attr

    def test_currency_attribution(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark()
        )
        fx = result["currency_attribution"]
        assert isinstance(fx, pd.DataFrame)
        assert "currency" in fx.columns
        assert "contribution" in fx.columns

    def test_fx_contribution_captured(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark()
        )
        assert result["fx_contribution"] != 0  # US holdings have fx_contribution

    def test_bf3_mode(self):
        result = compute_multi_market_attribution(
            _make_tw_us_portfolio(), _make_benchmark(),
            mode="BF3",
        )
        attr = result["by_sector"]
        assert attr.get("interaction_total") is not None


# ---------------------------------------------------------------------------
# Backward compatibility (pure TW)
# ---------------------------------------------------------------------------

class TestPureTWCompatibility:
    def test_pure_tw_portfolio(self):
        portfolio = pd.DataFrame([
            {"name": "A", "asset_class": "股票", "region": "台灣", "sector": "資訊科技",
             "weight": 0.6, "return_rate": 0.05, "currency": "TWD", "fx_contribution": 0.0},
            {"name": "B", "asset_class": "股票", "region": "台灣", "sector": "金融",
             "weight": 0.4, "return_rate": 0.02, "currency": "TWD", "fx_contribution": 0.0},
        ])
        benchmark = pd.DataFrame([
            {"name": "TAIEX:資訊科技", "asset_class": "股票", "region": "台灣", "sector": "資訊科技",
             "weight": 0.5, "return_rate": 0.04, "currency": "TWD", "fx_contribution": 0.0},
            {"name": "TAIEX:金融", "asset_class": "股票", "region": "台灣", "sector": "金融",
             "weight": 0.5, "return_rate": 0.015, "currency": "TWD", "fx_contribution": 0.0},
        ])

        result = compute_multi_market_attribution(portfolio, benchmark)

        # FX contribution should be zero for pure TWD
        assert result["fx_contribution"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Unified sector mapping
# ---------------------------------------------------------------------------

class TestUnifiedSectors:
    def test_has_11_sectors(self):
        assert len(UNIFIED_SECTORS) == 11

    def test_semiconductor_maps_to_it(self):
        assert map_to_unified_sector("半導體") == "資訊科技"

    def test_finance_maps(self):
        assert map_to_unified_sector("金融保險") == "金融"

    def test_english_maps(self):
        assert map_to_unified_sector("Technology") == "資訊科技"
        assert map_to_unified_sector("Financials") == "金融"

    def test_unknown_maps_to_other(self):
        assert map_to_unified_sector("未知分類") == "其他"

    def test_self_mapping(self):
        assert map_to_unified_sector("資訊科技") == "資訊科技"
        assert map_to_unified_sector("金融") == "金融"

    def test_coverage(self):
        # At least 30 detailed sectors mapped
        assert len(_SECTOR_REVERSE_MAP) >= 30


# ---------------------------------------------------------------------------
# Blended benchmark
# ---------------------------------------------------------------------------

class TestBlendedBenchmark:
    def test_50_50_blend(self):
        tw = pd.DataFrame([
            {"industry": "資訊科技", "Wb": 0.6, "Rb": 0.04},
            {"industry": "金融", "Wb": 0.4, "Rb": 0.02},
        ])
        us = pd.DataFrame([
            {"sector": "資訊科技", "Wb": 0.5, "Rb": 0.06},
            {"sector": "醫療保健", "Wb": 0.5, "Rb": 0.03},
        ])

        result = build_blended_benchmark(
            [{"index": "TAIEX", "weight": 0.5}, {"index": "SP500", "weight": 0.5}],
            tw_benchmark=tw, us_benchmark=us,
        )

        assert len(result) == 4
        assert result["weight"].sum() == pytest.approx(1.0, abs=0.01)

    def test_empty_allocations(self):
        result = build_blended_benchmark([])
        assert len(result) == 0

    def test_has_required_columns(self):
        tw = pd.DataFrame([{"industry": "資訊科技", "Wb": 1.0, "Rb": 0.04}])
        result = build_blended_benchmark(
            [{"index": "TAIEX", "weight": 1.0}],
            tw_benchmark=tw,
        )
        for col in ["name", "asset_class", "region", "sector", "weight", "return_rate", "currency"]:
            assert col in result.columns


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_missing_weight_raises(self):
        portfolio = pd.DataFrame({"return_rate": [0.05]})
        benchmark = pd.DataFrame({"weight": [1.0], "return_rate": [0.04]})
        with pytest.raises(ValueError, match="weight"):
            compute_multi_market_attribution(portfolio, benchmark)

    def test_missing_return_raises(self):
        portfolio = pd.DataFrame({"weight": [1.0]})
        benchmark = pd.DataFrame({"weight": [1.0], "return_rate": [0.04]})
        with pytest.raises(ValueError, match="return_rate"):
            compute_multi_market_attribution(portfolio, benchmark)
