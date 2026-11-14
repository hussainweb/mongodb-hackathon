# Billing Stack (Sample Demo Repo)

Lightweight billing reconciliation worker (`billing-worker`) with OpenTofu Docker provisioning under `deploy/tf/`.

## Structure
- `app/server.py` — Lightweight Python HTTP service exposing `/health` and `/ingest` with per-worker RPS limiting and v1/v2 env contract support.
- `app/Dockerfile` — Container image definition (`python:3.14-slim`).
- `deploy/tf/` — OpenTofu configuration (`main.tf`, `variables.tf`, `outputs.tf`, `prod.tfvars`) that provisions `docker_container.worker` replicas.
