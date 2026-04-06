"""Build structured prompt from AttributionResult for Claude API.

Output: 3 variants
  - LINE message: <100 chars Chinese with emoji
  - PDF summary: 150-200 chars professional Chinese
  - Advisor note: <50 chars metrics only

Prompt principles:
  - Role: senior investment research director
  - Forbidden terms: Brinson, attribution, allocation effect, selection effect
  - Use: market positioning, stock-picking ability, sector exposure
  - Instruction: use ONLY exact numbers provided, do NOT round/adjust/estimate
"""

# TODO: Implement — see Issue #8

raise NotImplementedError("See GitHub Issue")
