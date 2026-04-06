"""Golden dataset tests — engine output must match hand-calculated Excel.

These are the most important tests in the system.
If golden tests fail, no code may be merged to main.

Golden data: tests/golden_data/fund_1.xlsx, fund_2.xlsx, fund_3.xlsx
(hand-calculated by ARCH in Sprint 0, verified via generate_golden.py)
"""

import pathlib

import pandas as pd
import pytest

from engine.brinson import compute_attribution

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden_data"
TOLERANCE = 1e-10


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


def _get_summary_value(summary_df: pd.DataFrame, metric: str, mode: str):
    row = summary_df[summary_df["metric"] == metric]
    assert len(row) == 1, f"Expected 1 row for {metric}, got {len(row)}"
    val = row[mode].iloc[0]
    return float(val) if pd.notna(val) else None


def _assert_close(actual, expected, label):
    assert abs(actual - expected) < TOLERANCE, (
        f"{label}: {actual} != {expected} (diff={abs(actual - expected)})"
    )


# ============================================================
# Fund 1: 元大台灣50 (0050) — BF2
# ============================================================
def test_golden_fund1_bf2():
    """Yuanta Taiwan 50 — BF2 mode must match Excel."""
    golden = _load_golden(1)
    result = compute_attribution(golden["holdings"], mode="BF2")
    expected = golden["summary"]

    _assert_close(result["fund_return"], _get_summary_value(expected, "fund_return", "bf2"), "fund_return")
    _assert_close(result["bench_return"], _get_summary_value(expected, "bench_return", "bf2"), "bench_return")
    _assert_close(result["excess_return"], _get_summary_value(expected, "excess_return", "bf2"), "excess_return")
    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf2"), "allocation_total")
    _assert_close(result["selection_total"], _get_summary_value(expected, "selection_total", "bf2"), "selection_total")
    assert result["interaction_total"] is None


# ============================================================
# Fund 1: 元大台灣50 (0050) — BF3
# ============================================================
def test_golden_fund1_bf3():
    """Yuanta Taiwan 50 — BF3 mode must match Excel."""
    golden = _load_golden(1)
    result = compute_attribution(golden["holdings"], mode="BF3")
    expected = golden["summary"]

    _assert_close(result["fund_return"], _get_summary_value(expected, "fund_return", "bf3"), "fund_return")
    _assert_close(result["excess_return"], _get_summary_value(expected, "excess_return", "bf3"), "excess_return")
    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf3"), "allocation_total")
    _assert_close(result["selection_total"], _get_summary_value(expected, "selection_total", "bf3"), "selection_total")
    _assert_close(result["interaction_total"], _get_summary_value(expected, "interaction_total", "bf3"), "interaction_total")


# ============================================================
# Fund 2: 富邦台50 (006208) — BF2 + BF3
# ============================================================
def test_golden_fund2_bf2():
    """Fubon Taiwan 50 — BF2 mode must match Excel."""
    golden = _load_golden(2)
    result = compute_attribution(golden["holdings"], mode="BF2")
    expected = golden["summary"]

    _assert_close(result["fund_return"], _get_summary_value(expected, "fund_return", "bf2"), "fund_return")
    _assert_close(result["excess_return"], _get_summary_value(expected, "excess_return", "bf2"), "excess_return")
    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf2"), "allocation_total")
    _assert_close(result["selection_total"], _get_summary_value(expected, "selection_total", "bf2"), "selection_total")


def test_golden_fund2_bf3():
    """Fubon Taiwan 50 — BF3 mode must match Excel."""
    golden = _load_golden(2)
    result = compute_attribution(golden["holdings"], mode="BF3")
    expected = golden["summary"]

    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf3"), "allocation_total")
    _assert_close(result["selection_total"], _get_summary_value(expected, "selection_total", "bf3"), "selection_total")
    _assert_close(result["interaction_total"], _get_summary_value(expected, "interaction_total", "bf3"), "interaction_total")


# ============================================================
# Fund 3: 科技型基金 (含現金) — BF2
# ============================================================
def test_golden_fund3_bf2():
    """Technology fund with cash — BF2, cash allocation effect must be negative."""
    golden = _load_golden(3)
    result = compute_attribution(golden["holdings"], mode="BF2")
    expected = golden["summary"]

    _assert_close(result["fund_return"], _get_summary_value(expected, "fund_return", "bf2"), "fund_return")
    _assert_close(result["excess_return"], _get_summary_value(expected, "excess_return", "bf2"), "excess_return")
    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf2"), "allocation_total")

    # Cash row must have negative allocation effect
    detail = result["detail"]
    cash = detail[detail["industry"] == "現金"]
    assert len(cash) == 1, "Cash row must exist"
    assert cash.iloc[0]["alloc_effect"] < 0, "Cash allocation effect must be negative in up market"


# ============================================================
# Fund 3: 科技型基金 (含現金) — BF3
# ============================================================
def test_golden_fund3_bf3():
    """Technology fund with cash — BF3, verify all effects."""
    golden = _load_golden(3)
    result = compute_attribution(golden["holdings"], mode="BF3")
    expected = golden["summary"]

    _assert_close(result["allocation_total"], _get_summary_value(expected, "allocation_total", "bf3"), "allocation_total")
    _assert_close(result["selection_total"], _get_summary_value(expected, "selection_total", "bf3"), "selection_total")
    _assert_close(result["interaction_total"], _get_summary_value(expected, "interaction_total", "bf3"), "interaction_total")

    # Cash interaction: (0.10 - 0.00) * (0.00 - 0.00) = 0.00
    detail = result["detail"]
    cash = detail[detail["industry"] == "現金"]
    assert abs(cash.iloc[0]["interaction_effect"]) < 1e-10, "Cash interaction should be zero"
