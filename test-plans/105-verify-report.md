---
issue: 105
pr: 113
verifier: qa-20260410-0954327
date: 2026-04-11
verdict: PASS_WITH_BLOCKED_AC
---

# Verify Report: Final compose consolidation + nginx proxy + K8s migration docs

- **Issue**: liyoclaw1242/fund-attribution-mvp#105
- **PR**: #113 (`agent/ops-20260411-0043237/issue-105`)
- **Verifier**: qa-20260410-0954327
- **Date**: 2026-04-11
- **Dimensions**: Static review + structural compose validation. Docker daemon unavailable in QA env — live `docker compose up` ACs cannot be executed.

## Acceptance Criteria Results

| # | Criterion | Result | Evidence |
|---|-----------|--------|----------|
| 1 | `docker compose up -d` starts all services, all healthy | **BLOCKED** (static PASS) | Compose file structurally complete: 5 services with correct `depends_on` chain. `db` has `pg_isready` healthcheck; `service` has curl `/api/health` healthcheck with `start_period: 20s`; `app`/`pipeline`/`nginx` rely on container-up. Cannot execute live without Docker daemon. |
| 2 | `docker compose down && up -d` — data persists | **BLOCKED** (static PASS) | `pgdata` named volume declared at top level (line 80-81) and bound to `db` at `/var/lib/postgresql/data`. Named volumes survive `down`. |
| 3 | `.env.example` has ALL required env vars documented | PASS | Cross-referenced every `${VAR}` interpolation in `docker-compose.yml` against `.env.example`: `POSTGRES_PASSWORD`, `FINNHUB_API_KEY`, `FINMIND_API_TOKEN`, `SCHEDULER_TIMEZONE`, `ANTHROPIC_API_KEY`, `API_BASE` all present. Plus app-runtime vars: `BRINSON_MODE`, `TWSE_RATE_LIMIT_DELAY`, `SITCA_DATA_DIR`. Zero missing. |
| 4 | Nginx profile works with `--profile production` | PASS (static) | `nginx` service has `profiles: [production]` — will not start without the flag. `depends_on: [app, service]`. Config file bind-mounted RO. Cannot execute live. |
| 5 | K8s migration doc created | PASS | `docs/k8s-migration.md` (77 lines). Includes the 8-row resource mapping table required by spec, plus bonus: "When to migrate" heuristic, migration order (8-step low-risk sequence), liveness/readiness probe table, resource request/limit starting points, out-of-scope list. Exceeds spec. |
| 6 | README updated with full architecture diagram | PASS | README.md lines 23-60 show ASCII architecture diagram including nginx (production profile), per-container port table, dependency chain description, and a link to `docs/k8s-migration.md`. Quick Start updated to mention both `scripts/start.sh` and direct `docker compose up`. |

## Static Verification Steps

### S1: PR scope check
- **Action**: `git show --stat HEAD`
- **Expected**: Only files listed in the spec
- **Actual** (6 files, all on-spec):
  - `.env.example` (+22)
  - `README.md` (+66)
  - `docker-compose.yml` (+83)
  - `docs/k8s-migration.md` (+77, new file)
  - `ops/nginx.container.conf` (+52, new file)
  - `scripts/start.sh` (+43, new file, executable mode `755`)
- **Result**: PASS — zero scope drift.

### S2: docker-compose.yml structural validation
Parsed via PyYAML, inspected every service:

| Service | `depends_on` | `healthcheck` | `restart` | `profiles` | `ports` |
|---------|-------------|---------------|-----------|------------|---------|
| `db`      | — | `pg_isready -U pipeline -d fund_data` (5s/3s, 5 retries) | `unless-stopped` | — | `5432:5432` |
| `pipeline`| `db: service_healthy` | — | `unless-stopped` | — | — |
| `service` | `db: service_healthy` | `curl /api/health` (10s/5s, 5 retries, `start_period: 20s`) | `unless-stopped` | — | `8000:8000` |
| `app`     | `service` | — | `unless-stopped` | — | `8501:8501` |
| `nginx`   | `app`, `service` | — | `unless-stopped` | `production` | `80:80`, `443:443` |

Top-level `volumes: {pgdata: null}` ✓.

**Dependency chain matches spec exactly:**
```
db (healthy) ──→ pipeline
db (healthy) ──→ service (healthy) ──→ app
                                   ╲
                                    nginx ──► app + service (production profile)
```

- **Result**: PASS

### S3: Nginx config review
Read `ops/nginx.container.conf`:

- ✅ Upstreams declared for `app:8501` and `service:8000` (uses compose bridge network DNS)
- ✅ `/api/` → `fastapi_upstream` with X-Forwarded-* headers + 120s timeout
- ✅ **`/_stcore/stream` WebSocket location declared BEFORE `/`** (correct ordering — `nginx` matches prefix-longest-first for regex-free locations so this isn't strictly required, but the explicit block with `proxy_read_timeout 86400s` is the safe pattern)
- ✅ `/` → `streamlit_upstream` with `Upgrade`/`Connection: upgrade` headers (Streamlit's non-stream routes also use WS)
- ✅ `client_max_body_size 10M` — allows CSV/Excel uploads
- ✅ Header comment explicitly notes this is the container-internal variant; host-based TLS deploys would use a different file

- **Result**: PASS

### S4: `.env.example` completeness
Cross-ref against all `${VAR}` interpolations in compose:

| Variable | Used by | In .env.example? |
|----------|---------|------------------|
| `POSTGRES_PASSWORD` | db, pipeline, service | ✅ |
| `FINNHUB_API_KEY` | pipeline | ✅ |
| `FINMIND_API_TOKEN` | pipeline | ✅ |
| `SCHEDULER_TIMEZONE` | pipeline | ✅ |
| `ANTHROPIC_API_KEY` | service | ✅ |
| `API_BASE` | app (from env_file) | ✅ |

Plus app-runtime vars documented: `BRINSON_MODE`, `TWSE_RATE_LIMIT_DELAY`, `SITCA_DATA_DIR`.

- **Result**: PASS

### S5: `scripts/start.sh` review
Read the script:

- ✅ `set -euo pipefail` — strict mode
- ✅ `cd "$(dirname "$0")/.."` — runs from anywhere
- ✅ `.env` auto-created from `.env.example` on first run, then exits with a clear next-step message
- ✅ Post-first-run: warns if `ANTHROPIC_API_KEY` still looks unset
- ✅ `production` arg triggers `--profile production` (nginx)
- ✅ Post-startup: prints helpful URLs (Streamlit, FastAPI docs, nginx)
- ✅ Executable mode (`-rwxr-xr-x`)

Minor observation: the warning check (`grep -q "^ANTHROPIC_API_KEY=sk-"`) will miss a key that starts with another prefix, but this is a soft warning, not a blocker.

- **Result**: PASS

### S6: `docs/k8s-migration.md` content check
Required by spec: the Compose → K8s resource mapping table. Present (8 rows — exceeds the 6 in the spec by adding `./data/sitca_raw` and `./output` bind mounts).

Bonus content beyond spec:
- "When to migrate" / "When to stay on Compose" decision section
- 8-step migration order for low-risk cutover
- Per-service liveness/readiness probe table
- Per-service CPU/memory request/limit starting points with HPA settings
- Out-of-scope list (service mesh, multi-region, GitOps)

- **Result**: PASS

### S7: README architecture section
Lines 23-60 contain:
- ✅ ASCII diagram showing nginx → app + service → db with pipeline on the side
- ✅ Per-container port/purpose table
- ✅ Dependency chain prose
- ✅ Link to `docs/k8s-migration.md`
- ✅ Quick Start updated to show both `scripts/start.sh [production]` and direct `docker compose` commands

- **Result**: PASS

## Live Execution Gap

ACs #1, #2, and #4 require a live Docker daemon which is unavailable in this QA env (same constraint as #102 and #103). Static evidence is very strong:
- Compose file structurally sound (parsed + walked)
- All env vars wired
- Named volume declared
- Nginx profile correctly gated
- Service healthcheck targets an endpoint already verified in #104

A live smoke test on a machine with Docker should be a 5-minute exercise:
```bash
scripts/start.sh               # dev stack
docker compose ps              # all up
docker compose down
docker compose up -d           # data survives
scripts/start.sh production    # with nginx
curl http://localhost/         # streamlit via nginx
curl http://localhost/api/health  # fastapi via nginx
```

## Verdict

**PASS_WITH_BLOCKED_AC**

- 3/6 ACs pass with full static evidence (env completeness, K8s doc, README).
- 3/6 ACs blocked on Docker daemon but structurally validated — very high confidence they'll pass live.
- Zero scope drift. Zero concerns. The PR is a clean consolidation task done well:
  - Nginx config is container-aware and correctly handles Streamlit's WebSocket path
  - K8s doc exceeds spec (8-row mapping, migration order, probes, resources)
  - `scripts/start.sh` is polished (env bootstrap, profile flag, helpful output, strict mode)
  - Compose dependency chain is exactly what the spec diagram shows

## Recommendation

**Merge** after a live smoke test on a machine with Docker (5-minute exercise per commands above). If ARCH is willing to trust the static review, the PR is merge-eligible as-is — same pattern as #102's merge decision.
