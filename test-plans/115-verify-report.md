---
issue: 115
pr: 118
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: Fix stock_price PK / PARTITION BY expression conflict

- **Issue**: liyoclaw1242/fund-attribution-mvp#115
- **PR**: #118 (`agent/be-20260411-0043144/issue-115`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Origin**: Bug #2 from #106 live smoke. BE picked **Option A** (drop partitioning).

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `pipeline/schema.sql` applies cleanly on fresh Postgres 15+ | PASS | Live against `postgres:16-alpine`. `docker compose logs pipeline` includes `Schema migration complete`. Previous error (`FeatureNotSupportedError: PRIMARY KEY constraints cannot be used when partition keys include expressions`) gone. |
| 2 | `docker compose up -d db pipeline` — pipeline reaches steady state, no migration errors | PASS | After forced rebuild (`--build`), pipeline container: `running (health: starting)` for 17+ seconds with no restart-loop. Only log errors are fetcher network failures (`twse_mi_index`, `fx_rates`, etc.), which are expected in the QA env (no API tokens, no network). **Scheduler reached the post-migration cron loop — that's the AC target.** |
| 3 | `psql -c '\d stock_price'` shows expected structure | PASS | Live output: 7 columns (`stock_id`, `date`, `close_price`, `change_pct`, `volume`, `market_cap`, `source`), `PRIMARY KEY, btree (stock_id, date)`, `idx_stock_price_date btree (date)`. No `stock_price_default` child table. |
| 4 | Smoke INSERT of 5 rows (TW + US prefixes) round-trips | PASS | Inserted 2330, 2454 (TW `twse`), AAPL, MSFT, NVDA (US `yfinance`) — INSERT 0 5, SELECT returned all 5 rows ordered by stock_id, count = 5. |
| 5 | Code audit: no orphan `stock_price_default` references | PASS | `grep -rn "stock_price_default\|PARTITION"` across repo: only hits are (a) the schema.sql itself (removed), (b) a test assertion in `tests/test_pipeline_db.py:37` that excludes `PARTITION OF` from idempotency check (generic, still works), (c) historical verify reports. Zero live code depends on the old partition structure. |

## Verification Steps Executed

### S1: PR scope check
- **Action**: `git show --stat HEAD`
- **Actual**: `pipeline/schema.sql | 13 +++++++------` — single file, 7 insertions / 6 deletions. Zero scope drift.
- **Result**: PASS

### S2: Schema diff review
Diff removes `PARTITION BY LIST (substring(stock_id, 1, 1))` and the `stock_price_default` child table. Adds an explanatory comment block above the `stock_price` definition citing the root cause and the rationale for dropping partitioning. Clean, documented, minimal.
- **Result**: PASS

### S3: Orphan reference audit
- **Action**: `grep -rn "stock_price_default|PARTITION"` across repo
- **Actual**: 4 files match — schema.sql (the fix), `tests/test_pipeline_db.py` (generic test), `test-plans/106-verify-report.md` + `test-plans/84-verify-report.md` (historical docs). Zero production code references.
- **Result**: PASS

### S4: Live docker smoke — attempt 1 (FAILED, stale image)
First try: `docker compose up -d db pipeline` without `--build`. Pipeline crashed with `InvalidObjectDefinitionError: "stock_price" is not partitioned`. Diagnosed as stale cached image from #106 run — the image had the OLD schema.sql baked in and some code path was trying to treat `stock_price` as partitioned when the (correct) new schema had already created it as plain.

**Lesson for future QA**: when re-verifying a fix after a prior FAIL, ALWAYS `docker compose down -v` (remove volumes) AND `--build` (force rebuild). Stale images are silent.

### S5: Live docker smoke — attempt 2 (PASS, rebuilt)
```
docker compose down -v
docker compose up -d --build db pipeline
```

Container state at t+17s:
```
NAME                              STATE     STATUS
fund-attribution-mvp-db-1         running   Up 22 seconds (healthy)
fund-attribution-mvp-pipeline-1   running   Up 17 seconds (health: starting)
```

Pipeline logs (filtered):
```
pipeline-1 | Schema migration complete
pipeline-1 | ERROR: Failed: twse_mi_index          ← expected (no network in QA)
pipeline-1 | ERROR: Failed: twse_stock_day_all     ← expected
pipeline-1 | ERROR: Failed: finmind_stock_info     ← expected (no token)
... (all fetcher failures are network/credential failures, not schema)
```

The critical log line `Schema migration complete` is the AC target. Subsequent fetcher errors are orthogonal to this issue and were the expected failure mode in the #106 "seed runs" scenario that got cascaded out.

### S6: Table structure + round-trip
```sql
\d stock_price
  stock_id | text          | not null
  date     | date          | not null
  close_price | numeric(12,4) |
  change_pct  | numeric(8,4)  |
  volume      | bigint        |
  market_cap  | numeric(18,0) |
  source      | text          | not null
Indexes:
    "stock_price_pkey" PRIMARY KEY, btree (stock_id, date)
    "idx_stock_price_date" btree (date)

INSERT INTO stock_price VALUES ('2330', ...), ('2454', ...),
                                ('AAPL', ...), ('MSFT', ...), ('NVDA', ...);
→ INSERT 0 5

SELECT stock_id, date, close_price, source FROM stock_price ORDER BY stock_id;
→ 2330 | 2026-04-10 |  850.0000 | twse
  2454 | 2026-04-10 | 1100.0000 | twse
  AAPL | 2026-04-10 |  175.5000 | yfinance
  MSFT | 2026-04-10 |  420.7500 | yfinance
  NVDA | 2026-04-10 |  900.0000 | yfinance
(5 rows)

SELECT count(*) FROM stock_price; → 5
```

TW (`twse`) and US (`yfinance`) prefixes both succeed. The dropped partition key (`substring(stock_id, 1, 1)`) is now irrelevant — the plain table accepts any prefix.

- **Result**: PASS

### S7: Tear down
```
docker compose down -v
→ Container ... Removed, Volume ... Removed, Network ... Removed
rm -f .env
```

Clean state restored.

## Verdict

**PASS**

- All 5 ACs pass with direct live evidence.
- Fix is minimal (13 lines, 1 file) and well-documented (inline comment explains the Postgres constraint + the rationale for dropping partitioning).
- Pipeline container now reaches steady-state scheduler loop on fresh DB.
- Table accepts both TW and US prefixes; round-trip verified.
- Zero orphan references to the old `stock_price_default` child table.

## Recommendation

**Merge.** This closes Bug #2 from #106. Bug #1 (service pandas) and Bug #3 (start.sh array expansion) are tracked separately (#116 already has a PR). Once both fixes land, #106 should be re-verified with a full stack smoke.

## Note for #106 Follow-up

After this PR and #116 merge, re-running `docker compose up -d` should give us:
- `db` healthy ✓ (already works)
- `pipeline` running ✓ (fixed by this PR)
- `service` running — still blocked by Bug #1 (pandas). No PR yet.
- `app` running ✓ (always worked)

So #106's full-stack re-verify still needs one more fix (pandas) before it can turn green.
