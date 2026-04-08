# Verify Report: BE: Pipeline foundation — PostgreSQL schema, db pool, config, BaseFetcher ABC

- **Issue**: liyoclaw1242/fund-attribution-mvp#84
- **PR**: #90
- **Verifier**: qa-20260408-0847587
- **Date**: 2026-04-08
- **Verdict**: FAIL

## Results

| Step | Description | Result | Notes |
|------|-------------|--------|-------|
| A1 | schema.sql creates all 9 tables | PASS | stock_info, stock_price, industry_index, industry_weight, fund_info, fund_holding, fund_nav, fx_rate, pipeline_run |
| A2 | schema.sql is idempotent (IF NOT EXISTS) | PASS | All CREATE TABLE/INDEX use IF NOT EXISTS |
| A3 | schema matches #80 spec columns/types/PKs | PASS | Exact match on all column definitions |
| A4 | stock_price partitioned by market prefix | PASS | PARTITION BY LIST (substring(stock_id, 1, 1)) + default partition |
| A5 | db.py create_pool / close_pool | PASS | asyncpg pool factory with defaults (min=2, max=10) |
| A6 | db.py execute_schema | PASS | Reads schema.sql, executes via pool |
| A7 | db.py log_pipeline_run | PASS | Handles success/running/failed states, returns id |
| A8 | config.py loads env vars with defaults | PASS | PipelineConfig frozen dataclass, from_env() |
| A9 | fetchers/base.py BaseFetcher ABC | PASS | fetch(), transform(), run() with error handling |
| A10 | BaseFetcher._load uses temp table + COPY | PASS | Bulk insert with ON CONFLICT DO NOTHING |
| A11 | __init__.py exports | PASS | All key symbols exported |
| A12 | requirements.txt updated | PASS | asyncpg>=0.29.0 added |
| A13 | Pipeline unit tests (20 tests) | PASS | All 20 pass |
| A14 | Regression: test_sitca_scraper.py | FAIL | 4 tests broken by out-of-scope sitca_scraper.py rewrite |
| A15 | Regression: full test suite | FAIL | 24 failures total (15 pre-existing, 4 new from sitca_scraper, 5 from app.py/fund_lookup) |

## Failures

### A14: test_sitca_scraper.py — 4 regressions introduced by this PR

**Pre-existing on main**: 0 failures (19/19 pass)
**On PR branch**: 4 failures in TestParseHoldingsHtml

- `test_parses_table` — FAIL
- `test_weights_are_decimal` — FAIL
- `test_weights_sum_reasonable` — FAIL
- `test_fund_name_present` — FAIL

**Root cause**: `_parse_holdings_html()` was rewritten to expect `DTodd/DTeven` CSS classes and rowspan-based layout. Existing tests use `<table class="grid">` HTML without those classes, causing `ValueError: No data cells (DTodd/DTeven) found`.

**Severity**: Major — breaks existing SITCA scraper functionality.

**Triage**: -> BE — the `data/sitca_scraper.py` changes are out of scope for issue #84 (pipeline foundation). Either:
1. Revert the sitca_scraper.py changes from this PR, or
2. Update the tests to match the new parser

### A15: Out-of-scope changes

This PR includes changes to 2 files not in the spec:
- `app.py` (+49/-10): fund_lookup import, PDF generation rewrite
- `data/sitca_scraper.py` (+87/-40): Full parser rewrite + SSL verify=False

These changes introduce regressions and are scope creep beyond the "Pipeline foundation" spec.

## Summary

The pipeline foundation deliverables (schema, db, config, BaseFetcher) are well-implemented and match the spec exactly. All 20 pipeline-specific tests pass. However, the PR includes out-of-scope changes to `sitca_scraper.py` and `app.py` that break 4 previously-passing tests. Verdict is FAIL due to regressions — the pipeline code itself is solid.
