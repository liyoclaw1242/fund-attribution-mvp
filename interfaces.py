"""
Internal API contracts — type definitions for all module interfaces.
Based on MVP Blueprint v1.1, Section 8.
"""

from dataclasses import dataclass, field
from typing import TypedDict, List, Dict, Optional

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


# --- 8.4 Client Portfolio (v2.0) ---

@dataclass
class Client:
    client_id: str
    name: str
    kyc_risk_level: str = "moderate"
    created_at: str = ""


@dataclass
class ClientHolding:
    client_id: str
    fund_code: str
    bank_name: str = ""
    shares: float = 0.0
    cost_basis: float = 0.0
    added_at: str = ""


# --- 8.5 Fee Transparency (v2.0) ---

@dataclass
class FundFee:
    """Fee info for a single fund holding."""
    fund_code: str
    fund_name: str
    ter: float                  # total expense ratio, decimal (e.g. 0.015 = 1.5%)
    market_value: float         # TWD
    annual_fee: float           # TWD (market_value * ter)


@dataclass
class Alternative:
    """Low-cost alternative suggestion."""
    current_fund: str
    suggested_fund: str
    suggested_name: str
    current_ter: float
    suggested_ter: float
    ter_savings: float          # decimal
    annual_savings: float       # TWD
    category: str = ""


@dataclass
class FeeReport:
    """Full fee transparency report for a client."""
    client_id: str
    total_market_value: float   # TWD
    weighted_ter: float         # portfolio-weighted TER
    total_annual_fee: float     # TWD
    fund_fees: List[FundFee] = field(default_factory=list)
    alternatives: List[Alternative] = field(default_factory=list)


# --- 8.6 Goal Tracking (v2.0) ---

@dataclass
class GoalConfig:
    """Client financial goal configuration."""
    target_amount: float        # TWD
    target_year: int            # e.g. 2040
    monthly_contribution: float # TWD per month
    risk_tolerance: str = "moderate"  # conservative, moderate, aggressive
    goal_type: str = "retirement"     # retirement, house, education
    current_savings: float = 0.0      # TWD, starting balance


@dataclass
class GoalSimResult:
    """Monte Carlo simulation result for a financial goal."""
    success_probability: float  # 0.0–1.0
    median_outcome: float       # TWD, p50
    p10_outcome: float          # TWD, pessimistic
    p90_outcome: float          # TWD, optimistic
    target_amount: float        # TWD, for reference
    years_to_goal: int
    num_paths: int
    suggestions: List[str] = field(default_factory=list)


# --- 8.8 Portfolio Health Check (v2.0) ---

@dataclass
class HealthIssue:
    """A single health check finding."""
    check_type: str             # concentration, asset_class, kyc_mismatch
    severity: str               # warning, critical
    description: str            # Chinese description
    suggestion: str             # Chinese suggestion


@dataclass
class HealthCheckResult:
    """Full portfolio health check result."""
    client_id: str
    total_value: float          # TWD
    bank_breakdown: Dict[str, float] = field(default_factory=dict)
    issues: List[HealthIssue] = field(default_factory=list)
