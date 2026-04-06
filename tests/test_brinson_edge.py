"""20 Brinson edge case tests — extreme scenarios for compute_attribution.

Covers: 100% cash, single industry, negative/zero returns, identical fund/bench,
extreme weights, many industries, floating point precision, BF2 vs BF3,
top/bottom contributors, short positions, NaN handling.
"""

import pandas as pd
import numpy as np
import pytest

from engine.brinson import compute_attribution, TOLERANCE


def _make_df(rows):
    return pd.DataFrame(rows)


def _check_invariant(result):
    """Verify Brinson invariant: effects sum to excess return."""
    if result["brinson_mode"] == "BF3":
        total = result["allocation_total"] + result["selection_total"] + result["interaction_total"]
    else:
        total = result["allocation_total"] + result["selection_total"]
    assert abs(total - result["excess_return"]) < TOLERANCE


class TestBrinsonEdgeCases:
    """U1-U20: 20 edge case tests per spec."""

    def test_u01_100pct_cash_bf2(self):
        """U1: 100% cash fund BF2 — fund_return=0, excess negative."""
        df = _make_df([
            {"industry": "現金", "Wp": 1.0, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0},
            {"industry": "半導體業", "Wp": 0.0, "Wb": 1.0, "Rp": 0.0, "Rb": 0.05},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["fund_return"] == 0.0
        assert r["bench_return"] == pytest.approx(0.05)
        assert r["excess_return"] == pytest.approx(-0.05)
        _check_invariant(r)

    def test_u02_100pct_cash_bf3(self):
        """U2: 100% cash fund BF3 — invariant holds with 3 effects."""
        df = _make_df([
            {"industry": "現金", "Wp": 1.0, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0},
            {"industry": "半導體業", "Wp": 0.0, "Wb": 1.0, "Rp": 0.0, "Rb": 0.05},
        ])
        r = compute_attribution(df, mode="BF3")
        assert r["interaction_total"] is not None
        _check_invariant(r)

    def test_u03_single_industry_same_weight(self):
        """U3: Single industry, same weight — allocation=0, selection=excess."""
        df = _make_df([
            {"industry": "半導體業", "Wp": 1.0, "Wb": 1.0, "Rp": 0.10, "Rb": 0.05},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["allocation_total"] == pytest.approx(0.0)
        assert r["selection_total"] == pytest.approx(0.05)
        assert r["excess_return"] == pytest.approx(0.05)

    def test_u04_all_negative_returns(self):
        """U4: All negative returns — no crash, invariant holds."""
        df = _make_df([
            {"industry": "半導體業", "Wp": 0.6, "Wb": 0.5, "Rp": -0.05, "Rb": -0.08},
            {"industry": "金融保險業", "Wp": 0.4, "Wb": 0.5, "Rp": -0.10, "Rb": -0.03},
        ])
        r = compute_attribution(df, mode="BF3")
        _check_invariant(r)

    def test_u05_all_zero_returns(self):
        """U5: All returns zero — all effects zero."""
        df = _make_df([
            {"industry": "半導體業", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0, "Rb": 0.0},
            {"industry": "金融保險業", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0, "Rb": 0.0},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["excess_return"] == 0.0
        assert r["allocation_total"] == 0.0
        assert r["selection_total"] == 0.0

    def test_u06_identical_fund_and_benchmark(self):
        """U6: Fund = benchmark — excess=0, all effects=0."""
        df = _make_df([
            {"industry": "半導體業", "Wp": 0.6, "Wb": 0.6, "Rp": 0.08, "Rb": 0.08},
            {"industry": "金融保險業", "Wp": 0.4, "Wb": 0.4, "Rp": 0.03, "Rb": 0.03},
        ])
        r = compute_attribution(df, mode="BF3")
        assert abs(r["excess_return"]) < TOLERANCE
        assert abs(r["allocation_total"]) < TOLERANCE
        assert abs(r["selection_total"]) < TOLERANCE
        assert abs(r["interaction_total"]) < TOLERANCE

    def test_u07_extreme_overweight_single_industry(self):
        """U7: 95% in one industry — runs, invariant holds."""
        df = _make_df([
            {"industry": "半導體業", "Wp": 0.95, "Wb": 0.50, "Rp": 0.12, "Rb": 0.08},
            {"industry": "金融保險業", "Wp": 0.05, "Wb": 0.50, "Rp": 0.02, "Rb": 0.04},
        ])
        r = compute_attribution(df, mode="BF2")
        _check_invariant(r)

    def test_u08_many_industries_20(self):
        """U8: 20 industries — top/bottom 3, invariant holds."""
        rows = [
            {"industry": f"ind_{i:02d}", "Wp": 0.05, "Wb": 0.05,
             "Rp": 0.01 * (i - 10), "Rb": 0.005 * (i - 10)}
            for i in range(20)
        ]
        df = _make_df(rows)
        r = compute_attribution(df, mode="BF2")
        assert len(r["top_contributors"]) == 3
        assert len(r["bottom_contributors"]) == 3
        _check_invariant(r)

    def test_u09_near_zero_excess_floating_point(self):
        """U9: Near-zero excess — no assertion error."""
        df = _make_df([
            {"industry": "A", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0800000001, "Rb": 0.08},
            {"industry": "B", "Wp": 0.5, "Wb": 0.5, "Rp": 0.0299999999, "Rb": 0.03},
        ])
        r = compute_attribution(df, mode="BF2")
        assert abs(r["excess_return"]) < 1e-8
        _check_invariant(r)

    def test_u10_large_positive_returns(self):
        """U10: 45% returns — runs correctly."""
        df = _make_df([
            {"industry": "A", "Wp": 0.6, "Wb": 0.5, "Rp": 0.45, "Rb": 0.40},
            {"industry": "B", "Wp": 0.4, "Wb": 0.5, "Rp": 0.30, "Rb": 0.25},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["fund_return"] > 0.3
        _check_invariant(r)

    def test_u11_large_negative_returns(self):
        """U11: -40% returns — runs correctly."""
        df = _make_df([
            {"industry": "A", "Wp": 0.6, "Wb": 0.5, "Rp": -0.40, "Rb": -0.30},
            {"industry": "B", "Wp": 0.4, "Wb": 0.5, "Rp": -0.35, "Rb": -0.25},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["fund_return"] < -0.3
        _check_invariant(r)

    def test_u12_cash_plus_benchmark_up_market(self):
        """U12: Cash + benchmark in up market — cash allocation negative."""
        df = _make_df([
            {"industry": "現金", "Wp": 0.3, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0},
            {"industry": "半導體業", "Wp": 0.7, "Wb": 1.0, "Rp": 0.10, "Rb": 0.08},
        ])
        r = compute_attribution(df, mode="BF2")
        # Cash allocation should be negative (holding cash in up market = drag)
        cash_row = r["detail"][r["detail"]["industry"] == "現金"]
        assert cash_row.iloc[0]["alloc_effect"] < 0
        _check_invariant(r)

    def test_u13_bf2_vs_bf3_same_excess(self):
        """U13: BF2 vs BF3 — same excess_return, different decomposition."""
        df = _make_df([
            {"industry": "A", "Wp": 0.7, "Wb": 0.5, "Rp": 0.10, "Rb": 0.06},
            {"industry": "B", "Wp": 0.3, "Wb": 0.5, "Rp": 0.03, "Rb": 0.04},
        ])
        r2 = compute_attribution(df.copy(), mode="BF2")
        r3 = compute_attribution(df.copy(), mode="BF3")
        assert r2["excess_return"] == pytest.approx(r3["excess_return"])
        assert r2["interaction_total"] is None
        assert r3["interaction_total"] is not None
        _check_invariant(r2)
        _check_invariant(r3)

    def test_u14_top_contributors_ordered(self):
        """U14: Top contributors sorted descending by total_contrib."""
        df = _make_df([
            {"industry": "top", "Wp": 0.5, "Wb": 0.2, "Rp": 0.20, "Rb": 0.05},
            {"industry": "mid", "Wp": 0.3, "Wb": 0.3, "Rp": 0.05, "Rb": 0.04},
            {"industry": "bot", "Wp": 0.2, "Wb": 0.5, "Rp": 0.01, "Rb": 0.08},
        ])
        r = compute_attribution(df, mode="BF2")
        top = r["top_contributors"]
        assert top.iloc[0]["industry"] == "top"
        assert top.iloc[0]["total_contrib"] >= top.iloc[1]["total_contrib"]

    def test_u15_single_row_minimum_input(self):
        """U15: Single row — minimum valid input."""
        df = _make_df([
            {"industry": "A", "Wp": 1.0, "Wb": 1.0, "Rp": 0.05, "Rb": 0.03},
        ])
        r = compute_attribution(df, mode="BF2")
        assert r["excess_return"] == pytest.approx(0.02)
        _check_invariant(r)

    def test_u16_two_industries_equal_contribution(self):
        """U16: Two industries with identical total_contrib."""
        df = _make_df([
            {"industry": "A", "Wp": 0.5, "Wb": 0.5, "Rp": 0.10, "Rb": 0.05},
            {"industry": "B", "Wp": 0.5, "Wb": 0.5, "Rp": 0.10, "Rb": 0.05},
        ])
        r = compute_attribution(df, mode="BF2")
        assert len(r["detail"]) == 2
        assert r["detail"].iloc[0]["total_contrib"] == pytest.approx(
            r["detail"].iloc[1]["total_contrib"]
        )

    def test_u17_zero_fund_weight_positive_bench(self):
        """U17: Wp=0, Wb>0 — selection=0 in BF2."""
        df = _make_df([
            {"industry": "A", "Wp": 0.0, "Wb": 0.5, "Rp": 0.0, "Rb": 0.08},
            {"industry": "B", "Wp": 1.0, "Wb": 0.5, "Rp": 0.10, "Rb": 0.05},
        ])
        r = compute_attribution(df, mode="BF2")
        row_a = r["detail"][r["detail"]["industry"] == "A"]
        # BF2: select_effect = Wp * (Rp - Rb) = 0 * anything = 0
        assert row_a.iloc[0]["select_effect"] == pytest.approx(0.0)
        _check_invariant(r)

    def test_u18_zero_bench_weight_positive_fund(self):
        """U18: Wb=0, Wp>0 — allocation captures overweight."""
        df = _make_df([
            {"industry": "A", "Wp": 0.5, "Wb": 0.0, "Rp": 0.10, "Rb": 0.0},
            {"industry": "B", "Wp": 0.5, "Wb": 1.0, "Rp": 0.05, "Rb": 0.08},
        ])
        r = compute_attribution(df, mode="BF2")
        row_a = r["detail"][r["detail"]["industry"] == "A"]
        # Wp-Wb = 0.5, overweight
        assert row_a.iloc[0]["alloc_effect"] != 0.0
        _check_invariant(r)

    def test_u19_mixed_sign_returns(self):
        """U19: Mixed positive and negative returns across industries."""
        df = _make_df([
            {"industry": "A", "Wp": 0.3, "Wb": 0.3, "Rp": 0.15, "Rb": 0.10},
            {"industry": "B", "Wp": 0.3, "Wb": 0.3, "Rp": -0.05, "Rb": -0.03},
            {"industry": "C", "Wp": 0.4, "Wb": 0.4, "Rp": 0.02, "Rb": -0.01},
        ])
        r = compute_attribution(df, mode="BF3")
        _check_invariant(r)

    def test_u20_very_small_weights(self):
        """U20: Very small weights (1e-6) — no division errors."""
        df = _make_df([
            {"industry": "A", "Wp": 1e-6, "Wb": 1e-6, "Rp": 0.05, "Rb": 0.03},
            {"industry": "B", "Wp": 1.0 - 1e-6, "Wb": 1.0 - 1e-6, "Rp": 0.08, "Rb": 0.06},
        ])
        r = compute_attribution(df, mode="BF2")
        _check_invariant(r)
        # Contributions from A should be near zero
        row_a = r["detail"][r["detail"]["industry"] == "A"]
        assert abs(row_a.iloc[0]["total_contrib"]) < 1e-4


class TestBrinsonInputErrors:
    """Edge case error handling."""

    def test_e01_empty_dataframe(self):
        """E1: Empty DataFrame raises ValueError."""
        with pytest.raises(ValueError):
            compute_attribution(pd.DataFrame())

    def test_e02_missing_column(self):
        """E2: Missing 'Rb' column raises ValueError."""
        df = _make_df([{"industry": "A", "Wp": 0.5, "Wb": 0.5, "Rp": 0.05}])
        with pytest.raises(ValueError, match="Missing required columns"):
            compute_attribution(df)

    def test_e04_negative_weights_short_position(self):
        """E4: Negative weights (short) — computes, invariant holds."""
        df = _make_df([
            {"industry": "A", "Wp": 1.1, "Wb": 0.5, "Rp": 0.10, "Rb": 0.05},
            {"industry": "B", "Wp": -0.1, "Wb": 0.5, "Rp": 0.03, "Rb": 0.04},
        ])
        r = compute_attribution(df, mode="BF2")
        _check_invariant(r)
