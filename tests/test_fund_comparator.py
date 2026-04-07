"""Tests for engine/fund_comparator.py — fund comparison engine."""

import pandas as pd
import pytest

from engine.fund_comparator import (
    compare_funds,
    _compute_simple_sharpe,
    _compute_attribution_diffs,
    RISK_FREE_RATE,
)
from interfaces import FundMetrics, FundComparison


# ---------------------------------------------------------------------------
# Fixtures — golden-style holdings for test funds
# ---------------------------------------------------------------------------

def _make_holdings(rows: list[dict]) -> pd.DataFrame:
    """Build a holdings DataFrame from dicts."""
    return pd.DataFrame(rows)


FUND_A_HOLDINGS = _make_holdings([
    {"industry": "半導體業", "Wp": 0.40, "Wb": 0.30, "Rp": 0.12, "Rb": 0.08},
    {"industry": "金融保險業", "Wp": 0.30, "Wb": 0.35, "Rp": 0.04, "Rb": 0.05},
    {"industry": "電子零組件業", "Wp": 0.20, "Wb": 0.25, "Rp": 0.06, "Rb": 0.03},
    {"industry": "現金", "Wp": 0.10, "Wb": 0.10, "Rp": 0.00, "Rb": 0.00},
])

FUND_B_HOLDINGS = _make_holdings([
    {"industry": "半導體業", "Wp": 0.25, "Wb": 0.30, "Rp": 0.10, "Rb": 0.08},
    {"industry": "金融保險業", "Wp": 0.35, "Wb": 0.35, "Rp": 0.06, "Rb": 0.05},
    {"industry": "電子零組件業", "Wp": 0.30, "Wb": 0.25, "Rp": 0.02, "Rb": 0.03},
    {"industry": "現金", "Wp": 0.10, "Wb": 0.10, "Rp": 0.00, "Rb": 0.00},
])

FUND_C_HOLDINGS = _make_holdings([
    {"industry": "半導體業", "Wp": 0.50, "Wb": 0.30, "Rp": 0.15, "Rb": 0.08},
    {"industry": "金融保險業", "Wp": 0.20, "Wb": 0.35, "Rp": 0.03, "Rb": 0.05},
    {"industry": "電子零組件業", "Wp": 0.20, "Wb": 0.25, "Rp": 0.07, "Rb": 0.03},
    {"industry": "現金", "Wp": 0.10, "Wb": 0.10, "Rp": 0.00, "Rb": 0.00},
])


HOLDINGS_MAP = {
    "FUND_A": FUND_A_HOLDINGS,
    "FUND_B": FUND_B_HOLDINGS,
    "FUND_C": FUND_C_HOLDINGS,
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestCompareFunds:
    def test_two_funds(self):
        """Basic 2-fund comparison returns valid FundComparison."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            period="2026-03",
            generate_ai=False,
        )
        assert isinstance(result, FundComparison)
        assert len(result.funds) == 2
        assert result.funds[0].fund_code == "FUND_A"
        assert result.funds[1].fund_code == "FUND_B"

    def test_three_funds(self):
        """3-fund comparison."""
        result = compare_funds(
            ["FUND_A", "FUND_B", "FUND_C"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert len(result.funds) == 3

    def test_four_funds(self):
        """4-fund comparison (max)."""
        holdings = {**HOLDINGS_MAP, "FUND_D": FUND_A_HOLDINGS.copy()}
        result = compare_funds(
            ["FUND_A", "FUND_B", "FUND_C", "FUND_D"],
            holdings,
            generate_ai=False,
        )
        assert len(result.funds) == 4

    def test_attribution_results_present(self):
        """Each fund has Brinson attribution results."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert "FUND_A" in result.attribution_results
        assert "FUND_B" in result.attribution_results
        assert "fund_return" in result.attribution_results["FUND_A"]
        assert "excess_return" in result.attribution_results["FUND_B"]

    def test_attribution_diffs_present(self):
        """Pairwise diffs are computed."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert "FUND_A_vs_FUND_B" in result.attribution_diffs
        diff = result.attribution_diffs["FUND_A_vs_FUND_B"]
        assert "excess_return_diff" in diff
        assert "allocation_diff" in diff
        assert "selection_diff" in diff
        assert "sector_diffs" in diff

    def test_three_fund_pairwise_diffs(self):
        """3 funds produce 3 pairwise diffs."""
        result = compare_funds(
            ["FUND_A", "FUND_B", "FUND_C"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert len(result.attribution_diffs) == 3

    def test_sector_weights_populated(self):
        """FundMetrics includes sector weights."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert "半導體業" in result.funds[0].sector_weights
        assert result.funds[0].sector_weights["半導體業"] == pytest.approx(0.40)

    def test_total_return_matches_brinson(self):
        """FundMetrics total_return matches Brinson engine output."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        for fm in result.funds:
            expected = result.attribution_results[fm.fund_code]["fund_return"]
            assert fm.total_return == pytest.approx(expected)

    def test_bf3_mode(self):
        """BF3 mode runs without errors."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            mode="BF3",
            generate_ai=False,
        )
        for code, attr in result.attribution_results.items():
            assert attr["brinson_mode"] == "BF3"
            assert attr["interaction_total"] is not None


# ---------------------------------------------------------------------------
# Sector diffs
# ---------------------------------------------------------------------------

class TestSectorDiffs:
    def test_sector_diff_values(self):
        """Sector weight diffs are correct."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        diffs = result.attribution_diffs["FUND_A_vs_FUND_B"]["sector_diffs"]
        # FUND_A has 40% semi, FUND_B has 25% → diff = +15%
        assert diffs["半導體業"]["weight_diff"] == pytest.approx(0.15)
        # FUND_A has 30% finance, FUND_B has 35% → diff = -5%
        assert diffs["金融保險業"]["weight_diff"] == pytest.approx(-0.05)


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------

class TestSharpe:
    def test_positive_excess(self):
        """Positive return above risk-free produces positive Sharpe."""
        assert _compute_simple_sharpe(0.08) == pytest.approx(0.08 - RISK_FREE_RATE)

    def test_negative_excess(self):
        """Return below risk-free produces negative Sharpe."""
        assert _compute_simple_sharpe(0.005) < 0

    def test_sharpe_in_comparison(self):
        """Sharpe ratio is populated in FundMetrics."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        for fm in result.funds:
            assert fm.sharpe_ratio is not None
            assert fm.sharpe_ratio == pytest.approx(fm.total_return - RISK_FREE_RATE)


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_too_few_funds(self):
        """Reject fewer than 2 funds."""
        with pytest.raises(ValueError, match="Fund count must be 2-4"):
            compare_funds(["FUND_A"], HOLDINGS_MAP, generate_ai=False)

    def test_too_many_funds(self):
        """Reject more than 4 funds."""
        codes = [f"F{i}" for i in range(5)]
        with pytest.raises(ValueError, match="Fund count must be 2-4"):
            compare_funds(codes, HOLDINGS_MAP, generate_ai=False)

    def test_empty_fund_list(self):
        with pytest.raises(ValueError):
            compare_funds([], HOLDINGS_MAP, generate_ai=False)


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulHandling:
    def test_skip_missing_fund(self):
        """Funds not in holdings_map are skipped with warning."""
        result = compare_funds(
            ["FUND_A", "FUND_B", "MISSING_FUND"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert len(result.funds) == 2
        assert "MISSING_FUND" not in result.attribution_results

    def test_error_when_all_missing(self):
        """Raise if fewer than 2 funds have valid data."""
        with pytest.raises(ValueError, match="Need at least 2 funds"):
            compare_funds(
                ["MISSING_1", "MISSING_2"],
                HOLDINGS_MAP,
                generate_ai=False,
            )

    def test_skip_bad_holdings_data(self):
        """Fund with invalid holdings data is skipped."""
        bad_holdings = pd.DataFrame([{"industry": "test", "bad_col": 1}])
        holdings = {
            **HOLDINGS_MAP,
            "BAD_FUND": bad_holdings,
        }
        result = compare_funds(
            ["FUND_A", "FUND_B", "BAD_FUND"],
            holdings,
            generate_ai=False,
        )
        assert len(result.funds) == 2
        assert "BAD_FUND" not in result.attribution_results


# ---------------------------------------------------------------------------
# AI explanation (template fallback)
# ---------------------------------------------------------------------------

class TestAIExplanation:
    def test_template_fallback(self):
        """Without API key, falls back to template explanation."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=True,
            api_key="",
        )
        # Template should mention fund codes and percentages
        assert "FUND_A" in result.ai_explanation or "FUND_B" in result.ai_explanation

    def test_no_ai_when_disabled(self):
        """generate_ai=False produces empty explanation."""
        result = compare_funds(
            ["FUND_A", "FUND_B"],
            HOLDINGS_MAP,
            generate_ai=False,
        )
        assert result.ai_explanation == ""
