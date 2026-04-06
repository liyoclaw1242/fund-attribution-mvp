"""Validation rules for attribution pipeline.

Each validation function returns a ValidationResult with:
  - rule: name of the rule
  - level: "pass", "warn", or "block"
  - message: human-readable description

validate_all() runs all checks and returns a summary.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from config.settings import UNMAPPED_WARN_THRESHOLD, UNMAPPED_BLOCK_THRESHOLD

logger = logging.getLogger(__name__)

BRINSON_TOLERANCE = 1e-10
FUND_WEIGHT_TOLERANCE = 0.02
MAX_SINGLE_INDUSTRY_WEIGHT = 0.60
MIN_MONTHLY_RETURN = -0.50
MAX_MONTHLY_RETURN = 0.50
DATA_STALENESS_DAYS = 45


@dataclass
class ValidationResult:
    rule: str
    level: str  # "pass", "warn", "block"
    message: str


def validate_brinson_assertion(
    allocation_total: float,
    selection_total: float,
    excess_return: float,
    interaction_total: Optional[float] = None,
) -> ValidationResult:
    """Check: alloc + select (+ interaction) = excess return."""
    if interaction_total is not None:
        computed = allocation_total + selection_total + interaction_total
    else:
        computed = allocation_total + selection_total

    diff = abs(computed - excess_return)
    if diff < BRINSON_TOLERANCE:
        return ValidationResult("brinson_assertion", "pass", f"Invariant holds (diff={diff:.2e})")
    return ValidationResult("brinson_assertion", "block", f"Invariant violated: {computed} != {excess_return} (diff={diff:.2e})")


def validate_fund_weights(holdings: pd.DataFrame) -> ValidationResult:
    """Check: fund weights (Wp) sum to 1.0 within tolerance."""
    total = holdings["Wp"].sum() if "Wp" in holdings.columns else holdings["weight"].sum()
    diff = abs(total - 1.0)
    if diff <= FUND_WEIGHT_TOLERANCE:
        return ValidationResult("fund_weights", "pass", f"Sum={total:.4f} (diff={diff:.4f})")
    return ValidationResult("fund_weights", "block", f"Fund weights sum to {total:.4f}, exceeds tolerance ±{FUND_WEIGHT_TOLERANCE}")


def validate_benchmark_weights(holdings: pd.DataFrame) -> ValidationResult:
    """Check: benchmark weights (Wb) sum to 1.0 exactly."""
    if "Wb" not in holdings.columns:
        return ValidationResult("benchmark_weights", "pass", "No benchmark weights column — skipping")
    total = holdings["Wb"].sum()
    diff = abs(total - 1.0)
    if diff < 1e-10:
        return ValidationResult("benchmark_weights", "pass", f"Sum={total:.10f}")
    return ValidationResult("benchmark_weights", "block", f"Benchmark weights sum to {total:.10f}, expected exactly 1.0")


def validate_single_industry_weight(holdings: pd.DataFrame) -> ValidationResult:
    """Check: no single industry weight > 60%."""
    weight_col = "Wp" if "Wp" in holdings.columns else "weight"
    if weight_col not in holdings.columns:
        return ValidationResult("single_industry_weight", "pass", "No weight column — skipping")

    industry_col = "industry"
    max_row = holdings.loc[holdings[weight_col].idxmax()]
    max_weight = max_row[weight_col]
    max_industry = max_row[industry_col] if industry_col in holdings.columns else "unknown"

    if max_weight <= MAX_SINGLE_INDUSTRY_WEIGHT:
        return ValidationResult("single_industry_weight", "pass", f"Max={max_weight:.2%} ({max_industry})")
    return ValidationResult(
        "single_industry_weight", "warn",
        f"{max_industry} weight={max_weight:.2%} exceeds {MAX_SINGLE_INDUSTRY_WEIGHT:.0%} sanity check"
    )


def validate_monthly_returns(holdings: pd.DataFrame) -> ValidationResult:
    """Check: all monthly returns between -50% and +50%."""
    return_col = "Rp" if "Rp" in holdings.columns else "return_rate"
    if return_col not in holdings.columns:
        return ValidationResult("monthly_returns", "pass", "No return column — skipping")

    returns = holdings[return_col].dropna()
    out_of_range = returns[(returns < MIN_MONTHLY_RETURN) | (returns > MAX_MONTHLY_RETURN)]

    if out_of_range.empty:
        return ValidationResult("monthly_returns", "pass", f"All {len(returns)} returns within [{MIN_MONTHLY_RETURN}, {MAX_MONTHLY_RETURN}]")

    industries = holdings.loc[out_of_range.index, "industry"].tolist() if "industry" in holdings.columns else []
    return ValidationResult(
        "monthly_returns", "warn",
        f"{len(out_of_range)} returns out of range: {industries} values={out_of_range.tolist()}"
    )


def validate_data_staleness(
    data_timestamp: Optional[str | datetime] = None,
    analysis_date: Optional[datetime] = None,
) -> ValidationResult:
    """Check: SITCA data timestamp within 45 days of analysis period."""
    if data_timestamp is None:
        return ValidationResult("data_staleness", "warn", "No data timestamp provided — cannot verify freshness")

    if isinstance(data_timestamp, str):
        data_timestamp = datetime.fromisoformat(data_timestamp)

    if analysis_date is None:
        analysis_date = datetime.now()

    age_days = (analysis_date - data_timestamp).days
    if age_days <= DATA_STALENESS_DAYS:
        return ValidationResult("data_staleness", "pass", f"Data age: {age_days} days (limit: {DATA_STALENESS_DAYS})")
    return ValidationResult("data_staleness", "block", f"Data is {age_days} days old, exceeds {DATA_STALENESS_DAYS}-day limit")


def validate_unmapped_weight(
    unmapped_weight: float,
    total_weight: float = 1.0,
) -> ValidationResult:
    """Check: unmapped industry weight thresholds."""
    if total_weight == 0:
        return ValidationResult("unmapped_weight", "pass", "Total weight is 0 — skipping")

    ratio = unmapped_weight / total_weight

    if ratio >= UNMAPPED_BLOCK_THRESHOLD:
        return ValidationResult(
            "unmapped_weight", "block",
            f"Unmapped weight {ratio:.1%} >= {UNMAPPED_BLOCK_THRESHOLD:.0%} — report generation blocked"
        )
    if ratio >= UNMAPPED_WARN_THRESHOLD:
        return ValidationResult(
            "unmapped_weight", "warn",
            f"Unmapped weight {ratio:.1%} >= {UNMAPPED_WARN_THRESHOLD:.0%} — prominent warning required"
        )
    return ValidationResult("unmapped_weight", "pass", f"Unmapped weight {ratio:.1%} (below {UNMAPPED_WARN_THRESHOLD:.0%} threshold)")


def validate_all(
    holdings: pd.DataFrame,
    attribution_result: Optional[dict] = None,
    unmapped_weight: float = 0.0,
    data_timestamp: Optional[str | datetime] = None,
) -> list[ValidationResult]:
    """Run all validation rules and return results.

    Args:
        holdings: Fund holdings DataFrame.
        attribution_result: Output from compute_attribution (optional).
        unmapped_weight: Total weight of unmapped industries.
        data_timestamp: When the SITCA data was fetched.

    Returns:
        List of ValidationResult. Any "block" result means report should not be generated.
    """
    results = []

    # Holdings-level checks
    results.append(validate_fund_weights(holdings))
    results.append(validate_benchmark_weights(holdings))
    results.append(validate_single_industry_weight(holdings))
    results.append(validate_monthly_returns(holdings))
    results.append(validate_data_staleness(data_timestamp))
    results.append(validate_unmapped_weight(unmapped_weight))

    # Attribution-level check
    if attribution_result is not None:
        results.append(validate_brinson_assertion(
            allocation_total=attribution_result["allocation_total"],
            selection_total=attribution_result["selection_total"],
            excess_return=attribution_result["excess_return"],
            interaction_total=attribution_result.get("interaction_total"),
        ))

    # Log results
    for r in results:
        if r.level == "block":
            logger.error("[%s] BLOCK: %s", r.rule, r.message)
        elif r.level == "warn":
            logger.warning("[%s] WARN: %s", r.rule, r.message)

    return results


def has_blockers(results: list[ValidationResult]) -> bool:
    """Check if any validation result is a blocker."""
    return any(r.level == "block" for r in results)
