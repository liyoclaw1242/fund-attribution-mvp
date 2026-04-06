"""Fetch industry index data from TWSE OpenAPI.

Endpoints:
  - Weighted Return Index: GET https://openapi.twse.com.tw/v1/exchangeReport/TWT49U
  - Industry Index: GET https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX

Rate limit: 3 req / 5s, 2s delay between requests.
Cache: 24h TTL in SQLite.
"""

# TODO: Implement — see Issue #4
# - Rate limiting (2s delay)
# - 24h cache in SQLite
# - Fallback: manual CSV if API fails
# - Health check script for Day 1

raise NotImplementedError("See GitHub Issue")
