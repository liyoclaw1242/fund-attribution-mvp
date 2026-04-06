"""Golden dataset tests — engine output must match hand-calculated Excel.

These are the most important tests in the system.
If golden tests fail, no code may be merged to main.

Requires: tests/golden_data/fund_1.xlsx, fund_2.xlsx, fund_3.xlsx
(hand-calculated by ARCH in Sprint 0)
"""

import pytest


@pytest.mark.skip(reason="Golden dataset not yet prepared — Sprint 0 deliverable")
def test_golden_fund1_bf2():
    """Yuanta Taiwan 50 — BF2 mode must match Excel to 6 decimal places."""
    pass


@pytest.mark.skip(reason="Golden dataset not yet prepared — Sprint 0 deliverable")
def test_golden_fund1_bf3():
    """Yuanta Taiwan 50 — BF3 mode must match Excel."""
    pass


@pytest.mark.skip(reason="Golden dataset not yet prepared — Sprint 0 deliverable")
def test_golden_fund2_bf2():
    """Fubon Taiwan 50 — BF2 mode must match Excel."""
    pass


@pytest.mark.skip(reason="Golden dataset not yet prepared — Sprint 0 deliverable")
def test_golden_fund3_bf2():
    """Technology fund with cash — BF2, cash effect is negative."""
    pass
