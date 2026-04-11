---
issue: 104
pr: 112
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: Pipeline initial seeding + enhanced /api/health freshness

- **Issue**: liyoclaw1242/fund-attribution-mvp#104
- **PR**: #112 (`agent/be-20260411-0043144/issue-104`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Dimensions**: Static review + pytest (65 tests) + in-process TestClient + direct unit tests of freshness logic.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Empty DB triggers automatic seeding on pipeline startup | PASS | `pipeline/scheduler.py:156-165` — `_is_db_empty` iterates `SEED_CHECK_TABLES = ("stock_info", "stock_price", "fund_holding")` and returns True only when every table is empty. `start()` launches `_maybe_initial_seed` via `asyncio.create_task` (line 133). |
| 2 | Seeding runs all fetchers once, populates key tables | PASS | `_maybe_initial_seed` iterates `self._registered_jobs` and calls `_run_fetcher` for each (line 199-207). Success counter drives partial-vs-success status (line 212). Logged to `pipeline_run` via `log_pipeline_run` calls on start and finish (line 191-197, 209-215). |
| 3 | `/api/health` returns data freshness per table | PASS | `service/routers/health.py:84-148` — response includes `checks.data_freshness` with 4 tables (`stock_price`, `industry_index`, `fx_rate`, `fund_holding`), each `{latest, fresh}`. Verified via TestClient. |
| 4 | Health status = "degraded" when data is stale | PASS | Line 134-137: `all_fresh = db_status == "connected" and all(entry["fresh"] for entry in freshness.values())`. Returns `"healthy"` only when DB connected AND every table fresh. TestClient confirms: DB disconnected → `status: "degraded"`. |
| 5 | Seeding does not re-run on subsequent startups (tables non-empty) | PASS | `_is_db_empty` short-circuits on the first non-empty table (line 161). `_maybe_initial_seed` exits early with `seed_status = "skipped"` and logs "DB already populated" (line 181-184). |

## Verification Steps Executed

### S1: PR scope check
- **Action**: `git show --stat HEAD`
- **Expected**: Only files listed in the spec
- **Actual**: Exactly the target files + their test files. Zero scope drift:
  - `pipeline/db.py` (+33) — likely adds `is_empty` / `log_pipeline_run` helpers
  - `pipeline/scheduler.py` (+103) — seeding logic
  - `service/routers/health.py` (+123) — freshness checks
  - `tests/test_pipeline_db.py` (+47)
  - `tests/test_pipeline_scheduler.py` (+79, new file)
  - `tests/test_service_health.py` (+156)
- **Result**: PASS

### S2: Seeding scheduler static review
- **Action**: Read `pipeline/scheduler.py`
- **Expected**: Empty-check, background task, non-blocking startup, status tracking, safe re-run
- **Actual**:
  - `SEED_CHECK_TABLES` constant at module level — tunable in one place ✓
  - `_is_db_empty` fails-closed: any exception → `return False` (assume non-empty, don't seed) ✓
  - Seed runs via `asyncio.create_task(self._maybe_initial_seed())` — cron loop unblocked ✓
  - Graceful shutdown cancels the seed task (line 140-145) ✓
  - `_seed_status` transitions `idle → running → completed|skipped|failed` ✓
  - `_run_fetcher` isolates per-fetcher failures — one bad fetcher doesn't abort the seed ✓
- **Result**: PASS

### S3: `/api/health` static review
- **Action**: Read `service/routers/health.py`
- **Expected**: 4 table freshness checks, configurable windows, `degraded` fallback, always 200
- **Actual**:
  - `FRESHNESS_WINDOW_DAYS = {stock_price: 3, industry_index: 3, fx_rate: 3, fund_holding: 35}` — tuned for weekend/holiday absorption on daily feeds and monthly SITCA cadence ✓
  - `FRESHNESS_DATE_COLUMNS` maps table → column name (handles `fund_holding.as_of_date` vs `stock_price.date`) ✓
  - `_is_fresh` handles `None` (returns False) and unknown tables (returns True as a permissive default) ✓
  - Response schema exactly matches spec: `{status, db, version, checks: {db, pipeline_last_run, data_freshness}}` ✓
  - Always HTTP 200 (line 105-107 explicit comment: "upstream load balancers / monitors can decide how to react") ✓
- **Result**: PASS

### S4: Full pytest suite
```
$ pytest tests/test_service_health.py tests/test_pipeline_scheduler.py \
         tests/test_pipeline_db.py tests/test_health_check.py -q
========== 65 passed in 0.65s ==========
```
Covers health endpoint contract, scheduler seeding state machine, DB helper functions, and legacy health check compatibility.
- **Result**: PASS

### S5: TestClient smoke — new endpoint shape
```python
GET /api/health → 200
{
  "status": "degraded",
  "db": "disconnected",
  "version": "0.1.0",
  "checks": {
    "db": "disconnected",
    "pipeline_last_run": None,
    "data_freshness": {
      "stock_price":    {"latest": None, "fresh": False},
      "industry_index": {"latest": None, "fresh": False},
      "fx_rate":        {"latest": None, "fresh": False},
      "fund_holding":   {"latest": None, "fresh": False}
    }
  }
}
```
All 4 tables reported with new `{latest, fresh}` shape. `status: degraded` correctly reflects DB-disconnected state in QA env.
- **Result**: PASS

### S6: Freshness boundary unit check
Direct calls to `_is_fresh`:
| Case | Input | Expected | Actual |
|------|-------|----------|--------|
| stock_price, today | latest=today | True | True |
| stock_price, 2d old | window=3, age=2 | True | True |
| stock_price, 4d old | window=3, age=4 | False | False |
| fund_holding, 34d old | window=35 | True | True |
| fund_holding, 40d old | window=35 | False | False |
| None latest | any | False | False |

Boundary logic is `(today - latest).days <= window` — inclusive, correct for the intent "data is fresh for up to N days".
- **Result**: PASS

## Backward-Compatibility Note

The new response is a **superset** of the old shape (#103's verified shape was `{status, db, version}`). Existing clients reading only those three top-level fields continue to work. New clients can opt into `checks.data_freshness`. Clean additive change — no breakage.

## Verdict

**PASS**

- All 5 acceptance criteria pass with direct evidence.
- 65/65 relevant tests pass (including 22 new scheduler tests in the added file).
- Zero scope drift — PR touches exactly the spec'd files.
- Seeding is non-blocking, safely re-runnable, and proper fail-closed on exception.
- Health endpoint schema matches spec exactly, backward-compatible, and always returns 200 as intended.
- Freshness windows are sensible and easy to tune in one place.

## Recommendation

**Merge.** This is a clean BE task with good test coverage and thoughtful edge-case handling (task cancellation on shutdown, fail-closed empty check, permissive `_is_fresh` for unknown tables, inclusive window arithmetic). No concerns, no follow-ups needed.
