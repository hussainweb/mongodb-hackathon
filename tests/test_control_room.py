"""Control Room FastAPI endpoint tests backed by Atlas and ASGI target microservice."""

from __future__ import annotations

import httpx
import pytest

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import RunStatus
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.target_service import state as target_state

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_control_room_run_lifecycle_and_memory_invalidation() -> None:
    """Verify run creation, snapshot inspection, chaos toggles, approval, and memory invalidation."""
    target_state.reset()
    created_run_id = ""
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as tc:
            ctrl_mod.app.state._external_store = True
            ctrl_mod.app.state.store = store
            gh_cfg = Settings()
            gh_cfg.github_sandbox_repo = "dry-run/finishline-demo-sandbox"
            ctrl_mod.app.state.settings = gh_cfg
            ctrl_mod.app.state.github = GitHubSandboxAdapter(gh_cfg, token="")
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                r_home = await ac.get("/")
                assert r_home.status_code == 200
                assert "FinishLine" in r_home.text

                r_chaos = await ac.post("/chaos/drift_v2")
                assert r_chaos.status_code == 200
                assert r_chaos.json()["chaos_mode"] == "drift_v2"

                r_create = await ac.post(
                    "/runs",
                    json={
                        "repo": "dry-run/finishline-demo-sandbox",
                        "issue_number": 9,
                        "issue_title": "Test control room run",
                        "issue_body": "Exercise create + snapshot + approve.",
                        "auto_spawn": False,
                    },
                )
                assert r_create.status_code == 201
                created_run_id = r_create.json()["run_id"]

                r_snap = await ac.get(f"/api/runs/{created_run_id}")
                assert r_snap.status_code == 200
                assert r_snap.json()["run"]["status"] == RunStatus.RUNNING.value

                r_approve = await ac.post(
                    f"/runs/{created_run_id}/approve",
                    json={"note": "Canary green"},
                )
                assert r_approve.status_code == 200
                assert r_approve.json()["run"]["approval_granted"] is True

                r_mem = await ac.get("/api/memories")
                memories = r_mem.json()["memories"]
                if memories:
                    mem_id = memories[0]["memory_id"]
                    r_inv = await ac.post(f"/memories/{mem_id}/invalidate")
                    assert r_inv.status_code == 200
                    assert r_inv.json()["status"] == "invalidated"
                    r_res = await ac.post(f"/memories/{mem_id}/invalidate?restore=true")
                    assert r_res.status_code == 200
                    assert r_res.json()["status"] == "active"
    finally:
        if created_run_id:
            await store.runs.delete_many({"run_id": created_run_id})
            await store.checkpoints.delete_many({"run_id": created_run_id})
            await store.events.delete_many({"run_id": created_run_id})
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()
