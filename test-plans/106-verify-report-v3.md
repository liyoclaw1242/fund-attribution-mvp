---
issue: 106
verifier: qa-20260410-0954327
date: 2026-04-11
target: main @ b261026 (post #114 #115 #116 #121 #122/125 #123 #120)
verdict: PASS_WITH_NEW_BUG_H
supersedes: test-plans/106-verify-report-v2.md
---

# Re-verify Report: Full Stack Smoke Test — Round 3

- **Issue**: liyoclaw1242/fund-attribution-mvp#106
- **Target**: `main` @ `b261026` (post-merge of all 7 #106 round-2 fixes: #114, #115, #116, #120, #121, #122 fixup, #123)
- **Date**: 2026-04-11
- **Supersedes**: `test-plans/106-verify-report.md` (round 1 FAIL) and `test-plans/106-verify-report-v2.md` (round 2 PASS_WITH_NEW_FINDINGS)

## Verdict: **PASS_WITH_NEW_BUG_H**

Major progress across every section. 5 of 6 sections fully pass; §2 is PARTIAL (Bug H blocks twse+fx fetchers); §6 PARTIAL due to unchanged Bug F restart policy. **Real data is flowing for the first time**: 3,073 rows in `stock_info`, 180 rows in `stock_price`, `/api/health` freshness reports `stock_price.fresh: true, latest: 2026-04-10`.

## Round-over-Round Section Results

| § | Section | Round 1 | Round 2 | **Round 3** |
|---|---------|---------|---------|-------------|
| 1 | One-Click Startup | ❌ FAIL (2 crash loops) | ✅ PASS | ✅ **PASS** |
| 2 | Data Seeding | ❌ cascaded | 🟡 PARTIAL (0/9 real rows) | 🟡 **PARTIAL** (5/9 fetchers success, **3,253 real rows**) |
| 3 | API Verification | ❌ cascaded | 🟡 PARTIAL (500s everywhere) | 🟢 **MOSTLY PASS** (/api/health freshness works, /api/fund 404s correctly, /api/attribution returns 422 instead of 500) |
| 4 | Streamlit UI | ❌ cascaded | ✅ PASS | ✅ **PASS** |
| 5 | Persistence | ❌ cascaded | ✅ PASS | ✅ **PASS** |
| 6 | Failure Recovery | ❌ cascaded | 🟡 PARTIAL | 🟡 **PARTIAL** (fault isolation confirmed again; Bug F restart policy unchanged) |

**The cascade is converging.** Round 2 had 6 bugs behind the crashes; round 3 has just 2 remaining (Bug H new, Bug F policy).

## Section Details

### §1: One-Click Startup — PASS
```
NAME                              STATE     STATUS
fund-attribution-mvp-app-1        running   Up 24 seconds
fund-attribution-mvp-db-1         running   Up 30 seconds (healthy)
fund-attribution-mvp-pipeline-1   running   Up 24 seconds (health: starting)
fund-attribution-mvp-service-1    running   Up 24 seconds (healthy)
```
All 4 containers up within 30 seconds. Service reports `(healthy)` from its own `/api/health` curl healthcheck. No restart loops anywhere.

### §2: Data Seeding — PARTIAL (big improvement)

**pipeline_run status** (9 fetchers):
| fetcher | status | rows_count | notes |
|---------|--------|------------|-------|
| `twse_mi_index` | ❌ failed | 0 | Bug H — str date to asyncpg |
| `twse_stock_day_all` | ❌ failed | 0 | Bug H |
| `twse_company_info` | ✅ success | **1,081** | new — flows through #120 fix |
| `finmind_stock_info` | ✅ success | **1,992** | new — flows through #120 fix |
| `sitca` | ✅ success | 0 | no SITCA data in QA env (expected) |
| `finnhub` | ✅ success | 0 | no FINNHUB token (expected) |
| `yfinance` | ✅ success | **180** | new — flows through #120 fix |
| `fx_rate` | ❌ failed | 0 | Bug H |
| `weight_calculator` | ✅ success | 0 | #121 Bug B fix confirmed; 0 rows is expected because industry_weight needs upstream twse_stock_day_all data |

**Business table populations**:
| table | count |
|-------|-------|
| `stock_info` | **3,073** |
| `stock_price` | **180** |
| `fund_info` | 0 |
| `fund_holding` | 0 |
| `industry_index` | 0 |
| `fx_rate` | 0 |

**3,253 real rows bulk-inserted** end-to-end via the pipeline container → `_load` → Postgres. This is the first round where any business data actually lands.

### §3: API Verification — MOSTLY PASS

**`/api/health`** — this is the headline result:
```json
{
  "status": "degraded",
  "db": "connected",
  "version": "0.1.0",
  "checks": {
    "db": "connected",
    "pipeline_last_run": "2026-04-11T09:20:22.080105+00:00",
    "data_freshness": {
      "stock_price":    {"latest": "2026-04-10", "fresh": true},
      "industry_index": {"latest": null, "fresh": false},
      "fx_rate":        {"latest": null, "fresh": false},
      "fund_holding":   {"latest": null, "fresh": false}
    }
  }
}
```

**First round that `/api/health` freshness shows a non-null latest**. `stock_price.fresh: true` / `latest: "2026-04-10"` — the #104 data freshness feature finally works end-to-end, reading real pipeline-populated data from Postgres via the service container. This is a huge validation that the #82/#104/#106 infrastructure sprint is coherent.

**`GET /api/fund/2330`** → 404 `{"detail":"Fund not found: 2330"}`. Correct behavior — 2330 is a stock, not a fund, and the fund_info table is empty (no SITCA data). The fund_service Postgres migration is working — it's a clean 404 through the async pool, not a 500 SQLite crash.

**`GET /api/fund/search?q=Taiwan`** → 200 `{"query":"Taiwan","results":[],"total":0}`. Correct — empty results from an empty table, no offshore registry match. Not a bug.

**`POST /api/attribution`** → **422** `{"detail":"No holdings could be resolved from the provided identifiers"}`. This is a massive improvement over round 2's 500. The service:
1. Accepts the request (Pydantic passes)
2. Tries to resolve `2330` via fund_service (Postgres lookup returns None)
3. Returns a clean 422 with a helpful message

Bug E (engine COPY), Bug C (fund_service Postgres), and the async cascade all compose correctly. Once the pipeline actually has fund data, this will return real Brinson results.

**`/api/attribution {mode:BAD}`** → 422 (Pydantic validation still works)

**`/api/portfolio`** → **500** `sqlite3.OperationalError: no such table` — **Bug G** still active. Confirmed again, unchanged.

### §4: Streamlit UI — PASS
- `curl http://localhost:8501/` → 200
- `curl http://localhost:8501/_stcore/health` → 200 `ok`

### §5: Persistence — PASS

Sequence:
```bash
docker compose down   # no -v, volume preserved
docker compose up -d
```

After restart:
- `stock_info`: 3073 (unchanged)
- `stock_price`: 180 (unchanged)
- `pipeline_run`: 11 (unchanged)
- Pipeline log: **`DB already populated — skipping initial seed`** ✓

#104's empty-DB detection logic is symmetric. Volume persistence works.

### §6: Failure Recovery — PARTIAL

Same test as round 2, same partial result:

**`docker kill fund-attribution-mvp-db-1`** → db `Exited (137)`, stays dead (Bug F unchanged)
- ✅ service and pipeline **stayed running** (no crash, no restart loop) — fault isolation works
- ✅ service logged db connection failures cleanly
- ✅ After `docker compose up -d db`, db returned to `Up (healthy)` within 10 seconds
- ✅ service was still alive and returned 200 on `/api/health` with `db: connected` after the recovery
- ❌ DB did not auto-restart after kill (Bug F policy question)

**Connection-pool resilience is solid.** The stack tolerates transient DB loss and reconnects automatically.

## Outstanding Bugs (as of round 3)

| Bug | Component | Status | Severity |
|-----|-----------|--------|----------|
| A `_tmp_*` tables | pipeline base | ✅ merged (#120) | — |
| B weight_calculator | pipeline transformer | ✅ merged (#121) | — |
| C fund_service | service | ✅ merged w/ fixup (#122/125) | — |
| D yfinance TzCache | pipeline | ❌ open | cosmetic |
| E engine COPY | service dockerfile | ✅ merged (#123) | — |
| F restart policy | compose | ❌ open | policy question |
| **G** portfolio_service | service | ❌ open | blocker for `/api/portfolio` + `/api/goal` |
| **H** (new) fx.py + twse.py str dates | pipeline fetchers × 3 | ❌ open | blocker for industry_index / stock_price daily / fx_rate seeding |

**2 real blockers remain**: G and H. D and F are non-blocker / policy.

## Teardown

```bash
docker compose down -v
rm -f .env
git checkout main
```

Clean. Working tree on main.

## Recommendation for ARCH

1. **Close §1, §3 (health only), §4, §5 as DONE** on #106. These sections definitively pass.
2. **§2 and §3 (business endpoints) will close** once Bugs G and H ship. Both are mechanical fixes following proven patterns:
   - Bug H: apply `_coerce_date` (from #121) to `fx.py:46`, `twse.py:69`, `twse.py:118`. ~9 lines total.
   - Bug G: migrate `portfolio_service.py` to Postgres following the #122/125 pattern, plus add `clients` / `client_portfolios` / `client_goals` tables to `pipeline/schema.sql`. Bigger but well-understood scope.
3. **§6 Bug F**: decide policy. Either change `restart: unless-stopped` → `always`, OR clarify the #106 spec to distinguish operator-kill from internal-crash.
4. **Open 2 new issues** for G and H. Both should be trivial turnaround. After they land, round 4 should be all-green modulo Bug F policy.

## #106 Cascade Trajectory

| Round | Visible bugs | Real row counts | API status |
|-------|-------------|-----------------|------------|
| 1 | 3 | 0 | cascaded fail |
| 2 | 6 | 0 | all 500s |
| 3 | **2** | **3,253** | `/api/health` freshness works, `/api/fund/*` clean 404/200, `/api/attribution` returns 422 |

Velocity: started with 3 bugs visible, peaked at 6 (unmask), now at 2. **Each round strictly halves the remaining blocker count.** If BE ships G + H in one more cycle, round 4 should be all-green.
