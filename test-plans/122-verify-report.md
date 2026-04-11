---
issue: 122
pr: 125
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: FAIL_REGRESSION
---

# Verify Report: Migrate fund_service.py from SQLite to Postgres

- **Issue**: liyoclaw1242/fund-attribution-mvp#122
- **PR**: #125 (`agent/be-20260411-0043144/issue-122`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Origin**: Bug C from #106 round-2. The critical path blocker — until this lands, all `/api/fund/*` endpoints return 500.

## Verdict: **FAIL — Regression**

The core fund_service migration is correct and all 6 direct ACs for #122 pass cleanly. **However, the PR's `service/Dockerfile` changes drop `COPY engine/ ./engine/`**, which was added by PR #124 (closes #123) and merged to main just before this PR. The result: `POST /api/attribution` regresses to `ModuleNotFoundError: No module named 'engine'` — the exact Bug E I verified as fixed earlier today.

This looks like a rebase/merge-conflict resolution that dropped a sibling fix. Easy to fix (one line added back), but I can't PASS this PR as-is because it would undo a previously-merged fix.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `fund_service.py` uses async SQLAlchemy engine / asyncpg pool | PASS | New module imports `from service.db import get_engine`, `from sqlalchemy import text`. All three public functions (`get_fund_by_identifier`, `search_funds`, `get_benchmark_data`) are `async def`. `sqlite3` import removed entirely. |
| 2 | `sqlite3` / `cache.db` references removed from service layer | PARTIAL | Removed from `fund_service.py` ✓. **`portfolio_service.py` still imports sqlite3 and uses `DB_PATH`**. BE disclosed this in the commit message: client/goal tables (`clients`, `client_portfolios`, `client_goals`) don't exist in `pipeline/schema.sql`, so migration requires adding new Postgres schema — separate scope. Defensible but technically a gap vs. the AC. |
| 3 | `curl /api/fund/0050` returns 200 with real data | PASS | Seeded Postgres with fund_info + fund_holding (3 rows across 2 sectors). Live: `http_code=200`, body: `{"fund_id":"0050","fund_name":"元大台灣50","fund_type":"equity","market":"tw","source":"qa","holdings":[{"stock_name":"半導體","weight":0.65},{"stock_name":"金融","weight":0.1}],"as_of_date":"2026-04-01"}`. Aggregation by sector works correctly (2330+2454 rolled into `半導體 0.65`). |
| 4 | `curl /api/fund/search?q=<query>` returns 200 | PASS | `q=台灣` (URL-encoded `%E5%8F%B0%E7%81%A3`) → 200 with `{"query":"台灣","results":[{"fund_id":"0050",...},{"fund_id":"LU0348404012","fund_name":"安聯台灣科技基金",...}],"total":2}`. Postgres ILIKE match + offshore ISIN registry fallback both work. |
| 5 | `curl /api/fund/NOTAFUND` returns 404 (not 500) | PASS | `http_code=404`, body `{"detail":"Fund not found: NOTAFUND"}`. Previously a 500 in #106 round 2. |
| 6 | All existing `service/` tests pass | PASS | 44/44 in `tests/test_service_fund_attribution.py`, `tests/test_service_health.py`, `tests/test_service_portfolio_goal.py`, `tests/test_service_config.py`. Tests rewritten by BE to use a queue-based fake async engine (no real DB required). |

## The Regression

### What Happened

The PR branch's `service/Dockerfile` is missing `COPY engine/ ./engine/` and the associated comment block:

```diff
-# Copy service source and the root-level modules it imports.
-# - config/: settings used by service + engine
-# - interfaces.py: dataclasses used by service/routers/goal.py + engine/
-# - engine/: Brinson attribution lib imported lazily by
-#   service/services/attribution_service.py (from engine.brinson import ...)
+# Copy service source and the root-level modules it imports
+# (config package + interfaces.py used by service/routers/goal.py).
 COPY service/ ./service/
 COPY config/ ./config/
 COPY interfaces.py ./interfaces.py
-COPY engine/ ./engine/
+
+# Only the ISIN registry from pipeline/ is needed at runtime...
+COPY pipeline/fetchers/fund_isin_registry.py ./pipeline/fetchers/fund_isin_registry.py
+RUN : > ./pipeline/__init__.py && : > ./pipeline/fetchers/__init__.py
```

The `COPY engine/` line was added by PR #124 (closes #123) and merged to `main` at commit `39840ac` earlier today. This PR's diff against main deletes that line. This is the signature of a **merge-conflict resolution that dropped a sibling fix** — probably because the BE agent branched off main before #124 merged, then when resolving the Dockerfile conflict they kept their version (with the pipeline stub additions) instead of merging the two.

### Runtime Impact

Direct verification inside the running container:
```bash
$ docker compose exec service ls -la /app/engine
ls: cannot access '/app/engine': No such file or directory

$ docker compose exec service python -c "from engine.brinson import compute_attribution"
Traceback (most recent call last):
  File "<string>", line 1, in <module>
ModuleNotFoundError: No module named 'engine'
```

End-to-end via API:
```bash
$ curl -X POST http://localhost:8000/api/attribution \
    -d '{"holdings":[{"identifier":"0050","shares":1000}],"mode":"BF2","benchmark":"auto"}'
→ http_code=500

service-1  |   File "/app/service/services/attribution_service.py", line 30, in run_attribution
service-1  |     from engine.brinson import compute_attribution
service-1  | ModuleNotFoundError: No module named 'engine'
```

**This is the exact error from Bug E (#106 round-2, PR #124).** Fixing it again is a one-line re-addition of `COPY engine/ ./engine/` to the Dockerfile, keeping the pipeline stub additions this PR adds.

### Why This Wasn't Caught by BE's Smoke

The commit message claims BE ran `POST /api/attribution` and got HTTP 200 with a real Brinson result. Either:
1. BE tested on a branch state that had `COPY engine/` (maybe before a rebase/squash dropped it)
2. BE built once, tested, then amended the Dockerfile and didn't re-smoke
3. Docker's build cache kept an image with the old `engine/` layer around from a sibling build, masking the COPY removal

I can't distinguish which. The **important thing**: the PR as fetched from `origin/agent/be-20260411-0043144/issue-122` (commit `4f1340a`) does not include `COPY engine/` and crashes at the attribution endpoint.

## What the PR Gets Right (and Why It's Worth Saving)

Despite the regression, the core migration is high quality:

- **`fund_service.get_fund_by_identifier`**: reads `fund_info` for metadata + aggregates `fund_holding` by `COALESCE(sector, stock_name)` — clever preservation of the industry-keyed response shape the Brinson engine needs, without assuming every pipeline fetcher normalizes sector
- **`search_funds`**: ILIKE search on Postgres + union with offshore ISIN registry, deduped by `fund_id`. Handles both the mainstream TW ETF case and the offshore fund fallback
- **`get_benchmark_data`**: `DISTINCT ON` join between `industry_weight` and `industry_index.change_pct` — correct way to get the latest snapshot per industry in one query
- **All public functions async**: cascaded the async-ness to routers/fund.py, routers/attribution.py, and attribution_service.py correctly (4 call-sites updated)
- **Tests rewritten with a queue-based fake async engine**: 207 lines of test rewrites in `tests/test_service_fund_attribution.py`. All 44 service tests pass without requiring a real DB
- **Pipeline stub trick for ISIN registry**: `COPY pipeline/fetchers/fund_isin_registry.py` + `RUN : > pipeline/__init__.py && : > pipeline/fetchers/__init__.py` — clean way to pull ONE file from pipeline/ without dragging in apscheduler/fetchers/db.py. Good ops hygiene.
- **Honest audit disclosure**: BE explicitly called out the `portfolio_service.py` gap in the commit message with rationale (new schema needed). Shouldn't be silently hidden.

## Recommendation for ARCH

**Do NOT merge as-is.** But the fix is trivial and the BE work is correct. Suggest:

1. **Reject this PR back to BE** with a clear pointer to the missing `COPY engine/` line. Expected turnaround: 1 line change + new docker build + same smoke.
2. **OR merge on top after a manual fixup commit** adding `COPY engine/ ./engine/` back. The rest of the PR is solid and I don't want to throw away 362 lines of good migration work over a Dockerfile merge conflict.

Either path is fine. My preference: option 1 because it keeps BE in the loop on the regression and reinforces "re-smoke after rebase".

## Tangent: portfolio_service.py gap

BE's audit disclosure says `portfolio_service.py` still uses SQLite because the client/goal tables aren't in `pipeline/schema.sql`. I checked:

```
service/services/portfolio_service.py:6:  import sqlite3
service/services/portfolio_service.py:11: from config.settings import DB_PATH
service/services/portfolio_service.py:13: _DB_PATH = DB_PATH
service/services/portfolio_service.py:16: def _get_conn() -> sqlite3.Connection:
```

This means `/api/portfolio/*` and `/api/goal/*` are ALSO broken in the same way Bug C broke `/api/fund/*`. They'll 500 in the live container because there's no `cache.db`. **This is effectively a hidden Bug G** — pre-existing, surfaces as soon as anyone hits those endpoints.

**Triage → BE (separate issue).** Needs Postgres schema additions for `clients`, `client_portfolios`, `client_goals` (which live in `schema.sql` for SQLite but not `pipeline/schema.sql` for Postgres) PLUS a parallel migration of `portfolio_service.py`. Scope is comparable to this PR.

I'd recommend ARCH open a new issue for this immediately so it doesn't get lost.

## Tests on PR branch

```
$ pytest tests/test_service_fund_attribution.py \
         tests/test_service_health.py \
         tests/test_service_portfolio_goal.py \
         tests/test_service_config.py
========== 44 passed in 0.74s ==========
```

All service tests pass, including the rewritten fund/attribution suite.

## Teardown

```bash
docker compose down -v  # removed volumes, network
rm -f .env
git checkout main
```

Working tree clean on main. No residue.

## Summary Table

| Aspect | Status |
|--------|--------|
| #122 core migration | ✅ correct |
| #122 all 6 direct ACs | ✅ pass |
| 44 pytests | ✅ pass |
| `/api/fund/0050` live | ✅ 200 with real data |
| `/api/fund/search` live | ✅ 200 with results |
| `/api/fund/NOTAFUND` live | ✅ 404 (not 500) |
| #123 (#106 Bug E) | ❌ **REGRESSED** — `COPY engine/` dropped |
| `portfolio_service.py` | ⚠️ still SQLite (acknowledged by BE, needs follow-up issue) |
| portfolio_service gap hidden Bug G | ⚠️ will 500 in container, needs new issue |

**Net Verdict: FAIL — regression must be fixed before merge.**
