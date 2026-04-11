# Kubernetes Migration Path

This document describes how to migrate the Fund Attribution MVP from Docker
Compose to Kubernetes once the system outgrows single-host deployment.

## When to migrate

Stay on Compose if:
- Traffic is served from one host
- Single-user or small-team usage
- You prefer a single `docker compose up` lifecycle

Migrate to K8s if you need any of:
- Horizontal scaling of `service` (FastAPI) under load
- Multi-node fault tolerance for `db`
- Independent release cadence per component
- Per-fetcher scheduling with isolated failure domains

## Compose → K8s resource mapping

| Compose                 | K8s Equivalent                                      | Notes |
|-------------------------|-----------------------------------------------------|-------|
| `db` service            | `StatefulSet` + headless `Service` + `PVC`          | One replica; use managed Postgres (RDS/Cloud SQL) for production |
| `pipeline` service      | `CronJob` (per fetcher) **or** `Deployment`         | CronJob is cheaper if fetchers are independent; Deployment if APScheduler stays in-process |
| `service` service       | `Deployment` + `Service` + `HPA`                    | Stateless; scale on CPU / request latency |
| `app` service           | `Deployment` + `Service` + `Ingress`                | Streamlit holds WebSocket state; use session affinity |
| `nginx` (prod profile)  | `Ingress` (nginx-ingress / traefik)                 | Drop the container — ingress controller replaces it |
| `.env`                  | `ConfigMap` (non-secret) + `Secret` (API keys)      | Split: `POSTGRES_PASSWORD`, `ANTHROPIC_API_KEY`, `FINNHUB_API_KEY`, `FINMIND_API_TOKEN` → Secret |
| `pgdata` volume         | `PersistentVolumeClaim` (bound to StatefulSet)      | Use a `StorageClass` with snapshots |
| `./data/sitca_raw` bind | `PersistentVolumeClaim` (RWX) **or** object storage | Preferred: push SITCA files to S3/GCS and drop the bind mount |
| `./output` bind         | Object storage (S3/GCS)                             | PDF artifacts should not live on pod disk |

## Migration order (low-risk)

1. **Externalize state first.** Move Postgres to a managed service and swap
   the `db` container for a `Service` of type `ExternalName`. Compose stack
   still runs; validate the new DB end-to-end.
2. **Externalize file storage.** Move `data/sitca_raw` and `output` to object
   storage. Update `config/settings.py` to read the bucket URI.
3. **Split secrets.** Move API keys out of `.env` into a Secret store
   (Vault, AWS Secrets Manager, SOPS). Compose still works via env vars.
4. **Containerize for K8s.** Verify each image runs as non-root with a
   read-only root filesystem where possible. Add liveness + readiness probes
   matching the compose `healthcheck` blocks.
5. **Deploy `service` to K8s.** Point Compose `app` at the K8s `service`
   Ingress URL via `API_BASE`. Validate.
6. **Deploy `app` to K8s.** Configure session affinity on the Ingress so
   Streamlit WebSocket reconnects hit the same pod.
7. **Move `pipeline` to CronJob.** One CronJob per fetcher. Drop APScheduler.
8. **Decommission Compose.** Keep `docker-compose.yml` for local dev.

## Probes

| Service   | Liveness                       | Readiness                      |
|-----------|--------------------------------|--------------------------------|
| `db`      | `pg_isready`                   | `pg_isready`                   |
| `service` | `GET /api/health`              | `GET /api/health`              |
| `app`     | `GET /_stcore/health`          | `GET /_stcore/health`          |
| `pipeline`| Process-based (if Deployment)  | n/a for CronJob                |

## Resources

Starting points — tune after load testing:

| Service   | requests (cpu/mem) | limits (cpu/mem) | replicas |
|-----------|--------------------|------------------|----------|
| `service` | 100m / 256Mi       | 500m / 512Mi     | 2 (HPA: 2–6) |
| `app`     | 100m / 384Mi       | 500m / 768Mi     | 2        |
| `pipeline`| 50m / 256Mi        | 200m / 512Mi     | 1        |
| `db`      | 200m / 512Mi       | 1000m / 2Gi      | 1        |

## Out of scope

- Service mesh (Istio/Linkerd) — not needed until inter-service mTLS is required
- Multi-cluster / multi-region — single region is sufficient for the MVP
- GitOps (ArgoCD/Flux) — optional but recommended once more than one engineer
  is deploying
