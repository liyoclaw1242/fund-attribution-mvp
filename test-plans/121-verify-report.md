---
issue: 121
pr: 126
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS
---

# Verify Report: weight_calculator date-str bug

- **Issue**: liyoclaw1242/fund-attribution-mvp#121
- **PR**: #126 (`agent/be-20260411-0043144/issue-121`)
- **Verifier**: qa-20260410-0954327
- **Origin**: Bug B from #106 round-2. Minor, self-contained.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | Accepts both `date` and ISO string, normalizes to `date` | PASS | New `_coerce_date()` helper handles None / `date` / `datetime` / `str` / bad-type. Unit-tested via 5 new cases + verified live inside the running container. |
| 2 | Default uses `date.today()` (not `.isoformat()`) | PASS | Diff line -35 `date.today().isoformat()` → new helper line +27 `return date.today()`. |
| 3 | `docker compose up -d db pipeline` — no `toordinal` error in logs | PASS | `docker compose logs pipeline | grep toordinal` → **zero matches**. |
| 4 | `pipeline_run` shows successful weight_calculator runs | PASS | Live: `psql -c "SELECT fetcher, status, error_msg FROM pipeline_run WHERE fetcher LIKE '%weight%'"` → `weight_calculator | success | (null)`. |

## Verification Steps Executed

### S0: Pre-flight concurrent-change sanity check (new habit post-#122)
- **Action**: `git merge-base origin/main origin/agent/.../issue-121`, list files touched on branch, check recent main commits
- **Actual**: Branch base is `39f9dd2`. Branch touches only `pipeline/transformers/weight_calculator.py` and `tests/test_pipeline_transformers.py` — files that no other recent main commit modified. **No rebase-race risk.**
- **Bonus finding**: While checking main's recent history I noticed PR #125 (Bug C / #122) was merged as `d722c45` despite my `FAIL_REGRESSION` verdict. I checked `git show main:service/Dockerfile` — main now has both `COPY engine/` AND the pipeline-stub additions. **ARCH did the merge-with-fixup path I recommended as option 2. The engine COPY regression was correctly resolved.** No action needed from me.
- **Result**: PASS, safe to proceed

### S1: PR scope check
- **Action**: `git show --stat`
- **Actual**: 2 files, 102 insertions / 5 deletions.
  - `pipeline/transformers/weight_calculator.py`: +22 / -3 (adds `_coerce_date` helper + type annotation update)
  - `tests/test_pipeline_transformers.py`: +80 / -2 (5 new unit cases for `_coerce_date` + 3 regression cases for `fetch()`)
- **Result**: PASS — clean scope, 1 source file + 1 test file

### S2: Diff review
`_coerce_date(value) -> date` handles:
- `None` → `date.today()`
- `datetime` → `.date()` (strips time)
- `date` → identity
- `str` → `date.fromisoformat(value)`
- other → `TypeError`

`fetch()` now calls `_coerce_date(params.get("date"))`. Type annotation on `_compute_weights` changed from `str` → `date`. Clean, minimal, well-documented (docstring explains the asyncpg binding constraint).
- **Result**: PASS

### S3: Independent transformer audit
Walked every `.py` in `pipeline/transformers/` and grepped for `isoformat`, `date.today`, and any `date`-related patterns:

| File | Date usage | Bug pattern? |
|------|-----------|--------------|
| `__init__.py` | — | — |
| `currency.py` | `target_date: date \| str` → forwarded to `conn.fetchrow(..., target_date)` | **Latent risk** — type hint admits str, which would hit the same asyncpg `toordinal` error. BE's audit correctly noted "forwards whatever caller passes". Only test callers exist today — no production caller. |
| `industry_mapper.py` | No date handling | — |
| `weight_calculator.py` | Fixed by this PR | — |

**Finding**: `currency.py` carries a dormant version of the same bug. It isn't exercised today (only tests call it), but any future code that calls `currency.convert('USDTWD', '2026-04-11')` will crash with the exact same `toordinal` error. Not a blocker for this PR — out of scope per the issue's `Out of Scope` section ("Don't touch other transformers unless they have the identical bug"). BE's audit was technically correct; I'm noting this as a **latent risk for ARCH tracking, not a rejection**.
- **Result**: PASS (with note)

### S4: Unit tests
```
pytest tests/test_pipeline_transformers.py -q
========== 19 passed in 0.29s ==========
```
All 19 tests pass, including 8 new tests (5 `_coerce_date` + 3 `fetch()` regression).
- **Result**: PASS

### S5: Live Docker smoke
```bash
docker compose up -d --build db pipeline
```
Pipeline logs:
```
Schema migration complete
Registered: weight_calculator (0 17 * * 1-5)
...
Running: weight_calculator
WARNING: No market cap data for twse on 2026-04-11
WARNING: No market cap data for us on 2026-04-11
Completed: weight_calculator — 0 rows
```

The `No market cap data` warnings are expected — Bug A (pipeline `_tmp_*` tables) is still unfixed, so `stock_price` never gets seeded. But **weight_calculator itself ran to completion** — reached the query stage, got zero rows, logged the warning, and logged `Completed: ... — 0 rows` instead of crashing.

DB inspection:
```sql
SELECT fetcher, status, error_msg FROM pipeline_run WHERE fetcher LIKE '%weight%';
→ weight_calculator | success | (null)
```

Zero `toordinal` matches in any pipeline log.
- **Result**: PASS

### S6: Direct stress test — reproduce original bug + prove fix
Inside the running pipeline container I ran:
```python
from pipeline.transformers.weight_calculator import _coerce_date
from pipeline.db import create_pool

# Prove _coerce_date handles all inputs
print(_coerce_date(None))             # 2026-04-11
print(_coerce_date(date(2026,4,11)))  # 2026-04-11
print(_coerce_date('2026-04-11'))     # 2026-04-11

pool = await create_pool('...')
async with pool.acquire() as conn:
    # OLD pattern: str to asyncpg
    try:
        await conn.fetch('SELECT ... WHERE date = $1', '2026-04-11')
    except Exception as e:
        print(f'REPRODUCED: {type(e).__name__}: {e}')
    # NEW pattern via helper
    d = _coerce_date('2026-04-11')
    await conn.fetch('SELECT ... WHERE date = $1', d)
    print('OK via coerced date')
```

Output:
```
None → 2026-04-11
date(2026,4,11) → 2026-04-11
"2026-04-11" → 2026-04-11
str to asyncpg: REPRODUCED error — DataError: invalid input for query argument $1: '2026-04-11' ('str' object has no attribute...
date to asyncpg: OK (coerced type=date)
```

**This is the strongest possible evidence**: the exact original `toordinal` error is reproducible with the old pattern against live asyncpg, and switching to `_coerce_date()` output makes the same query succeed. The fix is conclusively correct.
- **Result**: PASS

### S7: Teardown
```bash
docker compose down -v
rm -f .env
git checkout main
```
Working tree clean on main. No residue.

## Latent Risk Note (not a blocker)

`pipeline/transformers/currency.py` has the same `date | str` type hint on its public API and forwards the value to asyncpg without coercion. If any future production caller passes a str, it'll hit the exact same `toordinal` error. BE's audit called this out as "forwards whatever caller passes" — technically correct, dormant because no production caller exists today.

**Recommendation to ARCH**: open a small follow-up issue to apply the same `_coerce_date` pattern to `currency.py` before anyone adds a production caller. The fix is mechanical (one helper call, ~3 lines).

## Verdict

**PASS**

- All 4 ACs pass with direct evidence
- 19/19 transformer unit tests pass
- Live docker smoke: `weight_calculator` runs to completion with `status=success`, zero `toordinal` errors
- Direct asyncpg stress-test reproduces the original bug AND proves the fix
- Clean scope (1 source file + 1 test file)
- Good audit (BE correctly identified `currency.py` as related but out-of-scope)

## Recommendation

**Merge.** Closes Bug B from #106. Optionally open a small follow-up issue for `currency.py` latent risk (not a blocker).

## #106 Bug Cascade Status

| Bug | Status |
|-----|--------|
| A pipeline `_tmp_*` tables | ❌ open (still blocks data seeding — most remaining damage) |
| **B weight_calculator str→date** | ✅ **this PR** |
| C fund_service SQLite→Postgres | 🟡 partially merged (PR #125 + ARCH fixup landed; regression closed) |
| D yfinance TzCache warning | ❌ open (cosmetic) |
| E service Dockerfile missing engine/ | ✅ merged #124 + preserved through ARCH fixup in #125 |
| F docker kill + unless-stopped policy | ❌ open (policy question) |
| G portfolio_service still SQLite | ❌ open (hidden, same class as C) |

After this merge: **2 blockers left** (A, G). Bug A is still the biggest remaining gap — without it, no data flows into stock_price / industry_index / fund_holding, so everything downstream runs with empty tables.
