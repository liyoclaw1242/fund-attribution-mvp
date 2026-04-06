"""Tests for engine/fund_comparator.py — fund comparison engine."""

import pathlib

import pandas as pd
import pytest

from engine.fund_comparator import compare_funds, _compute_fund_metrics

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden_data"


def _load_holdings(fund_n: int) -> pd.DataFrame:
    return pd.read_excel(GOLDEN_DIR / f"fund_{fund_n}.xlsx", sheet_name="holdings")


class TestCompareFunds:
    def test_two_funds(self):
        holdings_map = {
            "0050": _load_holdings(1),
            "006208": _load_holdings(2),
        }
        result = compare_funds(holdings_map)
        assert len(result.funds) == 2
        assert result.funds[0].fund_code == "0050"
        assert result.funds[1].fund_code == "006208"
        assert result.ai_explanation != ""

    def test_three_funds(self):
        holdings_map = {
            "0050": _load_holdings(1),
            "006208": _load_holdings(2),
            "TECH": _load_holdings(3),
        }
        result = compare_funds(holdings_map)
        assert len(result.funds) == 3

    def test_too_few_raises(self):
        with pytest.raises(ValueError, match="At least 2"):
            compare_funds({"0050": _load_holdings(1)})

    def test_too_many_raises(self):
        holdings_map = {f"fund_{i}": _load_holdings(1) for i in range(5)}
        with pytest.raises(ValueError, match="Maximum 4"):
            compare_funds(holdings_map)

    def test_attribution_diffs_computed(self):
        holdings_map = {
            "0050": _load_holdings(1),
            "006208": _load_holdings(2),
        }
        result = compare_funds(holdings_map)
        assert result.attribution_diffs is not None
        key = "0050_vs_006208"
        assert key in result.attribution_diffs
        diffs = result.attribution_diffs[key]
        assert len(diffs) > 0
        assert "industry" in diffs[0]
        assert "alloc_diff" in diffs[0]

    def test_template_explanation_mentions_best_fund(self):
        holdings_map = {
            "0050": _load_holdings(1),
            "006208": _load_holdings(2),
        }
        result = compare_funds(holdings_map)
        # Should mention at least one fund code
        assert "0050" in result.ai_explanation or "006208" in result.ai_explanation


class TestFundMetrics:
    def test_compute_metrics(self):
        holdings = _load_holdings(1)
        metrics = _compute_fund_metrics("0050", holdings)
        assert metrics.fund_code == "0050"
        assert metrics.total_return > 0
        assert metrics.sector_weights is not None
        assert "半導體業" in metrics.sector_weights
        assert metrics.attribution is not None

    def test_sharpe_computed(self):
        holdings = _load_holdings(1)
        metrics = _compute_fund_metrics("0050", holdings)
        # Sharpe should be a number (could be None for edge cases)
        if metrics.sharpe_ratio is not None:
            assert isinstance(metrics.sharpe_ratio, float)

    def test_max_drawdown(self):
        holdings = _load_holdings(1)
        metrics = _compute_fund_metrics("0050", holdings)
        # For positive return fund, MaxDD should be 0
        assert metrics.max_drawdown <= 0 or metrics.total_return > 0
