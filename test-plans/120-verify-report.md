---
issue: 120
pr: 127
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS_WITH_NEW_FINDINGS
---

# Verify Report: BaseFetcher `_tmp_*` staging table bug

- **Issue**: liyoclaw1242/fund-attribution-mvp#120
- **PR**: #127 (`agent/be-20260411-0043144/issue-120`)
- **Verifier**: qa-20260410-0954327
- **Origin**: Bug A from #106 round-2. Biggest remaining data-flow blocker.

## Root Cause Diagnosis (from BE, verified)

The previous `BaseFetcher._load()` ran three statements in asyncpg's autocommit mode:
1. `CREATE TEMP TABLE _tmp_X ... ON COMMIT DROP`
2. `copy_records_to_table(tmp, ...)`
3. `INSERT INTO X SELECT * FROM _tmp_X ON CONFLICT DO NOTHING`

In autocommit mode, each statement is its own implicit transaction. So `CREATE TEMP TABLE ... ON COMMIT DROP` commits and immediately drops the temp table. The next `copy_records_to_table` call then tries to introspect `_tmp_X` and crashes with `UndefinedTableError`.

**Fix**: Wrap the three statements in an explicit `async with conn.transaction():` block so the temp table lives for the duration of the transaction and is dropped only after the INSERT has already copied rows into the target.

Elegant diagnosis, minimal fix. I verified the autocommit/ON COMMIT DROP race by reading `pipeline/fetchers/base.py` before and after — BE's analysis is exactly right.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | All affected fetchers run to completion | PARTIAL (see caveat) | 5 of 9 fetchers now succeed end-to-end (`twse_company_info`: **1,081 rows**, `finmind_stock_info`: **1,992 rows**, `yfinance`: **180 rows**, `sitca`: 0 rows success, `finnhub`: 0 rows success). The 4 remaining failures are a **new bug class** (see New Findings below), NOT caused by #120. |
| 2 | No `UndefinedTableError` in logs | PASS | `docker compose logs pipeline | grep -c "UndefinedTableError\|_tmp_"` → **0**. |
| 3 | `pipeline_run` shows successful fetch records | PASS | 5 rows with `status='success'` (including two with non-zero `rows_count` proving `_load` staging → INSERT actually copies data). |
| 4 | Approach documented | PASS | Commit message names Option 1 from the issue and explains the autocommit race in precise detail. |
| 5 | Smoke insert + select for at least one affected fetcher | PASS | `twse_company_info` wrote 1,081 rows, `finmind_stock_info` wrote 1,992 rows, `yfinance` wrote 180 rows. All went through the fixed `_load` path (CREATE TEMP TABLE → COPY → INSERT ... ON CONFLICT) inside the new transaction wrapper. End-to-end proof. |

## Verification Steps Executed

### S0: Pre-flight sanity
- **Action**: Check branch base + stat + conflicts with recent main commits
- **Actual**: Branch base is `d722c45`. Touches only `pipeline/fetchers/base.py` and its test file. Only commit on main since branch base is `e4b6e11` (#121 weight_calculator fix, touches different files). **No conflict risk.** Will note that weight_calculator failures in the live smoke will be a pseudo-issue because this branch predates #121.
- **Result**: PASS

### S1: PR scope
- `pipeline/fetchers/base.py`: +25 / -15 (transaction wrapper + docstring explaining why)
- `tests/test_pipeline_fetcher_base.py`: +51 / -1 (one new regression test that records the execution order)
- **Result**: PASS — clean scope

### S2: Diff review
The fix:
```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(f"CREATE TEMP TABLE {tmp} ... ON COMMIT DROP")
        await conn.copy_records_to_table(tmp, ...)
        result = await conn.execute(f"INSERT INTO ... ON CONFLICT DO NOTHING")
```

Docstring additions call out WHY the transaction is required (asyncpg autocommit + `ON COMMIT DROP` timing). Excellent comment that will save the next reader 30 minutes of head-scratching.
- **Result**: PASS

### S3: Pipeline test suite
```
pytest tests/test_pipeline_fetcher_base.py tests/test_pipeline_transformers.py \
       tests/test_pipeline_db.py tests/test_pipeline_scheduler.py
========== 53 passed in 0.46s ==========
```
Includes BE's new regression test `test_load_wraps_staging_in_transaction` which records conn.execute/copy/transaction enter-exit and asserts the order `tx:enter, exec:CREATE, copy, exec:INSERT, tx:exit`. All 53 pass.
- **Result**: PASS

### S4: Live docker smoke
```
docker compose up -d --build db pipeline
```
After ~20s the initial seed has run and the pipeline_run table shows:

| fetcher | status | rows_count | error |
|---------|--------|------------|-------|
| `_initial_seed` | running/partial | — | — |
| `twse_mi_index` | **failed** | 0 | `'str' object has no attribute 'toordinal'` |
| `twse_stock_day_all` | **failed** | 0 | `'str' object has no attribute 'toordinal'` |
| `twse_company_info` | ✅ success | **1081** | — |
| `finmind_stock_info` | ✅ success | **1992** | — |
| `sitca` | ✅ success | 0 | — |
| `finnhub` | ✅ success | 0 | — |
| `yfinance` | ✅ success | **180** | — |
| `fx_rate` | **failed** | 0 | `'str' object has no attribute 'toordinal'` |
| `weight_calculator` | **failed** | 0 | same toordinal error — **but this branch predates #121 fix, will resolve after rebase onto main** |

Log grep:
```
grep -c "UndefinedTableError|_tmp_" → 0
```

**The Bug A fix is definitively working.** `twse_company_info`, `finmind_stock_info`, and `yfinance` all flow through `_load`'s new transaction-scoped staging path and successfully bulk-insert real row counts into their target tables.

- **Result**: PASS

## New Findings (surfaced by fixing Bug A)

Four additional fetchers fail with `'str' object has no attribute 'toordinal'` — the exact same bug class as #121 Bug B. Three of them are **pre-existing** and were hidden behind Bug A:

### New Bug H (was H-1 through H-3): pipeline/fetchers/fx.py + twse.py pass str dates to asyncpg

**`pipeline/fetchers/fx.py:46`**:
```python
target_date = params.get("date", date.today().isoformat())
```
Same pattern as weight_calculator's original bug. `target_date` flows into the emitted row dict's `"date"` field and eventually reaches asyncpg via `_load`'s `copy_records_to_table`. Crashes at type coercion.

**`pipeline/fetchers/twse.py:69` and `twse.py:118`**:
```python
today = date.today().isoformat()
...
"date": today,
```
Two separate fetchers (`TwseMiIndexFetcher` and `TwseStockDayAllFetcher`) both build an ISO-string date and put it in their emitted row dicts. Same asyncpg type error.

**Triage → BE**. **Severity**: blockers for daily price / industry / FX data ingestion. **Fix**: replace `.isoformat()` defaults with `date.today()`, OR apply the `_coerce_date` helper from #121 at the emit-row step.

**Recommendation for ARCH**: open one or two follow-up issues for these. They're the same class as #121 Bug B and should be quick fixes (mechanical, ~3 lines each, following the proven pattern from #121).

### weight_calculator also failing — BUT this is a rebase artifact, not a regression

This branch was created from `d722c45` which is BEFORE #121 merged. So it's still running the pre-fix `weight_calculator.py`. After rebase onto current main, this failure will disappear.

Noting it explicitly so ARCH doesn't count it as a new bug.

## Teardown

```bash
docker compose down -v
rm -f .env
git checkout main
```
Clean. No residue.

## Verdict

**PASS_WITH_NEW_FINDINGS**

- Bug A fix is correct, complete, well-tested, and proven live (1,081 + 1,992 + 180 = **3,253 rows** successfully bulk-inserted via the fixed `_load` path).
- 5 fetchers now report `success` in `pipeline_run`. Previously zero could get past `_load`.
- The fix unmasks 3 new pre-existing bugs in `fx.py` + `twse.py` (same class as #121's already-fixed Bug B).

## Recommendation

**Merge.** Closes Bug A. The 3 new findings are pre-existing bugs that Bug A was hiding — they are not the responsibility of this PR.

After merge, the cascade will be:
- Bug A ✅ (this PR)
- Bug B ✅ (#121 merged)
- Bug H-new (fx.py + twse.py × 2) → open as follow-up issue(s), fix with `_coerce_date` pattern

Once Bug H lands, the pipeline should ingest daily data end-to-end and `/api/health` freshness should finally show non-null `latest` values.

## #106 Bug Cascade Status (updated)

| Bug | Status |
|-----|--------|
| **A** pipeline `_tmp_*` tables | ✅ **this PR** |
| B weight_calculator | ✅ merged (#121) |
| C fund_service SQLite | ✅ merged with fixup (#122/125) |
| D yfinance TzCache | ❌ open (cosmetic) |
| E engine COPY | ✅ merged (#123/124) |
| F restart policy | ❌ open (policy question) |
| G portfolio_service SQLite | ❌ open (hidden) |
| **H-new** fx.py + twse.py str dates | ❌ **new** — surfaced by fixing A |

**5 remaining**: A-free now, so remaining visible blockers are H (3 fetchers) + G (portfolio). D and F are non-blocker / policy.
