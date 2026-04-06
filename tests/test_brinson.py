"""Edge case tests for engine/brinson.py — extreme scenarios."""

import pandas as pd
import pytest

from engine.brinson import compute_attribution


class TestEdgeCases:
    def test_100_percent_cash(self):
        """100% cash fund: fund_return=0, excess negative, allocation is all drag."""
        df = pd.DataFrame([
            {"industry": "現金", "Wp": 1.0, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0},
            {"industry": "半導體業", "Wp": 0.0, "Wb": 1.0, "Rp": 0.0, "Rb": 0.05},
        ])
        result = compute_attribution(df, mode="BF2")
        assert result["fund_return"] == 0.0
        assert result["bench_return"] == pytest.approx(0.05)
        assert result["excess_return"] == pytest.approx(-0.05)

    def test_single_industry(self):
        """Single industry: allocation=0 (same weight), selection captures all."""
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 1.0, "Wb": 1.0, "Rp": 0.10, "Rb": 0.05},
        ])
        result = compute_attribution(df, mode="BF2")
        assert result["allocation_total"] == pytest.approx(0.0)
        assert result["selection_total"] == pytest.approx(0.05)
        assert result["excess_return"] == pytest.approx(0.05)

    def test_all_negative_returns(self):
        """All negative returns: should not crash, excess can be positive or negative."""
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 0.6, "Wb": 0.5, "Rp": -0.05, "Rb": -0.08},
            {"industry": "金融保險業", "Wp": 0.4, "Wb": 0.5, "Rp": -0.10, "Rb": -0.03},
        ])
        result = compute_attribution(df, mode="BF3")
        assert isinstance(result["excess_return"], float)
        # Invariant: alloc + select + interaction = excess
        total = result["allocation_total"] + result["selection_total"] + result["interaction_total"]
        assert abs(total - result["excess_return"]) < 1e-10

    def test_zero_returns(self):
        """All returns are zero: all effects should be zero."""
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0, "Rb": 0.0},
            {"industry": "金融保險業", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0, "Rb": 0.0},
        ])
        result = compute_attribution(df, mode="BF2")
        assert result["excess_return"] == 0.0
        assert result["allocation_total"] == 0.0
        assert result["selection_total"] == 0.0

    def test_identical_fund_and_benchmark(self):
        """Fund = benchmark: excess=0, all effects=0."""
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 0.6, "Wb": 0.6, "Rp": 0.08, "Rb": 0.08},
            {"industry": "金融保險業", "Wp": 0.4, "Wb": 0.4, "Rp": 0.03, "Rb": 0.03},
        ])
        result = compute_attribution(df, mode="BF3")
        assert abs(result["excess_return"]) < 1e-10
        assert abs(result["allocation_total"]) < 1e-10
        assert abs(result["selection_total"]) < 1e-10
        assert abs(result["interaction_total"]) < 1e-10


class TestInputValidation:
    def test_invalid_mode(self):
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 1.0, "Wb": 1.0, "Rp": 0.0, "Rb": 0.0},
        ])
        with pytest.raises(ValueError, match="Invalid mode"):
            compute_attribution(df, mode="BF4")

    def test_missing_columns(self):
        df = pd.DataFrame([{"industry": "半導體業", "weight": 0.5}])
        with pytest.raises(ValueError, match="Missing required columns"):
            compute_attribution(df)


class TestOutputShape:
    def test_top_bottom_contributors(self):
        df = pd.DataFrame([
            {"industry": f"ind_{i}", "Wp": 0.1, "Wb": 0.1, "Rp": 0.01 * i, "Rb": 0.005 * i}
            for i in range(1, 11)
        ])
        result = compute_attribution(df, mode="BF2")
        assert len(result["top_contributors"]) == 3
        assert len(result["bottom_contributors"]) == 3
        assert result["top_contributors"].iloc[0]["total_contrib"] >= result["top_contributors"].iloc[1]["total_contrib"]

    def test_bf3_has_interaction(self):
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 0.7, "Wb": 0.5, "Rp": 0.10, "Rb": 0.05},
            {"industry": "金融保險業", "Wp": 0.3, "Wb": 0.5, "Rp": 0.02, "Rb": 0.03},
        ])
        result = compute_attribution(df, mode="BF3")
        assert result["interaction_total"] is not None
        assert isinstance(result["interaction_total"], float)

    def test_bf2_interaction_is_none(self):
        df = pd.DataFrame([
            {"industry": "半導體業", "Wp": 1.0, "Wb": 1.0, "Rp": 0.10, "Rb": 0.05},
        ])
        result = compute_attribution(df, mode="BF2")
        assert result["interaction_total"] is None
