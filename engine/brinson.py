"""Brinson-Fachler attribution engine.

Supports two modes:
  BF2 (default): 2-effect — interaction merged into selection
    Allocation: (Wp,i - Wb,i) * (Rb,i - Rb)
    Selection:  Wp,i * (Rp,i - Rb,i)

  BF3: 3-effect — standard Brinson-Fachler (1985)
    Allocation:  (Wp,i - Wb,i) * (Rb,i - Rb)
    Selection:   Wb,i * (Rp,i - Rb,i)
    Interaction: (Wp,i - Wb,i) * (Rp,i - Rb,i)

Cash: separate industry, return=0%, benchmark weight=0%.
Assertion: effects must sum to excess return (tolerance < 1e-10).
"""

import pandas as pd
import numpy as np

from interfaces import AttributionResult

TOLERANCE = 1e-10


def compute_attribution(
    holdings: pd.DataFrame,
    mode: str = "BF2",
) -> AttributionResult:
    """Compute Brinson-Fachler attribution.

    Args:
        holdings: DataFrame with columns [industry, Wp, Wb, Rp, Rb].
            Wp/Wb = fund/benchmark weight (proportions, sum ≈ 1.0).
            Rp/Rb = fund/benchmark return (decimals, e.g. 0.08 = 8%).
        mode: "BF2" (2-factor) or "BF3" (3-factor).

    Returns:
        AttributionResult dict.

    Raises:
        ValueError: If mode is invalid or required columns are missing.
    """
    mode = mode.upper()
    if mode not in ("BF2", "BF3"):
        raise ValueError(f"Invalid mode: {mode}. Must be 'BF2' or 'BF3'.")

    required = ["industry", "Wp", "Wb", "Rp", "Rb"]
    missing = [c for c in required if c not in holdings.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df = holdings.copy()

    # Total returns (weighted sums)
    fund_return = (df["Wp"] * df["Rp"]).sum()
    bench_return = (df["Wb"] * df["Rb"]).sum()
    excess_return = fund_return - bench_return

    # Allocation effect (same for both modes)
    df["alloc_effect"] = (df["Wp"] - df["Wb"]) * (df["Rb"] - bench_return)

    if mode == "BF2":
        # Selection includes interaction
        df["select_effect"] = df["Wp"] * (df["Rp"] - df["Rb"])
        df["interaction_effect"] = 0.0
        df["total_contrib"] = df["alloc_effect"] + df["select_effect"]
    else:
        # BF3: pure selection + separate interaction
        df["select_effect"] = df["Wb"] * (df["Rp"] - df["Rb"])
        df["interaction_effect"] = (df["Wp"] - df["Wb"]) * (df["Rp"] - df["Rb"])
        df["total_contrib"] = df["alloc_effect"] + df["select_effect"] + df["interaction_effect"]

    # Aggregate totals
    allocation_total = df["alloc_effect"].sum()
    selection_total = df["select_effect"].sum()
    interaction_total = df["interaction_effect"].sum() if mode == "BF3" else None

    # Invariant check: effects must sum to excess return
    if mode == "BF2":
        check_sum = allocation_total + selection_total
    else:
        check_sum = allocation_total + selection_total + interaction_total

    assert abs(check_sum - excess_return) < TOLERANCE, (
        f"Brinson invariant violated: {check_sum} != {excess_return} "
        f"(diff={abs(check_sum - excess_return)})"
    )

    # Unmapped industry tracking
    unmapped_industries = []
    unmapped_weight = 0.0

    # Detail DataFrame
    detail = df[["industry", "Wp", "Wb", "Rp", "Rb",
                  "alloc_effect", "select_effect", "interaction_effect",
                  "total_contrib"]].copy()

    # Top/bottom contributors by total_contrib
    sorted_detail = detail.sort_values("total_contrib", ascending=False)
    top_contributors = sorted_detail.head(3).reset_index(drop=True)
    bottom_contributors = sorted_detail.tail(3).sort_values("total_contrib").reset_index(drop=True)

    return AttributionResult(
        fund_return=fund_return,
        bench_return=bench_return,
        excess_return=excess_return,
        allocation_total=allocation_total,
        selection_total=selection_total,
        interaction_total=interaction_total,
        brinson_mode=mode,
        detail=detail,
        top_contributors=top_contributors,
        bottom_contributors=bottom_contributors,
        validation_passed=True,
        unmapped_weight=unmapped_weight,
        unmapped_industries=unmapped_industries,
    )
