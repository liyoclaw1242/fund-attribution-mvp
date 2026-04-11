---
issue: 123
pr: 124
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: service/Dockerfile missing COPY engine/

- **Issue**: liyoclaw1242/fund-attribution-mvp#123
- **PR**: #124 (`agent/be-20260411-0043144/issue-123`)
- **Verifier**: qa-20260410-0954327
- **Origin**: Bug E from #106 round-2 — `POST /api/attribution` returned 500 with `ModuleNotFoundError: No module named 'engine'` because `service/Dockerfile` only copied `service/`, `config/`, and `interfaces.py` but `attribution_service.py` lazy-imports `from engine.brinson import compute_attribution`.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `service/Dockerfile` copies `engine/` | PASS | Diff adds `COPY engine/ ./engine/` (line 18). Comment block updated to document each COPY. |
| 2 | Audit other top-level imports outside copied dirs | PASS | Independent audit (see S2 below): walked every `^(from|import)` in `service/` AND `engine/` on the PR branch. After filtering stdlib + installed packages + project-internal modules (`config/`, `service/`, `engine/`, `interfaces`), zero unaccounted imports remain. `ai/` and `data/` are not imported from service. |
| 3 | `docker compose build service` succeeds | PASS | Built via `docker compose up -d --build`. Image creation completed. |
| 4 | Container `(healthy)`, no `ModuleNotFoundError` | PASS | Live: `fund-attribution-mvp-service-1 running Up 13 seconds (healthy)`. Service logs: `INFO: Application startup complete`, `INFO: Uvicorn running on http://0.0.0.0:8000`. Zero ModuleNotFoundError on startup or first request. |
| 5 | `POST /api/attribution` returns 200 with Brinson result | PASS | After seeding cache.db with minimal `fund_holdings` + `benchmark_index` data inside the container, `POST /api/attribution -d '{"holdings":[{"identifier":"0050","shares":1000}],"mode":"BF2","benchmark":"auto"}'` → **HTTP 200**. Response is a complete Brinson result dict with `fund_return`, `bench_return`, `excess_return`, `allocation_total`, `selection_total`, `interaction_total`, `brinson_mode: "BF2"`, `detail[]` with per-industry `Wp`, `Wb`, `Rp`, `Rb`, `alloc_effect`, `select_effect`, `interaction_effect`, `total_contrib`. |
| 6 | `engine/` deps reconciled with `service/requirements.txt` | PASS | engine/ only pulls pandas, numpy, interfaces, config.settings — all already in `service/requirements.txt` post-#114. No new pip installs needed. |

## Verification Steps Executed

### S1: PR scope check
- **Action**: `git show --stat origin/agent/be-20260411-0043144/issue-123`
- **Actual**: `service/Dockerfile | 8 ++++++--`. Single file, 6 insertions / 2 deletions. The 2 deletions are the prior comment block being replaced with a more detailed one. Zero scope drift.
- **Result**: PASS

### S2: Independent import audit
Listed every Python file in `service/` and `engine/` from the PR branch via `git ls-tree`, then `git show <ref>:<path>` each one and grepped for `^(from|import)`. After filtering stdlib (`os`, `sys`, `re`, `uuid`, `datetime`, `pathlib`, `logging`, `typing`, `contextlib`, `dataclasses`, `sqlite3`, `json`, `io`, `enum`, `collections`, `functools`, `itertools`, `abc`, `asyncio`, `warnings`) + installed packages (`fastapi`, `pydantic`, `sqlalchemy`, `pandas`, `numpy`, `asyncpg`, `matplotlib`) + project-internal modules now COPY'd into the image (`config`, `service`, `engine`, `interfaces`), the result was empty.

This independently confirms BE's audit claim. `ai/` and `data/` are NOT imported from `service/`.
- **Result**: PASS

### S3: Direct engine import inside container
Before doing the API smoke (which would route through `fund_service` first), I verified the engine COPY directly:
```bash
docker compose exec service python -c "
from engine.brinson import compute_attribution
print('engine.brinson imported OK:', compute_attribution.__module__)
from service.services.attribution_service import run_attribution
print('service.services.attribution_service imported OK')
import os
print('engine/ files:', sorted(os.listdir('/app/engine')))
"
```

Output:
```
engine.brinson imported OK: engine.brinson
service.services.attribution_service imported OK
engine/ files: ['__init__.py', '__pycache__', 'anomaly_detector.py', 'brinson.py',
                'crisis_response.py', 'etf_mirror.py', 'fee_calculator.py',
                'fund_comparator.py', 'goal_tracker.py', 'health_check.py',
                'multi_market_brinson.py', 'validator.py']
```

11 engine modules present in `/app/engine/` inside the container. Both `engine.brinson` and the lazy-importing `attribution_service` module load cleanly. **This is the most direct evidence the fix works.**
- **Result**: PASS

### S4: Live POST /api/attribution end-to-end (the BE claim)

#### Initial attempt without seed data
```bash
curl -X POST http://localhost:8000/api/attribution \
  -H "Content-Type: application/json" \
  -d '{"holdings":[{"identifier":"0050","shares":1000}],"mode":"BF2","benchmark":"auto"}'
→ http_code=500
```
Service logs: `sqlite3.OperationalError: no such table: fund_holdings` — that's **Bug C** (the still-unfixed `fund_service.py` SQLite issue), NOT the engine import bug. Bug C blocks the call before it ever reaches `engine.brinson`.

#### Worked around Bug C by seeding cache.db inside the container
```python
docker compose exec service python -c "
import sqlite3
conn = sqlite3.connect('cache.db')
# create fund_holdings + benchmark_index tables
# insert 4 industries each (semiconductor, electronics, financial, other)
"
```

#### Retry after seeding
```bash
curl -X POST http://localhost:8000/api/attribution -d '...' → http_code=200
```

Response (first 600 bytes):
```json
{
  "fund_return": 0.0,
  "bench_return": 0.0,
  "excess_return": 0.0,
  "allocation_total": 0.0,
  "selection_total": 0.0,
  "interaction_total": 0.0,
  "brinson_mode": "BF2",
  "detail": [
    {"industry": "半導體",     "Wp": 0.45, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0,
     "alloc_effect": 0.0, "select_effect": 0.0, "interaction_effect": 0.0, "total_contrib": 0.0},
    {"industry": "其他",       "Wp": 0.20, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0, ...},
    {"industry": "電子零組件", "Wp": 0.20, "Wb": 0.0, "Rp": 0.0, "Rb": 0.0, ...},
    ...
  ]
}
```

The numerical values are all `0.0` because my seed data didn't match the lookup keys `fund_service.get_benchmark_data()` expects (it pulls `benchmark_index` rows by a different period+name pattern). But the response shape proves three things:
1. ✅ `engine.brinson.compute_attribution` actually executed (the Brinson result schema is populated, with 4 industries reflecting the seeded `fund_holdings` rows via `Wp`)
2. ✅ The Pydantic response schema validates (would have 500'd on serialization mismatch otherwise)
3. ✅ HTTP 200 round-trip — the Bug E `ModuleNotFoundError` is gone

The benchmark-side zeros are a test-data issue, not a code bug. This independently corroborates BE's commit-message smoke ("HTTP 200, valid Brinson-Fachler result with per-industry alloc_effect / select_effect / total_contrib").

- **Result**: PASS

### S5: Teardown
```bash
docker compose down -v
rm -f .env
git checkout main
```
Working tree clean on main. No residue. Volumes removed.

## Verdict

**PASS**

All 6 ACs pass with direct evidence. Bug E from #106 round-2 is closed. The fix is minimal (1 file, 6+/2-), well-documented (commit message + inline comment block explains why each COPY is there), and live-tested both via direct module import AND end-to-end through the FastAPI request → uvicorn → router → service → engine.brinson path.

## Recommendation

**Merge.** Closes Bug E from #106. After this lands:
- `/api/attribution` will work end-to-end *as soon as Bug C (fund_service SQLite) is also fixed*
- `#106` round-3 §3 will move from PARTIAL toward green (still needs Bugs A + C resolved for full data flow)

## Status of #106 Bug Cascade

| Bug | Component | Status |
|-----|-----------|--------|
| A | pipeline `_tmp_*` tables | ❌ open |
| B | weight_calculator str→date | ❌ open |
| C | fund_service SQLite→Postgres | ❌ open (blocks `/api/fund/*` and `/api/attribution`) |
| D | yfinance TzCache warning | ❌ open (cosmetic) |
| **E** | service Dockerfile missing engine/ | ✅ **this PR** |
| F | docker kill + unless-stopped policy | ❌ open (policy question) |

Bug E was the second-easiest of the 6 (single Dockerfile line). Bug C is the next critical blocker — without it, the attribution endpoint still 500s end-to-end despite Bug E being fixed.

## Self-Review Note

I caught a real subtlety here: my first `POST /api/attribution` returned 500 with `sqlite3.OperationalError: no such table: fund_holdings` — and I almost concluded "the fix didn't work" before realizing Bug C runs *before* the engine import in the call stack. The lesson: when re-verifying a fix in a multi-bug system, always confirm the failure mode you're seeing is YOUR bug and not a sibling. The direct `docker exec ... python -c "from engine.brinson import ..."` test was the right move because it isolated Bug E from Bug C entirely.
