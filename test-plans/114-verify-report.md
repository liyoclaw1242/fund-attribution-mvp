---
issue: 114
pr: 119
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: Add pandas + numpy + interfaces.py to service container

- **Issue**: liyoclaw1242/fund-attribution-mvp#114
- **PR**: #119 (`agent/be-20260411-0043144/issue-114`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Origin**: Bug #1 from #106 live smoke. Last of three bugs from that FAIL report.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `service/requirements.txt` includes `pandas>=2.1.0` and `numpy>=1.25.0` | PASS | Diff adds both lines, versions match root `requirements.txt`. |
| 2 | `docker compose build service` succeeds | PASS | Image built via `docker compose up -d --build` on both the isolated fix branch and on main+overlay. |
| 3 | `docker compose up -d service` — `Up (healthy)`, no `ModuleNotFoundError` | PASS | Live: `fund-attribution-mvp-service-1 running Up 26 seconds (healthy)`. Logs: `INFO: Application startup complete`, `INFO: Uvicorn running on http://0.0.0.0:8000`. Zero `ModuleNotFoundError` in logs. Container passes its own `/api/health` curl healthcheck within 20s. |
| 4 | `curl http://localhost:8000/api/health` returns 200 | PASS | Live: `http_code=200`. Body: `{"status":"degraded","db":"connected","version":"0.1.0","checks":{"db":"connected","pipeline_last_run":"2026-04-11T04:41:16...","data_freshness":{...}}}`. `db: connected` confirms actual Postgres connectivity. `status: degraded` is correct (empty freshness tables — no seed data yet). |
| 5 | Audit other `service/` imports | PASS + BONUS | Grepped every `^(import|from)` in `service/` on the PR branch. All imports are stdlib, in the updated requirements.txt, or project-internal (`config.*`, `interfaces`, `service.*`). **Bonus finding by BE**: `service/routers/goal.py` does `from interfaces import GoalConfig` but the Dockerfile only copied `service/` and `config/` — the goal router would have crashed as soon as the pandas bug was fixed. BE caught this and added `COPY interfaces.py ./interfaces.py` to the Dockerfile. Two bugs closed with one PR. |

## Verification Steps Executed

### S1: PR scope check
- **Action**: `git show --stat origin/agent/be-20260411-0043144/issue-114`
- **Actual**: `service/Dockerfile | 4 +++-`, `service/requirements.txt | 2 ++`. Two files, 5 insertions / 1 deletion. Zero drift.
- **Result**: PASS

### S2: Independent import audit
Extracted every `^(import|from)` line across all `.py` files in `service/` from the PR branch via `git show ...:service/...py`. Categorized:
- **Stdlib**: `contextlib`, `dataclasses`, `datetime`, `logging`, `os`, `pathlib`, `re`, `sqlite3`, `typing`, `uuid`
- **In updated requirements.txt**: `fastapi`, `pydantic`, `sqlalchemy`, `pandas`
- **Project-internal**: `config.settings`, `interfaces`, `service.*`
- **Transitive / driver**: `asyncpg` (via `sqlalchemy[asyncio]` + `postgresql+asyncpg://` URL), `numpy` (transitive through pandas but belt-and-suspenders in requirements)

Zero missing deps. The `interfaces` import is covered by the Dockerfile's new `COPY interfaces.py` line.
- **Result**: PASS

### S3: Live smoke — PR branch only (isolated)
```bash
git checkout agent/be-20260411-0043144/issue-114
docker compose up -d --build
```
| Container | Status at t+21s |
|-----------|-----------------|
| db | `Up 26 seconds (healthy)` |
| service | **`Up 21 seconds (healthy)`** ✓ |
| app | `Up 21 seconds` |
| pipeline | `Restarting (1)` — expected: this branch predates #115's schema fix |

Service logs showed clean startup:
```
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```
No `ModuleNotFoundError`, no restart loop. The pandas+interfaces fix works.
- **Result**: PASS (for #114's direct ACs)

### S4: Live smoke — main + #114 overlay (full stack)
To prove the fix composes with the #115 (schema) and #116 (start.sh) fixes already on main, overlaid just the #114 file changes onto main without committing:
```bash
git checkout main
git checkout origin/agent/be-20260411-0043144/issue-114 -- service/Dockerfile service/requirements.txt
docker compose up -d --build
```

| Container | Status at t+24s |
|-----------|-----------------|
| db | `Up 32 seconds (healthy)` |
| service | `Up 26 seconds (healthy)` ✓ |
| pipeline | `Up 26 seconds (health: starting)` — **no restart loop** ✓ |
| app | `Up 26 seconds` ✓ |

Pipeline logs: `INFO: Schema migration complete` — schema migration works. Fetchers subsequently fail (see "New Latent Bugs" below).

Service logs: clean startup, no ModuleNotFoundError.

`/api/health` live response:
```json
{
  "status": "degraded",
  "db": "connected",
  "version": "0.1.0",
  "checks": {
    "db": "connected",
    "pipeline_last_run": "2026-04-11T04:41:16.559686+00:00",
    "data_freshness": {
      "stock_price":    {"latest": null, "fresh": false},
      "industry_index": {"latest": null, "fresh": false},
      "fx_rate":        {"latest": null, "fresh": false},
      "fund_holding":   {"latest": null, "fresh": false}
    }
  }
}
```

`db: connected` and `pipeline_last_run` is populated — meaning Postgres is reachable AND the pipeline successfully wrote to the `pipeline_run` table. This is a massive improvement over #106's state where the stack didn't even start.

Streamlit: `http://localhost:8501/` → HTTP 200. UI is reachable.

### S5: Teardown
```bash
docker compose down -v
git checkout HEAD -- service/Dockerfile service/requirements.txt  # revert overlay
rm -f .env
```
Working tree clean, on main, no residual state.

## New Latent Bugs Found During Full-Stack Smoke

With all three #106 blockers fixed, the stack finally starts — which reveals a new set of issues that were hidden behind the container crashes. **NONE of these are regressions from #114, #115, or #116.** They are pre-existing bugs that were masked:

### New Bug A: Pipeline fetchers fail with `_tmp_*` table errors

```
ERROR: Failed: twse_mi_index
asyncpg.exceptions.UndefinedTableError: relation "_tmp_industry_index" does not exist

ERROR: Failed: twse_stock_day_all
asyncpg.exceptions.UndefinedTableError: relation "_tmp_stock_price" does not exist
```

Every TWSE/FinMind/yfinance/FX fetcher crashes because `_tmp_*` tables don't exist. The fetchers presumably expect these to be created elsewhere (transformer step? a migration we're not running?). **Triage → BE (pipeline)**. Severity: blocks all data seeding, so `/api/fund/*` will always be empty.

### New Bug B: Weight calculator `'str' has no attribute 'toordinal'`

```
ERROR: Failed: weight_calculator
AttributeError: 'str' object has no attribute 'toordinal'
asyncpg.exceptions.DataError: invalid input for query argument $2: '2026-04-11' ('str' object has no attribute 'toordinal')
```

Somewhere in the weight_calculator transformer, a date is being passed as a string instead of a `date` object to an asyncpg query. **Triage → BE (pipeline)**. Simple fix.

### New Bug C: `/api/fund/search` returns 500

```
GET /api/fund/search?q=test → 500
sqlite3.OperationalError: no such table: fund_holdings
```

`service/services/fund_service.py` is still coded against the legacy SQLite `cache.db` instead of the Postgres pipeline tables. The service container has no such cache.db file (correctly — it's a Postgres-backed service now), so every fund lookup fails with a SQLite error. **Triage → BE (service)**. This is the same SQLite vs Postgres gap I noted in #103 but is now visible as a live 500.

### New Bug D (minor): yfinance TzCache permission warning

```
yfinance INFO: Failed to create TzCache, reason: [Errno 17] File exists: '/root/.cache/py-yfinance'
```
Non-fatal warning. Triage → BE (pipeline), low priority.

## Verdict

**PASS**

All 5 ACs for #114 pass cleanly, with both isolated and composed full-stack live evidence. The fix closes Bug #1 from #106 AND catches a second latent bug (missing `interfaces.py` COPY) as a bonus. Zero scope drift.

## Recommendation

**Merge immediately.** This closes the last of the three #106 blockers and brings the stack to a startable state.

## Status Update for #106

All three bugs from my #106 FAIL verdict are now fixed:
- ✅ Bug #1 (service pandas) — this PR (#119 / #114)
- ✅ Bug #2 (schema PK/partition) — merged (#118 / #115)
- ✅ Bug #3 (start.sh bash 3.2) — merged (#117 / #116)

**#106 should be re-verified** after #114 merges. The stack now comes up with all 4 containers in running state. However, **#106 will still FAIL on the data seeding / API sections** because of the new bugs A/B/C/D above. My recommendation to ARCH:

1. Merge #114 immediately (closes the container-startup blockers)
2. Open 4 new issues for new bugs A/B/C/D
3. Re-verify #106 after the new bugs ship. Section 1 (startup) will pass cleanly. Section 2 (seeding) needs bugs A/B fixed. Sections 3-4 (API, UI) need bug C fixed.

The #106 → #114/#115/#116 → new-bugs cascade is a classic "fix one layer, reveal the next" situation. Each step is now visible because each prior step unblocks the next live smoke.

## Self-Review: What I Did Right This Time

After the shared-worktree race in #116, I adopted stricter isolation for this verification:
- Used `git show <ref>:<path>` for all file reads before touching the working tree
- Explicit `git checkout <branch> && git reset --hard origin/<branch>` only after confirming working tree was clean
- Used `git checkout <ref> -- <path>` to overlay the fix onto main without a full merge, which let me test the combined fix without polluting any branch
- Cleaned up the overlay with `git checkout HEAD -- <path>` at the end
- No `git add -A`. Every commit used explicit paths.

No WIP destroyed. No branch races. Clean end state.
