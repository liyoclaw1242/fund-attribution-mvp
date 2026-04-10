---
issue: 102
pr: 110
verifier: qa-20260410-0954327
date: 2026-04-10
verdict: PASS_WITH_CONCERNS
---

# Verify Report: Service Docker container + compose integration

- **Issue**: liyoclaw1242/fund-attribution-mvp#102
- **PR**: #110 (`agent/ops-20260409-0549056/issue-102`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-10
- **Dimensions**: Static (Dockerfile / compose / module import). Live Docker build NOT executed — daemon unavailable in QA env.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `docker-compose build service` succeeds | NOT_RUN | Docker daemon unavailable. Static review of `service/Dockerfile` passes (valid base image, requirements file present, COPY paths exist). |
| 2 | `docker-compose up` starts all 4 containers | NOT_RUN | Compose file validated structurally — services `db`, `pipeline`, `service`, `app` all defined. |
| 3 | Service waits for DB healthcheck | PASS | `service.depends_on = {db: {condition: service_healthy}}`; `db` defines `pg_isready` healthcheck. |
| 4 | Service `/api/health` HEALTHCHECK works | PASS | Imported `service.main:app` — route `/api/health` is registered. Dockerfile `HEALTHCHECK curl -f http://localhost:8000/api/health` matches. |
| 5 | Streamlit connects via `API_BASE` | PASS | `app.environment.API_BASE=http://service:8000`; `app.depends_on=[service]`; `.env.example` contains `API_BASE=http://localhost:8000`. |
| 6 | Existing containers still work | PASS (static) | Existing `db` and `pipeline` services unchanged in compose; `app` only gains `API_BASE` + `depends_on: service`. |

## Static Verification Steps Executed

### S1: Dockerfile structure
- **Action**: Read `service/Dockerfile`
- **Expected**: python:3.12-slim base, installs requirements, EXPOSE 8000, HEALTHCHECK on /api/health, CMD uvicorn service.main:app
- **Actual**: All present. Adds `curl` (needed for HEALTHCHECK — improvement vs spec). Build context is repo root (compose `context: .`), `COPY service/ ./service/` and `COPY config/ ./config/` are correct relative paths.
- **Result**: PASS

### S2: docker-compose.yml service definition
- **Action**: Parse compose YAML, inspect `service` block
- **Expected**: build → service/Dockerfile, depends_on db healthy, POSTGRES_URL + ANTHROPIC_API_KEY env, port 8000, restart unless-stopped
- **Actual**: All present. `build.context=.`, `build.dockerfile=service/Dockerfile` (correct given Dockerfile uses repo-root relative COPY paths).
- **Result**: PASS

### S3: docker-compose.yml app updates
- **Action**: Inspect updated `app` service
- **Expected**: `API_BASE=http://service:8000`, `depends_on: [service]`
- **Actual**: Both present.
- **Result**: PASS

### S4: .env.example update
- **Action**: `cat .env.example`
- **Expected**: `API_BASE` entry
- **Actual**: `API_BASE=http://localhost:8000` present.
- **Result**: PASS

### S5: README architecture documentation
- **Action**: Read README "Architecture" section
- **Expected**: Document 4-container architecture with db/pipeline/service/app and ports
- **Actual**: New "Architecture" section with arrow diagram and per-container port table; Quick Start updated to describe 4-container stack.
- **Result**: PASS

### S6: FastAPI app importability
- **Action**: `python -c "from service.main import app; print(app.routes)"`
- **Expected**: `service.main:app` resolves to a FastAPI instance with `/api/health`
- **Actual**: FastAPI app imports cleanly. Routes include `/api/health`, `/api/fund/*`, `/api/attribution`, `/api/portfolio`, `/api/goal/*`.
- **Result**: PASS

## Concerns (Out-of-Scope Changes)

The PR contains changes beyond the spec's deliverables. These are unrelated to "Service Docker container + compose integration":

1. **`app.py`** — refactored chart rendering imports (`render_waterfall` → `generate_waterfall`, similar for sector chart). This appears to be a fix for an integration mismatch but is not in the spec.
2. **`data/fund_lookup.py`** — adds `_fallback_golden()` helper and golden-dataset fallback path for fund codes 0050 and 006208. Not in the spec.
3. **`smoke_test_report.md`** — updated content unrelated to compose integration.
4. **`test-plans/99-verify-report.md`** — added a verify report for issue #99 (different issue).

These changes may be valid bug fixes, but they violate spec scope and should have been separate issues / PRs. ARCH should decide whether to:
- Accept as-is (if the changes are needed to make the stack actually run together), or
- Ask OPS to split them out.

## Live Build Limitation

Acceptance criteria #1 and #2 (`docker-compose build service` and `docker-compose up` actually starting all containers) were **NOT executed** because the Docker daemon is not available in the QA environment. Static analysis indicates the build SHOULD succeed:

- Base image `python:3.12-slim` is valid
- `service/requirements.txt` exists with valid pins (fastapi, uvicorn, sqlalchemy, asyncpg, pydantic)
- COPY paths `service/` and `config/` exist at repo root (build context = `.`)
- `HEALTHCHECK curl -f http://localhost:8000/api/health` will work since `curl` is installed and the route exists

A live `docker-compose up` smoke test by ARCH or OPS in an env with Docker is recommended before merging.

## Verdict

**PASS_WITH_CONCERNS**

All testable acceptance criteria pass via static review. The Docker build itself was not executable in this env, but every prerequisite for it (Dockerfile correctness, source paths, module importability, compose wiring) passes inspection. Out-of-scope code changes flagged for ARCH triage.

## Recommendation

- **Merge-eligible**: Yes, contingent on a live `docker-compose build service` smoke test (or ARCH accepting static-only verification).
- **Triage ask**: ARCH should decide whether the unrelated `app.py` / `data/fund_lookup.py` changes belong in this PR or should be split.
