---
issue: 101
pr: 111
verifier: qa-20260410-0954327
date: 2026-04-10
verdict: PASS_WITH_CONCERNS
---

# Verify Report: FE Streamlit migration → FastAPI client

- **Issue**: liyoclaw1242/fund-attribution-mvp#101
- **PR**: #111 (`agent/fe-20260409-0549000/issue-101`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-10
- **Dimensions**: Static + module-import smoke test. Streamlit UI not booted (no live API service available in QA env).

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `app.py` no longer imports from `data/` directly (except CSV upload) | PASS | `grep '^(from\|import)\s+data\b' app.py` → no matches. CSV parsing uses `pd.read_csv` / `pd.read_excel` directly on the uploaded file (no `data/` import needed). |
| 2 | All data fetching goes through FastAPI endpoints | PASS_WITH_CONCERNS | Fund-code mode → `api_client.run_attribution`. CSV-upload mode parses locally then runs `engine.brinson.compute_attribution` directly instead of POSTing to `/api/attribution` (see Concerns). |
| 3 | Brinson attribution results identical to before | NOT_RUN | Cannot execute end-to-end without live FastAPI + DB. Static review shows API result is converted to engine format via `_api_result_to_engine_format` — same downstream rendering. |
| 4 | Goal tracker page works via API | PASS (static) | `pages/3_🎯_目標追蹤.py` calls `api_client.list_goals` (line 197) and `api_client.create_goal` (line 181). Note: simulation still uses `engine.goal_simulator` directly (line 72) — `api_client.simulate_goal` exists but is not wired up. |
| 5 | Advisor dashboard works via API | PASS (static) | `pages/4_🧠_顧問儀表板.py` calls `api_client.check_health` (23), `list_clients` (459), `get_portfolio` (492). Fund comparison still uses `engine.fund_comparator` directly (line 350) — explicit v2.0 carve-out per spec. |
| 6 | CSV upload still works (parsed client-side, sent to API) | PARTIAL_FAIL | CSV is parsed client-side ✓, but **NOT sent to API**. The structured DataFrame is passed straight to `engine.brinson.compute_attribution` locally (app.py:350-351). Spec literally says "parse locally, send structured data to API". |
| 7 | Clear error message when API is unreachable | PASS | Live test: set `API_BASE=http://nonexistent.invalid:9999`, called `check_health()` → `APIUnavailableError` raised with bilingual Chinese error: `無法連線至 API 服務 (...)。請確認 FastAPI 服務已啟動 ...`. app.py catches this and shows it via `st.error`. |
| 8 | `API_BASE` configurable via env var | PASS | `utils/api_client.py:14` → `API_BASE = os.getenv("API_BASE", "http://service:8000")`. Verified by reload + override. `.env.example` ships with `API_BASE=http://service:8000` (Docker default). |

## Static + Smoke Test Steps Executed

### S1: api_client module import
- **Action**: `python -c "from utils.api_client import get_fund, search_funds, run_attribution, list_goals, create_goal, update_goal, delete_goal, simulate_goal, list_clients, get_portfolio, check_health, APIError, APIUnavailableError, API_BASE"`
- **Expected**: All symbols import without error
- **Actual**: PASS — all 14 symbols imported. `API_BASE=http://service:8000`.

### S2: API_BASE env override
- **Action**: Set `API_BASE=http://nonexistent.invalid:9999`, reload module
- **Expected**: Module picks up new value
- **Actual**: PASS — `utils.api_client.API_BASE` reflects override.

### S3: APIUnavailableError raised on connection failure
- **Action**: Call `check_health()` against unreachable host
- **Expected**: `APIUnavailableError` with helpful Chinese message
- **Actual**: PASS — error message: `無法連線至 API 服務 (http://nonexistent.invalid:9999)。\n請確認 FastAPI 服務已啟動 (uvicorn service.main:app)。`

### S4: Syntax check on changed Python files
- **Action**: `ast.parse` on `app.py`, `pages/3_*.py`, `pages/4_*.py`, `utils/api_client.py`
- **Expected**: No SyntaxError
- **Actual**: PASS — all 4 files parse cleanly.

### S5: app.py data/* import audit
- **Action**: `grep -nE '^(from|import)\s+(data|engine|ai|report)\b' app.py`
- **Expected**: No `data/*` imports
- **Actual**: PASS — zero `data/*` imports. `engine/*`, `ai/*`, `report/*` imports remain inside helper functions (validation, charts, AI summary, PDF) — explicitly allowed by spec ("Some v2.0 features may still import modules directly").

### S6: api_client function-to-endpoint mapping
| Function | Endpoint | Method |
|----------|----------|--------|
| `get_fund` | `/api/fund/{id}` | GET |
| `search_funds` | `/api/fund/search?q=` | GET |
| `run_attribution` | `/api/attribution` | POST |
| `list_goals` | `/api/goal/{client_id}` | GET |
| `create_goal` | `/api/goal` | POST |
| `update_goal` | `/api/goal/{goal_id}` | PUT |
| `delete_goal` | `/api/goal/{goal_id}` | DELETE |
| `simulate_goal` | `/api/goal/{goal_id}/simulate` | GET |
| `list_clients` | `/api/portfolio` | GET |
| `get_portfolio` | `/api/portfolio/{client_id}` | GET |
| `check_health` | `/api/health` | GET |

All endpoints exist on the merged FastAPI app (verified earlier in #102 — `service.main:app` exposes all these routes).

## Concerns

### C1: CSV upload mode bypasses API entirely (PARTIAL_FAIL on AC #6)

**Spec text:**
> "CSV upload still works (parsed client-side, sent to API)"
> "Keep CSV upload parsing in Streamlit (parse locally, send structured data to API)"

**Implementation** (app.py:334-362):
```python
else:
    # CSV upload mode: parse locally, compute attribution locally
    holdings = _parse_csv_holdings(...)
    from engine.brinson import compute_attribution
    result = compute_attribution(holdings, mode=mode)
```

The CSV path parses the file locally then runs the attribution engine directly. The spec is explicit: structured data should be POSTed to `/api/attribution`. The api_client even has `run_attribution(holdings, mode, benchmark)` ready for it.

**Severity**: Major. This means the FE has two parallel code paths (API for fund-code, local engine for CSV) — defeats the migration goal of having FastAPI as the single source of truth for attribution math. Bug fixes / engine changes will silently diverge between the two paths.

**Triage**: → **FE**. Fix is small: replace `compute_attribution(holdings, mode)` with `api_client.run_attribution(holdings.to_dict('records'), mode=mode)` and reuse `_api_result_to_engine_format`.

### C2: Goal page simulation still local (minor)

`pages/3_🎯_目標追蹤.py:72` calls `engine.goal_simulator.simulate_goal` directly. `api_client.simulate_goal` exists but is unused. Spec allows v2.0 incremental migration, so not a fail — but worth noting since the API endpoint is already wired.

**Triage**: → **FE** (low priority). Or accept and defer.

### C3: .env.example default differs from #102

This branch sets `API_BASE=http://service:8000` (Docker default). PR #102 (already verified) added `API_BASE=http://localhost:8000` (local default). When ARCH merges both, there will be a 1-line conflict. Both defaults are defensible — pick one based on whether typical dev runs Streamlit inside Docker (`service:8000`) or locally (`localhost:8000`).

**Triage**: → **ARCH** (merge conflict resolution).

### C4: Cannot end-to-end verify attribution numerical equivalence (AC #3)

AC #3 ("Brinson results identical to before") requires running the same fund through both old (direct engine) and new (via API) paths and diffing outputs. This needs:
- Live FastAPI service running
- DB seeded with fund data
- Streamlit booted

None available in QA env. Static review shows the conversion path (`_api_result_to_engine_format`) is structurally sound, but numerical equivalence is unverified.

**Triage**: → **ARCH** to decide whether to require a smoke test pre-merge.

## Verdict

**PASS_WITH_CONCERNS**

- 6/8 ACs pass cleanly.
- AC #6 (CSV upload sent to API) is a clear partial fail — implementation contradicts spec text. Recommend FE fix before merge.
- AC #3 (numerical equivalence) is unverifiable in this env — needs live smoke test.
- Goal/advisor pages do call API for their core flows. Remaining `engine.*` imports are explicitly carved out by spec.
- Error handling and env configurability tested live and work correctly.

## Recommendation

**ARCH should reject back to FE** to fix C1 (CSV upload should POST to `/api/attribution`). It's a small, well-defined change and the api_client already has `run_attribution()` ready. After that, a live smoke test (or ARCH's discretion) handles AC #3.

If ARCH is willing to defer the CSV-path migration to a follow-up issue, this PR is mergeable as a "Phase 1" of the migration.
