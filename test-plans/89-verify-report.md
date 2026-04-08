# Verify Report: QA: Pipeline integration verification — schema, fetchers, scheduler

- **Issue**: liyoclaw1242/fund-attribution-mvp#89
- **PR**: N/A (integration test, no PR)
- **Verifier**: qa-20260408-0847587
- **Date**: 2026-04-08
- **Verdict**: PASS

## Test Plan Execution

### 1. Schema Idempotency ✅
- 10 tables with `CREATE TABLE IF NOT EXISTS` (9 required + 1 partition default)
- 7 indexes with `CREATE INDEX IF NOT EXISTS`
- All 9 required tables present: stock_info, stock_price, industry_index, industry_weight, fund_info, fund_holding, fund_nav, fx_rate, pipeline_run
- stock_price partitioned by market prefix

### 2. Individual Fetcher Verification ✅
All 9 fetchers import successfully:
| Fetcher | source_name | target_table | Import |
|---------|------------|-------------|--------|
| TwseMiIndexFetcher | twse_mi_index | industry_index | OK |
| TwseStockDayAllFetcher | twse_stock_day_all | stock_price | OK |
| TwseCompanyInfoFetcher | twse_company_info | stock_info | OK |
| FinMindStockInfoFetcher | finmind_stock_info | stock_info | OK |
| SitcaFetcher | sitca | fund_holding | OK |
| FinnhubFundFetcher | finnhub | fund_holding | OK |
| YfinanceFetcher | yfinance | stock_price | OK |
| FxRateFetcher | fx_rate | fx_rate | OK |
| WeightCalculator | weight_calculator | industry_weight | OK |

### 3. Error Isolation ✅
- Scheduler `_run_fetcher` catches all exceptions (tested)
- `pipeline_run` logging via BaseFetcher inheritance (tested)
- Per-fund/ticker error isolation in all fetchers (tested)
- Missing API keys → warning + skip (tested)

### 4. Scheduler ✅
- `python -m pipeline.scheduler` entry point via `__main__.py`
- All 9 cron jobs registered in SCHEDULE_REGISTRY
- Graceful shutdown via SIGTERM/SIGINT handlers
- Health endpoint at /health on port 8080

### 5. Docker ✅
- Dockerfile: python:3.12-slim, curl for HEALTHCHECK, layer-cached pip install
- HEALTHCHECK: `/health` (previously fixed from `/`)
- docker-compose: db (postgres:16-alpine) + pipeline (depends_on healthy) + app (preserved)
- restart: unless-stopped, pgdata volume, env vars
- Note: Docker not available locally — structural verification only

### 6. Data Quality Spot Checks ✅
- FX fallback rates: all 6 pairs in reasonable ranges (USDTWD=32.0, JPYTWD=0.21)
- TSE industry indices: 33 entries, major sectors covered
- Industry mapper: 31 mapping entries loaded from data/mapping.json
- ISIN registry: 50 funds, all valid format

### Full Test Suite
- **98/98 pipeline tests pass** (config: 3, db: 8, fetcher_base: 7, scheduler: 8, tw_fetchers: 18, finnhub: 20, mapper: 13, transformers: 11, international: 10)

## Limitations
- No live PostgreSQL — schema verified structurally, DB operations via mocks
- No live API calls — fetcher logic verified via unit tests
- No Docker build/run — structural config verification only

## Summary

The Data Pipeline service is well-integrated: all 9 fetchers import and register correctly, schema is idempotent with all required tables, error isolation works, scheduler orchestration is solid, and Docker config is properly structured. 98 unit tests cover the full pipeline stack.
