"""Validation rules for attribution pipeline.

Checks:
  - Brinson assertion: alloc + select (+ interaction) = excess (tolerance < 1e-10)
  - Fund weights sum to 1.0 (tolerance +/- 0.02)
  - Benchmark weights sum to 1.0 (exact)
  - No single industry weight > 0.60
  - Monthly returns between -0.50 and +0.50
  - SITCA data within 45 days of analysis period
  - Unmapped weight thresholds: <3% WARN, >=3% PROMINENT WARN, >=10% BLOCK
"""

# TODO: Implement — see Issue #7

raise NotImplementedError("See GitHub Issue")
