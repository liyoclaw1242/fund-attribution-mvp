# Verify Report: OPS: Pipeline Docker container + compose integration

- **Issue**: liyoclaw1242/fund-attribution-mvp#88
- **PR**: #94
- **Verifier**: qa-20260408-0847587
- **Date**: 2026-04-08
- **Verdict**: FAIL

## Results

| Step | Description | Result | Notes |
|------|-------------|--------|-------|
| A1 | pipeline/Dockerfile structure | PASS | python:3.12-slim, curl installed, layer-cached pip install, COPY ./pipeline/ |
| A2 | pipeline/requirements.txt pinned | PASS | All deps with upper bounds, finnhub-python included |
| A3 | docker-compose.yml: db service | PASS | postgres:16-alpine, healthcheck, named volume, correct credentials |
| A4 | docker-compose.yml: pipeline service | PASS | depends_on db healthy, env vars, restart: unless-stopped |
| A5 | docker-compose.yml: app service preserved | PASS | No changes to existing app service |
| A6 | .env.example updated | PASS | POSTGRES_PASSWORD, FINNHUB_API_KEY, FINMIND_API_TOKEN added |
| A7 | README updated | PASS | Quick Start + project structure updated with pipeline section |
| A8 | HEALTHCHECK URL correct | FAIL | Uses `http://localhost:8080/` but health endpoint is `/health` |
| A9 | Pipeline dependencies in container | WARN | sitca.py imports `data.sitca_parser`, industry_mapper.py reads `data/mapping.json` — both outside container's COPY scope, use fallbacks |

## Failures

### A8: HEALTHCHECK URL mismatch

**Dockerfile line 13:**
```
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8080/ || exit 1
```

**scheduler.py line 152:**
```python
self._health_app.router.add_get("/health", self._health_handler)
```

The health endpoint is at `/health`, not `/`. The HEALTHCHECK will hit `/` which returns 404 (no route registered for root). Docker will mark the container as **unhealthy** after retries.

**Fix:** Change HEALTHCHECK to `curl -f http://localhost:8080/health || exit 1`

**Severity:** Major — container will be marked unhealthy, and `depends_on: condition: service_healthy` consumers will never start.

### A9: Container isolation concern (minor)

Two pipeline modules reference files outside the `pipeline/` directory:
- `pipeline/fetchers/sitca.py:62` — `from data.sitca_parser import parse_sitca_excel` (fallback to `pd.read_excel`)
- `pipeline/transformers/industry_mapper.py:15` — `data/mapping.json` (fallback to empty mapping)

Both have graceful fallbacks, so the container won't crash, but SITCA parsing and industry mapping will be degraded.

**Triage:** → OPS for the HEALTHCHECK fix (1-line change)

## Summary

Overall solid Docker/compose setup with correct service topology, healthchecks, persistence, and env var management. One bug: HEALTHCHECK URL is missing `/health` path — will cause container to be marked unhealthy. Existing app service is preserved.
