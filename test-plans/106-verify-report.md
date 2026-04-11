---
issue: 106
verifier: qa-20260410-0954327
date: 2026-04-11
target: main @ 25b5d54 (post #102, #104, #105)
verdict: FAIL
---

# Verify Report: Full Stack Smoke Test — 4-container Deployment

- **Issue**: liyoclaw1242/fund-attribution-mvp#106
- **Target**: `main` @ `25b5d54` (post-merge of #102 OPS compose, #104 BE seeding+health, #105 OPS consolidation)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Docker**: Daemon available (OrbStack, started mid-session). **First live smoke test on this repo.**

## Verdict: FAIL — 2 Independent Blocker Bugs

Two real container crash bugs prevent the stack from reaching a working state. Both are regressions that slipped through all prior static / in-venv verifications (#102, #103, #105) because nothing had ever actually brought the containers up.

## Bug #1 (BLOCKER): `service` container — `ModuleNotFoundError: No module named 'pandas'`

### Root Cause
- `service/services/attribution_service.py:8` imports `pandas as pd`.
- `service/requirements.txt` contains only: `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `pydantic>=2.0`. **Pandas is missing.**
- The root `requirements.txt` (used by `app` container + local `.venv`) has `pandas>=2.1.0` and `numpy>=1.25.0`.
- All previous QA cycles ran service code from the project venv, which has pandas — so the missing dep in `service/requirements.txt` was invisible.

### Evidence
```
service-1  |   File "/app/service/routers/attribution.py", line 6, in <module>
service-1  |     from service.services.attribution_service import run_attribution
service-1  |   File "/app/service/services/attribution_service.py", line 8, in <module>
service-1  |     import pandas as pd
service-1  | ModuleNotFoundError: No module named 'pandas'
```

Container exit code: 1. Restart loop.

### Fix
Add to `service/requirements.txt`:
```
pandas>=2.1.0
numpy>=1.25.0
```

### Triage
→ **BE** (the attribution service is BE territory) or **OPS** (the containerization is OPS territory). Probably whoever owns `service/requirements.txt`. I'd go BE since they wrote the code that pulls pandas.

---

## Bug #2 (BLOCKER): `pipeline` container — Schema migration fails

### Root Cause
`pipeline/schema.sql` line 20-25 defines `stock_price` as a LIST-partitioned table:

```sql
CREATE TABLE IF NOT EXISTS stock_price (
    stock_id    TEXT NOT NULL,
    date        DATE NOT NULL,
    ...
    PRIMARY KEY (stock_id, date)
) PARTITION BY LIST (substring(stock_id, 1, 1));
```

Postgres rejects this because **the partition key is an expression** (`substring(stock_id, 1, 1)`), and Postgres rule is:
> PRIMARY KEY constraints cannot be used when partition keys include expressions.

The PK would need to *include* all partition-key columns/expressions, but expressions aren't valid in PK definitions. It's an inherently incompatible combination.

### Evidence
```
pipeline-1  |   File "/app/pipeline/db.py", line 34, in execute_schema
pipeline-1  |     await conn.execute(sql)
pipeline-1  | asyncpg.exceptions.FeatureNotSupportedError: unsupported PRIMARY KEY constraint with partition key definition
pipeline-1  | DETAIL:  PRIMARY KEY constraints cannot be used when partition keys include expressions.
```

Container exit code: 1. Restart loop.

### Fix Options
Pick one:
1. **Drop the partitioning** — use a plain `stock_price` table with `PRIMARY KEY (stock_id, date)` and a regular B-tree index on `substring(stock_id, 1, 1)` if prefix filtering matters.
2. **Change partition key to a non-expression column** — e.g. add a `market` column and `PARTITION BY LIST (market)`, adjusting writers.
3. **Drop the PRIMARY KEY, use a UNIQUE index instead** — UNIQUE indexes on partitioned tables have different rules than PKs. (This is the closest to the original intent.)

### Triage
→ **BE** (schema definition + ingestion writers). May need a follow-up `debug` agent if the fix has ripple effects on fetcher code that relies on PK for `ON CONFLICT` upserts.

---

## Test Plan Results (complete)

| § | Section | Result | Notes |
|---|---------|--------|-------|
| 1 | One-Click Startup | **FAIL** | `docker compose up -d` ran, but `service` and `pipeline` are in restart loop. Only `db` and `app` are healthy/running. `scripts/start.sh` has a bash bug (see Bug #3 below). |
| 2 | Data Seeding | **FAIL (cascaded)** | Pipeline container crashes before seeding runs because schema migration fails at startup. Zero rows in any table. |
| 3 | API Verification | **NOT_RUN (cascaded)** | `service` container crashes before uvicorn binds, so `curl http://localhost:8000/api/*` times out. |
| 4 | Streamlit UI | **NOT_RUN (cascaded)** | `app` container is running but useless without service (API unreachable) and without DB data. Did not exercise. |
| 5 | Persistence | **NOT_RUN (cascaded)** | Can't test persistence when the initial fill didn't happen. |
| 6 | Failure Recovery | **NOT_RUN (cascaded)** | Can't test recovery when the baseline doesn't come up. |

## Bug #3 (MINOR): `scripts/start.sh` crashes on dev mode

### Root Cause
`scripts/start.sh:31` under `set -euo pipefail` references `${PROFILE_ARGS[@]}`:

```bash
PROFILE_ARGS=()
...
docker compose "${PROFILE_ARGS[@]}" up -d
```

Under `set -u` (nounset), bash treats `${empty_array[@]}` as an undefined variable reference in some bash versions (notably bash < 4.4, and macOS's system bash is 3.2). Error:
```
scripts/start.sh: line 31: PROFILE_ARGS[@]: unbound variable
```

### Fix
Use the safe array expansion:
```bash
docker compose ${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"} up -d
```

Or drop `set -u` / use a conditional. This only manifests on older bash, which macOS ships as `/bin/bash`.

### Triage
→ **OPS**. Small, mechanical fix. I worked around it in this session by running `docker compose up -d` directly.

### My Earlier Miss
I statically reviewed `scripts/start.sh` in #105 and gave it a PASS. I noted the strict mode (`set -euo pipefail`) as a quality point but did not think through the `[@]` / unbound interaction. **This is a gap in my own verification — a bash-syntax smoke test of the script would have caught it.** Noting for my own journal.

---

## What This FAIL Tells Us About Prior Verdicts

- **#102 (OPS service Dockerfile)**: I marked "docker-compose build service succeeds" as NOT_RUN (no daemon). The build technically would have succeeded — but the *runtime* failure (missing pandas) was hiding behind that NOT_RUN. Lesson: a successful build ≠ a working container.
- **#103 (QA integration)**: I marked "live `/api/health` db: connected" as NOT_RUN. If I had stood up the stack, I would have caught Bug #2 (pipeline schema) immediately.
- **#105 (OPS consolidation)**: I statically reviewed `scripts/start.sh` and missed the `set -u` + empty-array bug. Container-level bugs (#1, #2) were not #105's fault — they're pre-existing regressions that #105 simply didn't touch.

**The single-missing-ingredient was always Docker daemon access.** Now that it's available, the whole class of "does it actually run?" bugs surfaces. Suggest ARCH formalize: **any PR that adds/modifies Dockerfile, docker-compose.yml, schema.sql, or container requirements.txt files must be followed by a live smoke test issue.**

## Recommendation

1. **Do NOT merge anything OPS-adjacent until Bug #1 and Bug #2 are fixed.** The stack literally does not function end-to-end on main.
2. **Open 3 new issues**:
   - `BE: Add pandas+numpy to service/requirements.txt (fixes container crash)` — 1-line fix
   - `BE: Fix stock_price partitioned table PK definition` — 2-8 lines, needs design decision
   - `OPS: Fix scripts/start.sh empty-array expansion under set -u` — 1-line fix
3. **Re-run #106** (or a follow-up smoke test issue) after the three fixes land.
4. **Retroactively flag prior "PASS_WITH_BLOCKED_AC" verdicts** (#102, #105) as "requiring live re-verify" now that Docker is available in the QA env.

## Verdict

**FAIL → BE (primary) + OPS (secondary)**

Three bugs identified, two are hard blockers for any deployment of main. Caught on first live smoke test. Stack torn down cleanly at end of session (`docker compose down -v`, volumes removed).
