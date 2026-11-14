"""Target microservice (port 8001) supporting v1/v2 contract drift, silent 202 drops, and verification."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from mongodb_hackathon.models import ChaosMode, utc_now

app = FastAPI(title="FinishLine Target Deployment Service", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DeploymentV1Request(BaseModel):
    """Contract v1 payload expected before schema drift."""

    service_name: str
    branch: str
    commit_sha: str
    webhook_url: str
    rate_limit: int = Field(ge=1, le=10000)
    idempotency_key: str


class DeploymentV2Request(BaseModel):
    """Contract v2 payload after breaking schema drift (renamed fields + env_tier)."""

    service_name: str
    branch: str
    commit_sha: str
    callback_uri: str
    max_rps: int = Field(ge=1, le=10000)
    env_tier: str = Field(pattern="^(staging|canary|production)$")
    idempotency_key: str


class ChaosToggleRequest(BaseModel):
    """Payload for switching live chaos injection mode."""

    mode: ChaosMode


class _ServiceState:
    """In-memory mutable target service state for live chaos demos and tests."""

    def __init__(self) -> None:
        self.chaos_mode: ChaosMode = ChaosMode.NORMAL
        self.deployments: dict[str, dict[str, Any]] = {}
        self.idempotency_index: dict[str, str] = {}
        self.dropped_attempts: dict[str, int] = {}
        self.request_log: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.chaos_mode = ChaosMode.NORMAL
        self.deployments.clear()
        self.idempotency_index.clear()
        self.dropped_attempts.clear()
        self.request_log.clear()


state = _ServiceState()


def _record_request(method: str, path: str, status_code: int, summary: str) -> None:
    state.request_log.append(
        {
            "ts": utc_now().isoformat(),
            "method": method,
            "path": path,
            "status_code": status_code,
            "summary": summary,
        }
    )
    if len(state.request_log) > 40:
        state.request_log = state.request_log[-40:]


@app.get("/health")
async def health() -> dict[str, Any]:
    """Return service health, active chaos mode, and live active deployment count."""
    active = [d for d in state.deployments.values() if d.get("active")]
    return {
        "status": "ok",
        "chaos_mode": state.chaos_mode.value,
        "api_version": "v2" if state.chaos_mode == ChaosMode.DRIFT_V2 else "v1",
        "active_deployments": len(active),
        "total_records": len(state.deployments),
    }


@app.get("/state")
async def get_state() -> dict[str, Any]:
    """Return full inspectable target state for the Control Room and verification."""
    return {
        "chaos_mode": state.chaos_mode.value,
        "api_version": "v2" if state.chaos_mode == ChaosMode.DRIFT_V2 else "v1",
        "deployments": list(state.deployments.values()),
        "recent_requests": state.request_log[-12:],
    }


@app.post("/chaos/mode")
async def set_chaos_mode(body: ChaosToggleRequest) -> dict[str, str]:
    """Toggle chaos injection mode at runtime."""
    state.chaos_mode = body.mode
    _record_request("POST", "/chaos/mode", 200, f"chaos_mode={body.mode.value}")
    return {"chaos_mode": state.chaos_mode.value}


@app.post("/reset")
async def reset_service() -> dict[str, str]:
    """Reset target deployments and chaos mode for a clean demo run."""
    state.reset()
    return {"status": "reset", "chaos_mode": state.chaos_mode.value}


@app.post("/v1/deployments")
async def create_deployment_v1(
    req: DeploymentV1Request, response: Response
) -> JSONResponse:
    """Create deployment using v1 schema; simulates silent 202 drop or v2 drift when enabled."""
    if state.chaos_mode == ChaosMode.DRIFT_V2:
        _record_request(
            "POST", "/v1/deployments", 422, "rejected: schema drifted to v2"
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": "API_CONTRACT_DRIFT",
                "detail": (
                    "v1 endpoint deprecated after service upgrade. Use POST /v2/deployments with "
                    "fields: callback_uri (was webhook_url), max_rps (was rate_limit), and env_tier."
                ),
                "openapi_url": "/openapi.json",
            },
        )

    if req.idempotency_key in state.idempotency_index:
        dep_id = state.idempotency_index[req.idempotency_key]
        existing = state.deployments[dep_id]
        if existing.get("active"):
            _record_request("POST", "/v1/deployments", 200, f"idempotent hit {dep_id}")
            return JSONResponse(status_code=200, content=existing)

    if state.chaos_mode == ChaosMode.SILENT_DROP_202:
        attempts = state.dropped_attempts.get(req.idempotency_key, 0) + 1
        state.dropped_attempts[req.idempotency_key] = attempts
        if attempts == 1:
            dep_id = f"dep-{req.idempotency_key[:10]}"
            state.idempotency_index[req.idempotency_key] = dep_id
            state.deployments[dep_id] = {
                "deployment_id": dep_id,
                "service_name": req.service_name,
                "branch": req.branch,
                "commit_sha": req.commit_sha,
                "callback_uri": req.webhook_url,
                "max_rps": req.rate_limit,
                "env_tier": "staging",
                "active": False,
                "status": "dropped_unverified",
                "api_version": "v1",
                "idempotency_key": req.idempotency_key,
                "updated_at": utc_now().isoformat(),
            }
            _record_request("POST", "/v1/deployments", 202, f"202 SILENT DROP {dep_id}")
            return JSONResponse(
                status_code=202,
                content={
                    "deployment_id": dep_id,
                    "status": "queued",
                    "message": "Accepted for async rollout",
                },
            )

    dep_id = (
        state.idempotency_index.get(req.idempotency_key)
        or f"dep-{req.idempotency_key[:10]}"
    )
    state.idempotency_index[req.idempotency_key] = dep_id
    record = {
        "deployment_id": dep_id,
        "service_name": req.service_name,
        "branch": req.branch,
        "commit_sha": req.commit_sha,
        "callback_uri": req.webhook_url,
        "max_rps": req.rate_limit,
        "env_tier": "staging",
        "active": True,
        "status": "active",
        "api_version": "v1",
        "idempotency_key": req.idempotency_key,
        "updated_at": utc_now().isoformat(),
    }
    state.deployments[dep_id] = record
    _record_request("POST", "/v1/deployments", 201, f"deployed {dep_id} (active)")
    return JSONResponse(status_code=201, content=record)


@app.post("/v2/deployments")
async def create_deployment_v2(req: DeploymentV2Request) -> JSONResponse:
    """Create deployment using drifted v2 contract (callback_uri, max_rps, env_tier)."""
    if req.idempotency_key in state.idempotency_index:
        dep_id = state.idempotency_index[req.idempotency_key]
        existing = state.deployments[dep_id]
        if existing.get("active"):
            _record_request("POST", "/v2/deployments", 200, f"idempotent hit {dep_id}")
            return JSONResponse(status_code=200, content=existing)

    dep_id = (
        state.idempotency_index.get(req.idempotency_key)
        or f"dep-{req.idempotency_key[:10]}"
    )
    state.idempotency_index[req.idempotency_key] = dep_id
    record = {
        "deployment_id": dep_id,
        "service_name": req.service_name,
        "branch": req.branch,
        "commit_sha": req.commit_sha,
        "callback_uri": req.callback_uri,
        "max_rps": req.max_rps,
        "env_tier": req.env_tier,
        "active": True,
        "status": "active",
        "api_version": "v2",
        "idempotency_key": req.idempotency_key,
        "updated_at": utc_now().isoformat(),
    }
    state.deployments[dep_id] = record
    _record_request("POST", "/v2/deployments", 201, f"deployed v2 {dep_id} (active)")
    return JSONResponse(status_code=201, content=record)


@app.get("/verify/{deployment_id}")
async def verify_deployment(deployment_id: str) -> dict[str, Any]:
    """Independent verification probe checking whether deployment actually took effect."""
    record = state.deployments.get(deployment_id)
    if record is None:
        _record_request("GET", f"/verify/{deployment_id}", 404, "probe: not_found")
        raise HTTPException(status_code=404, detail="deployment not found")

    active = bool(record.get("active"))
    _record_request(
        "GET",
        f"/verify/{deployment_id}",
        200,
        f"probe: active={active} status={record.get('status')}",
    )
    return {
        "deployment_id": deployment_id,
        "exists": True,
        "active": active,
        "status": record.get("status", "unknown"),
        "api_version": record.get("api_version", "v1"),
        "config": {
            "branch": record.get("branch"),
            "callback_uri": record.get("callback_uri"),
            "max_rps": record.get("max_rps"),
            "env_tier": record.get("env_tier"),
        },
    }


@app.delete("/deployments/{deployment_id}")
async def rollback_deployment(deployment_id: str, request: Request) -> dict[str, Any]:
    """Compensating rollback endpoint removing or deactivating a deployment."""
    record = state.deployments.pop(deployment_id, None)
    if record is None:
        _record_request(
            "DELETE", f"/deployments/{deployment_id}", 200, "already absent"
        )
        return {
            "deployment_id": deployment_id,
            "rolled_back": True,
            "was_present": False,
        }
    state.idempotency_index.pop(record.get("idempotency_key", ""), None)
    _record_request(
        "DELETE", f"/deployments/{deployment_id}", 200, f"rolled back {deployment_id}"
    )
    return {"deployment_id": deployment_id, "rolled_back": True, "was_present": True}


def run_target_service() -> None:
    """Entrypoint for running the standalone Target Deployment Service."""
    import uvicorn

    from mongodb_hackathon.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "mongodb_hackathon.target_service:app",
        host=settings.server_host,
        port=settings.target_service_port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="info",
    )


if __name__ == "__main__":
    run_target_service()
