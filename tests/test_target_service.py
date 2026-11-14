"""Tests for the chaos-capable FastAPI target deployment microservice."""

from __future__ import annotations

import httpx
import pytest

from mongodb_hackathon.target_service import app, state


@pytest.fixture(autouse=True)
def _reset_target_state() -> None:
    state.reset()


@pytest.mark.asyncio
async def test_silent_drop_202_and_retry_verification() -> None:
    """First attempt returns 202 without activating; probe catches it; retry commits."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test-target"
    ) as client:
        toggle = await client.post("/chaos/mode", json={"mode": "silent_drop_202"})
        assert toggle.status_code == 200

        payload = {
            "service_name": "payments-webhook",
            "branch": "fix-1",
            "commit_sha": "abc1234",
            "webhook_url": "https://hooks.example.internal/v1/ingest",
            "rate_limit": 300,
            "idempotency_key": "test-silent-drop-1",
        }
        r1 = await client.post("/v1/deployments", json=payload)
        assert r1.status_code == 202
        dep_id = r1.json()["deployment_id"]

        probe1 = await client.get(f"/verify/{dep_id}")
        assert probe1.status_code == 200
        assert probe1.json()["active"] is False

        r2 = await client.post("/v1/deployments", json=payload)
        assert r2.status_code == 201
        assert r2.json()["deployment_id"] == dep_id

        probe2 = await client.get(f"/verify/{dep_id}")
        assert probe2.status_code == 200
        assert probe2.json()["active"] is True


@pytest.mark.asyncio
async def test_drift_v2_rejects_v1_and_accepts_v2() -> None:
    """When chaos=drift_v2, /v1 returns 422 while /v2 succeeds and verifies."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test-target"
    ) as client:
        await client.post("/chaos/mode", json={"mode": "drift_v2"})

        v1_resp = await client.post(
            "/v1/deployments",
            json={
                "service_name": "payments-webhook",
                "branch": "fix-1",
                "commit_sha": "abc1234",
                "webhook_url": "https://hooks.example.internal/v1/ingest",
                "rate_limit": 300,
                "idempotency_key": "test-drift-1",
            },
        )
        assert v1_resp.status_code == 422

        v2_resp = await client.post(
            "/v2/deployments",
            json={
                "service_name": "payments-webhook",
                "branch": "fix-1",
                "commit_sha": "abc1234",
                "callback_uri": "https://hooks.example.internal/v2/ingest",
                "max_rps": 300,
                "env_tier": "staging",
                "idempotency_key": "test-drift-1",
            },
        )
        assert v2_resp.status_code == 201
        dep_id = v2_resp.json()["deployment_id"]

        probe = await client.get(f"/verify/{dep_id}")
        assert probe.json()["active"] is True
        assert probe.json()["api_version"] == "v2"

        deleted = await client.delete(f"/deployments/{dep_id}")
        assert deleted.status_code == 200
        assert (await client.get(f"/verify/{dep_id}")).status_code == 404
