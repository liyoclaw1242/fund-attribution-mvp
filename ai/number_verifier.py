"""Regex-based number verification for AI-generated text.

Extracts all percentages from response text.
Compares each to source AttributionResult values (tolerance: 0.01%).
Returns pass/fail with details.
"""

import re
from dataclasses import dataclass

# Match patterns like: 8.50%, -2.29%, +1.50%, 0.30%
PERCENT_PATTERN = re.compile(r"[+-]?\d+\.?\d*%")

# Tolerance for number comparison (0.01% = 0.0001 in decimal)
TOLERANCE = 0.0001


@dataclass
class VerificationResult:
    passed: bool
    extracted_numbers: list[float]  # percentages as decimals (e.g., 8.5% -> 0.085)
    source_numbers: list[float]
    mismatches: list[dict]  # [{extracted, closest_source, diff}]


def extract_percentages(text: str) -> list[float]:
    """Extract all percentage values from text, convert to decimal.

    '8.50%' -> 0.085, '-2.29%' -> -0.0229
    """
    matches = PERCENT_PATTERN.findall(text)
    values = []
    for m in matches:
        try:
            pct = float(m.rstrip("%"))
            values.append(pct / 100.0)
        except ValueError:
            continue
    return values


def get_source_numbers(result: dict) -> list[float]:
    """Extract all verifiable numbers from an AttributionResult.

    Returns list of decimal values that might appear in AI text.
    """
    numbers = [
        result["fund_return"],
        result["bench_return"],
        result["excess_return"],
        result["allocation_total"],
        result["selection_total"],
    ]

    if result.get("interaction_total") is not None:
        numbers.append(result["interaction_total"])

    # Add detail-level numbers (industry contributions)
    detail = result.get("detail")
    if detail is not None:
        for _, row in detail.iterrows():
            numbers.extend([
                row.get("Rp", 0),
                row.get("Rb", 0),
                row.get("alloc_effect", 0),
                row.get("select_effect", 0),
                row.get("total_contrib", 0),
            ])

    # Add top/bottom contributor numbers
    for key in ("top_contributors", "bottom_contributors"):
        contributors = result.get(key)
        if contributors is not None:
            for _, row in contributors.iterrows():
                numbers.append(row.get("total_contrib", 0))

    return [n for n in numbers if n is not None]


def find_closest(value: float, source_numbers: list[float]) -> tuple[float, float]:
    """Find the closest source number and return (closest, diff)."""
    if not source_numbers:
        return (0.0, abs(value))
    closest = min(source_numbers, key=lambda s: abs(s - value))
    return (closest, abs(value - closest))


def verify_numbers(text: str, result: dict) -> VerificationResult:
    """Verify all percentages in AI text against source AttributionResult.

    Args:
        text: AI-generated text containing percentages.
        result: AttributionResult dict with source numbers.

    Returns:
        VerificationResult with pass/fail and mismatch details.
    """
    extracted = extract_percentages(text)
    source = get_source_numbers(result)

    if not extracted:
        # No numbers to verify — pass by default
        return VerificationResult(
            passed=True,
            extracted_numbers=extracted,
            source_numbers=source,
            mismatches=[],
        )

    mismatches = []
    for ext in extracted:
        closest, diff = find_closest(ext, source)
        if diff > TOLERANCE:
            mismatches.append({
                "extracted": ext,
                "closest_source": closest,
                "diff": diff,
            })

    return VerificationResult(
        passed=len(mismatches) == 0,
        extracted_numbers=extracted,
        source_numbers=source,
        mismatches=mismatches,
    )
