# TWSE OpenAPI Health Check Report

**Date**: 2026-04-06
**Agent**: be-20260406-0956264

## Summary

| Endpoint | URL | Status | Records | Notes |
|----------|-----|--------|---------|-------|
| MI_INDEX | `/v1/exchangeReport/MI_INDEX` | ✅ OK | 267 | Industry indices — primary data source |
| TWT49U | `/v1/exchangeReport/TWT49U` | ❌ FAIL | — | Returns HTML 404; endpoint deprecated/removed |
| BWIBBU_d | `/v1/exchangeReport/BWIBBU_d` | ✅ OK | 1,070 | Individual stock P/E, P/B, dividend yield |

## Endpoint Details

### MI_INDEX (✅ Available)

- **Purpose**: Market industry indices — closing price, daily change %
- **Fields**: `日期`, `指數`, `收盤指數`, `漲跌`, `漲跌點數`, `漲跌百分比`, `特殊處理註記`
- **Use case**: Benchmark industry returns for Brinson attribution
- **Industry coverage**: 28+ TSE industry indices (半導體, 金融保險, 電子工業, etc.)

### TWT49U (❌ Unavailable — needs fallback)

- **Purpose**: Weighted return index by industry
- **Status**: Endpoint returns 302 redirect → HTML 404 page (not JSON)
- **Root cause**: Likely deprecated by TWSE; no longer in their OpenAPI catalogue
- **Fallback strategy**:
  1. **Primary**: Compute weighted returns from MI_INDEX closing indices (calculate period returns from consecutive dates)
  2. **Secondary**: Manual CSV upload if MI_INDEX lacks historical depth

### BWIBBU_d (✅ Available)

- **Purpose**: Individual stock fundamentals (P/E, P/B, dividend yield)
- **Fields**: `Date`, `Code`, `Name`, `ClosePrice`, `DividendYield`, `DividendYear`, `PEratio`, `PBratio`, `FiscalYearQuarter`
- **Use case**: Supplementary data for fund holdings analysis

## Known Issues

### SSL Certificate

TWSE's SSL certificate is missing the Subject Key Identifier extension. This causes Python's default SSL verification to fail.

**Workaround**: Use `verify=False` with `requests` library + suppress `InsecureRequestWarning`. This is acceptable because:
- TWSE is a government-operated open data API
- Data is public market information (not sensitive)
- `curl` handles the connection fine — it's a strict Python SSL check

**Recommendation**: Add `TWSE_SSL_VERIFY` env var to `config/settings.py` (default `False`) so this can be toggled.

### Rate Limiting

TWSE enforces ~3 requests per 5 seconds. Current `TWSE_RATE_LIMIT_DELAY=2.0s` in settings.py is appropriate.

## Recommendations for twse_client.py (Issue #4)

1. Use MI_INDEX as the primary benchmark data source
2. Compute period returns from consecutive MI_INDEX snapshots (no TWT49U needed)
3. Add BWIBBU_d as optional enrichment data
4. Implement `verify=False` with configurable SSL setting
5. Cache responses in SQLite with 24h TTL (already planned)
6. Support manual CSV fallback when API is unreachable
