---
issue: 106
verifier: qa-20260410-0954327
date: 2026-04-11
target: main @ 66d5b1a (post #114 + #115 + #116 merged)
verdict: PASS_WITH_NEW_FINDINGS
supersedes: test-plans/106-verify-report.md
---

# Re-verify Report: Full Stack Smoke Test — 4-container Deployment (Round 2)

- **Issue**: liyoclaw1242/fund-attribution-mvp#106
- **Target**: `main` @ `66d5b1a` (post-merge of #114 pandas, #115 schema, #116 start.sh)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Supersedes**: `test-plans/106-verify-report.md` (original FAIL verdict from earlier today)

## Verdict Summary

**PASS_WITH_NEW_FINDINGS** — original three blockers closed. Stack starts, persists, and has good fault isolation. Three new latent bugs (fund_service SQLite / missing `engine/` COPY / killed containers not auto-restarting) found during full-stack exercise. Sections 1, 5 fully pass. Sections 2, 3, 4, 6 partial.

## Section-by-Section Results

### §1: One-Click Startup — **PASS**

| Check | Result |
|-------|--------|
| `docker compose up -d` starts all 4 containers | ✅ |
| All containers reach healthy within 5 minutes | ✅ (actual: all up within 23 seconds) |
| `docker compose ps` shows all running | ✅ |

Final state observed at t+23s:
```
NAME                              STATE     STATUS
fund-attribution-mvp-app-1        running   Up 23 seconds
fund-attribution-mvp-db-1         running   Up 28 seconds (healthy)
fund-attribution-mvp-pipeline-1   running   Up 23 seconds (health: starting)
fund-attribution-mvp-service-1    running   Up 23 seconds (healthy)
```

No restart loops. Pipeline stabilizes to `healthy` by §6.

### §2: Data Seeding — **PARTIAL PASS**

| Check | Result |
|-------|--------|
| Empty-DB detection triggers initial seed | ✅ (`Empty DB detected — running initial seed (9 fetchers)`) |
| `pipeline_run` table shows seed execution records | ✅ (11 rows after seed pass) |
| `stock_info`, `stock_price`, `fund_holding` populated | ❌ (all 0 rows) |

Pipeline log: `Initial seed complete — 2/9 fetchers ran`. The 2 "completed" fetchers (`sitca_holdings`, `finnhub_fund_holdings`) returned 0 rows because they need API credentials not available in QA env. The remaining 7 fail with **New Bug A** (missing `_tmp_*` staging tables) and **New Bug B** (`weight_calculator` str→date bug). These are pre-existing bugs hidden behind the container crashes in round 1.

**Seed orchestration logic works correctly.** Data acquisition is blocked by individual fetcher bugs.

### §3: API Verification — **PARTIAL PASS**

| Endpoint | Expected | Actual |
|----------|----------|--------|
| `GET /api/health` | 200 | ✅ 200, body shape complete, `db: connected`, `pipeline_last_run` populated |
| `GET /api/fund/0050` | 200 | ❌ 500 `sqlite3.OperationalError: no such table: fund_holdings` (Bug C) |
| `GET /api/fund/search?q=test` | 200 | ❌ 500 `sqlite3.OperationalError: no such table: fund_holdings` (Bug C) |
| `POST /api/attribution` | 200 | ❌ 500 `ModuleNotFoundError: No module named 'engine'` (**New Bug E**) |
| `POST /api/attribution {mode:BAD}` | 422 | ✅ 422 (Pydantic validation works) |

`/api/health` live response:
```json
{
  "status": "degraded",
  "db": "connected",
  "version": "0.1.0",
  "checks": {
    "db": "connected",
    "pipeline_last_run": "2026-04-11T05:17:28.224369+00:00",
    "data_freshness": {
      "stock_price":    {"latest": null, "fresh": false},
      "industry_index": {"latest": null, "fresh": false},
      "fx_rate":        {"latest": null, "fresh": false},
      "fund_holding":   {"latest": null, "fresh": false}
    }
  }
}
```

`db: connected` is a major improvement over round 1 (which had `db: disconnected`). The pipeline successfully writes to `pipeline_run` and the service reads it.

**The health endpoint works. Business endpoints are blocked by two BE bugs.**

### §4: Streamlit UI — **PASS (reachable)**

| Check | Result |
|-------|--------|
| `http://localhost:8501/` loads | ✅ HTTP 200, time_total ~6ms |
| `http://localhost:8501/_stcore/health` | ✅ HTTP 200, body `ok` |
| Fund lookup works end-to-end | NOT_RUN (would hit Bug C/E) |
| Attribution analysis produces results | NOT_RUN (would hit Bug C/E) |
| Charts render correctly | NOT_RUN |

UI is reachable. Exercising business flows would hit the §3 bugs.

### §5: Persistence — **PASS**

| Check | Result |
|-------|--------|
| `docker compose down && up -d` | ✅ (no `-v` — volume preserved) |
| Data still present in PostgreSQL | ✅ (`TEST_MARKER` row survived: `TEST_MARKER | 2026-04-11 | 999.9900`) |
| No re-seeding triggered | ✅ (`INFO: DB already populated — skipping initial seed`) |

Confirms #104's empty-DB detection logic works symmetrically: seeds when empty, skips when populated. `pgdata` named volume survives container removal as designed.

### §6: Failure Recovery — **PARTIAL PASS**

| Check | Result |
|-------|--------|
| Kill pipeline → auto-restart | ❌ (exits 137, stays dead — **New Bug F**) |
| Kill service → auto-restart, Streamlit handles briefly | ❌ (same Bug F) |
| Kill db → pipeline + service fail gracefully | ✅ (neither crashed; service logs `Health check connection failed` cleanly) |
| Kill db → recover on DB restart | ✅ (after `docker compose up -d db`, both service and pipeline reconnect without restart) |

Observed sequence for db kill:
1. `docker kill fund-attribution-mvp-db-1` → `Exited (137) 5 seconds ago`
2. Service + pipeline **remained running** — no crash, no restart loop
3. Service logs reported `Health check connection failed` (expected, logged cleanly)
4. `docker compose up -d db` → db back up within 10 seconds
5. Service + pipeline picked up the connection without manual intervention

**Good news**: connection-pool resilience is solid. Service and pipeline survive DB disconnect/reconnect.

**Bug news**: `restart: unless-stopped` in compose doesn't cover `docker kill`. All three killed containers (`service`, `db`, `pipeline`) exited 137 and stayed in `exited` state. Docker's `unless-stopped` treats `docker kill` as a user-initiated stop and refuses to restart.

## New Bugs Found (not regressions — pre-existing)

### Bug A (Blocker for seeding): Pipeline fetchers missing `_tmp_*` staging tables

```
asyncpg.exceptions.UndefinedTableError: relation "_tmp_industry_index" does not exist
asyncpg.exceptions.UndefinedTableError: relation "_tmp_stock_price" does not exist
asyncpg.exceptions.UndefinedTableError: relation "_tmp_stock_info" does not exist
asyncpg.exceptions.UndefinedTableError: relation "_tmp_fx_rate" does not exist
```

Affects: `twse_mi_index`, `twse_stock_day_all`, `twse_t187ap03`, `finmind_stock_info`, `yfinance_us_stocks`, `fx_rates` (6 of 9 fetchers). The fetchers use a stage-and-swap pattern (write to `_tmp_*`, then `ALTER TABLE ... RENAME` or similar), but the staging tables are never created. Missing from `pipeline/schema.sql` or from a pre-fetch migration step.

**Triage → BE (pipeline)**. **Severity: blocker for data seeding.**

### Bug B: `weight_calculator` passes str instead of `date`

```
ERROR: Failed: weight_calculator
AttributeError: 'str' object has no attribute 'toordinal'
asyncpg.exceptions.DataError: invalid input for query argument $2: '2026-04-11'
    rows = await self._compute_weights(pool, market, target_date)
    rows = await conn.fetch(...)
```

Somewhere in `pipeline/transformers/weight_calculator.py`, `target_date` is being passed as a string (`'2026-04-11'`) instead of a `datetime.date` object. asyncpg requires `date` for `DATE` columns. One-line fix: `target_date = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date`.

**Triage → BE (pipeline)**. **Severity: minor, self-contained.**

### Bug C (Blocker for API): `fund_service` uses SQLite, not Postgres

```
GET /api/fund/0050 → 500
GET /api/fund/search → 500
sqlite3.OperationalError: no such table: fund_holdings
```

`service/services/fund_service.py` imports `DB_PATH` from `config.settings` (which points to the legacy `cache.db` SQLite file) instead of using the async SQLAlchemy engine at `service/db.py` (which points at Postgres via `POSTGRES_URL`). The service container has no `cache.db` — this is a Postgres-backed service now. All fund lookups fail.

Same symptom I noted in #103 but as a hidden venv-masked issue; now it's a live 500 because the service actually runs end-to-end.

**Triage → BE (service)**. **Severity: blocker for all fund/attribution API routes.** Fix: rewrite `fund_service.py` to use the async engine, mirroring `service/routers/health.py` pattern.

### Bug D (Minor): yfinance TzCache permission warning

```
yfinance INFO: Failed to create TzCache, reason: [Errno 17] File exists: '/root/.cache/py-yfinance'
```

Non-fatal, only logged at INFO level. Low priority.

**Triage → BE (pipeline)**. **Severity: cosmetic.**

### Bug E (Blocker for attribution): `service/Dockerfile` doesn't COPY `engine/`

```
POST /api/attribution → 500
ModuleNotFoundError: No module named 'engine'
```

`service/services/attribution_service.py` imports from `engine.*` (the Brinson engine modules) but `service/Dockerfile` only copies `service/`, `config/`, and `interfaces.py`. Same class of bug as the `interfaces.py` miss in #114 — exposed now that pandas is fixed and the service gets far enough to load the attribution router.

**Triage → BE/OPS (service Dockerfile)**. **Severity: blocker for attribution API.** Fix: add `COPY engine/ ./engine/` to `service/Dockerfile` (~1 line).

### Bug F: `docker kill` doesn't trigger auto-restart under `unless-stopped`

```
docker kill fund-attribution-mvp-service-1
→ Exited (137) N seconds ago  (stays dead)
```

Compose file uses `restart: unless-stopped` on all services. In this Docker version (28.5.2, OrbStack), `docker kill` (SIGKILL from the Docker CLI) is treated as a user-initiated stop, so `unless-stopped` doesn't restart. Same result for `service`, `db`, `pipeline` — all tested, all stayed dead.

Fix options:
1. Change to `restart: always` (restarts even after manual stop)
2. Accept the current behavior and update #106's AC to test internal crashes (e.g. `docker exec ... kill -9 <pid>`) instead of `docker kill`
3. Document the distinction: "killed by operator stays dead; crashed-internally restarts"

**Triage → OPS (compose policy) or ARCH (spec clarification)**. **Severity: depends on interpretation.** The spec says "Kill pipeline container → restarts automatically" — if "kill" means operator kill, this fails; if it means "pipeline process crashes internally", `unless-stopped` is correct for healthy production (you don't want a runaway restart loop on bad deploys).

## Comparison to Round 1 FAIL

| Dimension | Round 1 (2026-04-11 earlier) | Round 2 (now) | Delta |
|-----------|------------------------------|---------------|-------|
| §1 Startup | FAIL (2 containers crash loop) | **PASS** | ✅ fixed by #114 + #115 |
| §2 Seeding | FAIL (cascaded) | PARTIAL (logic works, fetchers bugged) | ✅ infra fixed, new bugs exposed |
| §3 API | NOT_RUN (cascaded) | PARTIAL (health 200, business 500) | ✅ service boots, two routing bugs remain |
| §4 UI | NOT_RUN (cascaded) | PASS (reachable) | ✅ |
| §5 Persistence | NOT_RUN (cascaded) | **PASS** | ✅ |
| §6 Recovery | NOT_RUN (cascaded) | PARTIAL (fault isolation OK, restart policy not) | ✅ isolation verified; Bug F found |

**Net progress**: 3 blockers closed, 3 new blockers found + 1 policy question. The net direction is strongly positive — the cascade unmasking pattern is working as intended.

## Recommendation for ARCH

1. **Close §1 and §5 as DONE** on this issue — container startup and persistence AC definitively pass.
2. **Keep #106 open or create "#106 Round 3"** to track §2, §3, §4, §6 completion.
3. **Open 5 new issues**:
   - Bug A (pipeline `_tmp_*` tables) — BE, blocker
   - Bug B (weight_calculator str→date) — BE, minor
   - Bug C (fund_service SQLite→Postgres) — BE, blocker
   - Bug D (yfinance TzCache warning) — BE, cosmetic
   - Bug E (service Dockerfile missing `engine/` COPY) — BE/OPS, blocker
4. **Decide policy on Bug F**: either change to `restart: always` or clarify the #106 spec to test internal crashes vs operator kill.
5. After bugs A/C/E (blockers) ship, re-run the remaining sections. §2, §3, §4 will then turn green.

## Teardown

```bash
docker compose down -v
→ Container ... Removed, Volume pgdata Removed, Network Removed
rm -f .env
```

Clean state. Working tree on `main`, no residue.
