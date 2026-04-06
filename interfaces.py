"""
Internal API contracts — type definitions for all module interfaces.
Based on MVP Blueprint v1.1, Section 8.
"""

from dataclasses import dataclass, field
from typing import TypedDict, List, Optional

import pandas as pd


# --- 8.1 Data Pipeline Output ---

# FundHoldings: pd.DataFrame with columns [industry: str, weight: float, return_rate: float]
# BenchmarkData: dict[str, dict] -> {industry: {weight: float, return: float, index_name: str}}

BenchmarkData = dict[str, dict]


# --- 8.2 Brinson Engine Output ---

class AttributionResult(TypedDict):
    fund_return: float
    bench_return: float
    excess_return: float
    allocation_total: float
    selection_total: float
    interaction_total: Optional[float]  # only in BF3
    brinson_mode: str  # 'BF2' or 'BF3'
    detail: pd.DataFrame  # [industry, Wp, Wb, Rp, Rb, alloc_effect, select_effect, interaction_effect, total_contrib]
    top_contributors: pd.DataFrame
    bottom_contributors: pd.DataFrame
    validation_passed: bool
    unmapped_weight: float
    unmapped_industries: List[str]


# --- 8.3 AI Summary Output ---

class AISummary(TypedDict):
    line_message: str       # <100 chars Chinese with emoji prefix
    pdf_summary: str        # 150-200 chars professional Chinese
    advisor_note: str       # <50 chars metrics only
    verification_passed: bool
    fallback_used: bool
    ai_prompt: str          # full prompt for debugging


# --- 8.5 Fund Comparison (v2.0) ---

@dataclass
class FundMetrics:
    fund_code: str
    total_return: float
    sharpe_ratio: Optional[float] = None   # simplified single-period
    max_drawdown: Optional[float] = None   # simplified single-period
    sector_weights: Optional[dict] = None  # {industry: weight}
    attribution: Optional[dict] = None     # AttributionResult


@dataclass
class FundComparison:
    funds: list  # List[FundMetrics]
    attribution_diffs: Optional[dict] = None  # per-industry diffs
    ai_explanation: str = ""
