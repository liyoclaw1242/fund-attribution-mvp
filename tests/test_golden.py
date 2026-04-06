"""Golden dataset tests — engine output must match hand-calculated Excel.

These are the most important tests in the system.
If golden tests fail, no code may be merged to main.

Golden data: tests/golden_data/fund_1.xlsx, fund_2.xlsx, fund_3.xlsx
(hand-calculated by ARCH in Sprint 0, verified via generate_golden.py)
"""

import pathlib

import pandas as pd
import pytest

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden_data"


def _load_golden(fund_n: int) -> dict:
    """Load golden dataset for fund N. Returns dict of DataFrames."""
    path = GOLDEN_DIR / f"fund_{fund_n}.xlsx"
    assert path.exists(), f"Golden file not found: {path}"
    return {
        "holdings": pd.read_excel(path, sheet_name="holdings"),
        "bf2": pd.read_excel(path, sheet_name="bf2"),
        "bf3": pd.read_excel(path, sheet_name="bf3"),
        "summary": pd.read_excel(path, sheet_name="summary"),
    }


def _get_summary_value(summary_df: pd.DataFrame, metric: str, mode: str) -> float:
    row = summary_df[summary_df["metric"] == metric]
    assert len(row) == 1, f"Expected 1 row for {metric}, got {len(row)}"
    return float(row[mode].iloc[0])


@pytest.mark.skip(reason="Engine not yet implemented — awaiting Issue #7")
def test_golden_fund1_bf2():
    """Yuanta Taiwan 50 — BF2 mode must match Excel to 6 decimal places."""
    golden = _load_golden(1)
    holdings = golden["holdings"]
    expected = golden["summary"]

    # When engine is implemented:
    # from engine.brinson import compute_attribution
    # result = compute_attribution(holdings, mode="BF2")
    # assert abs(result["fund_return"] - _get_summary_value(expected, "fund_return", "bf2")) < 1e-6
    # assert abs(result["excess_return"] - _get_summary_value(expected, "excess_return", "bf2")) < 1e-6
    # assert abs(result["allocation_total"] - _get_summary_value(expected, "allocation_total", "bf2")) < 1e-6
    # assert abs(result["selection_total"] - _get_summary_value(expected, "selection_total", "bf2")) < 1e-6


@pytest.mark.skip(reason="Engine not yet implemented — awaiting Issue #7")
def test_golden_fund1_bf3():
    """Yuanta Taiwan 50 — BF3 mode must match Excel to 6 decimal places."""
    golden = _load_golden(1)
    expected = golden["summary"]

    # When engine is implemented:
    # result = compute_attribution(holdings, mode="BF3")
    # assert abs(result["interaction_total"] - _get_summary_value(expected, "interaction_total", "bf3")) < 1e-6


@pytest.mark.skip(reason="Engine not yet implemented — awaiting Issue #7")
def test_golden_fund2_bf2():
    """Fubon Taiwan 50 — BF2 mode must match Excel."""
    golden = _load_golden(2)
    expected = golden["summary"]

    # fund_return ≈ 0.05566, excess ≈ 0.00196


@pytest.mark.skip(reason="Engine not yet implemented — awaiting Issue #7")
def test_golden_fund3_bf2():
    """Technology fund with cash — BF2, cash allocation effect must be negative."""
    golden = _load_golden(3)
    bf2_detail = golden["bf2"]

    # Cash row should have negative allocation effect
    cash_row = bf2_detail[bf2_detail["industry"] == "現金"]
    assert len(cash_row) == 1, "Cash row must exist in fund 3"
    # assert cash_row["bf2_allocation"].iloc[0] < 0, "Cash allocation effect must be negative"


@pytest.mark.skip(reason="Engine not yet implemented — awaiting Issue #7")
def test_golden_fund3_bf3():
    """Technology fund with cash — BF3, verify interaction effect is negative for cash."""
    golden = _load_golden(3)
    bf3_detail = golden["bf3"]

    # Cash: Wp=10%, Wb=0%, Rp=0%, Rb=0%
    # Interaction = (0.10 - 0.00) * (0.00 - 0.00) = 0.00 (no interaction for cash)
    # Allocation is the main drag: (0.10 - 0.00) * (0.00 - Rb_total) < 0
