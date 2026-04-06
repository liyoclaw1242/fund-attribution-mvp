"""Claude API client with number verification and fallback.

Pipeline:
  1. prompt_builder constructs prompt from AttributionResult
  2. Call Claude API with 10s timeout
  3. number_verifier extracts all % from response, compares to source
  4. If ALL match: use AI summary. If ANY mismatch: rule-based fallback.
"""

# TODO: Implement — see Issue #9

raise NotImplementedError("See GitHub Issue")
