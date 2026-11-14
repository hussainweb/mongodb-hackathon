"""Tests for standalone pages (/, /infra, /store), static assets, and active run API."""

from __future__ import annotations

import uuid

import httpx
import pytest

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import (
    ChaosMode,
    JobRun,
    RunStatus,
    StepCheckpoint,
    StepStatus,
)
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.target_service import state as target_state


@pytest.mark.asyncio
async def test_static_assets_serve_correctly() -> None:
    """Verify styles.css and live-run.js return 200 with appropriate content types."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ctrl_mod.app),
        base_url="http://test-control",
    ) as ac:
        r_css = await ac.get("/static/styles.css")
        assert r_css.status_code == 200
        assert "text/css" in r_css.headers.get("content-type", "")
        assert "--mongo: #00684a;" in r_css.text
        assert "--bg: #fafafa;" in r_css.text
        assert ".live-run-strip" in r_css.text

        r_js = await ac.get("/static/live-run.js")
        assert r_js.status_code == 200
        assert "FinishLineLiveRun" in r_js.text
        assert "connectLiveRun" in r_js.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_standalone_pages_and_navigation() -> None:
    """Verify /, /infra, and /store return 200 and render top navigation with open-in-new-tab links."""
    target_state.reset()
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    suffix = uuid.uuid4().hex[:8]
    test_run_id = f"tst-page-{suffix}"

    try:
        await store.create_run(
            JobRun(
                run_id=test_run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=42,
                issue_title="Test multi-page layout",
                issue_body="Layout verification",
                target_service_url="http://test-target",
                status=RunStatus.RUNNING,
                current_step=2,
                step_paused=True,
            )
        )

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
                # 1. Workspace page (GET /)
                r_home = await ac.get("/")
                assert r_home.status_code == 200
                assert "FinishLine" in r_home.text
                assert 'href="/infra"' in r_home.text
                assert 'href="/store"' in r_home.text
                # Check for open-in-new-tab indicator ↗
                assert 'target="_blank"' in r_home.text
                assert "↗" in r_home.text
                assert "live-run-strip" in r_home.text
                assert test_run_id in r_home.text

                # Workspace prompt-first UI elements
                assert 'id="prompt-input"' in r_home.text
                assert 'id="repo-select"' in r_home.text
                assert 'id="pacing-control"' in r_home.text
                assert "Demo 0.5s" in r_home.text
                assert "Step-by-Step" in r_home.text
                assert "Fast 0.1s" in r_home.text
                assert "Slow 2.5s" in r_home.text
                assert "Run Release Closer" in r_home.text

                # Timeline, Breakpoints & Actions
                assert 'id="step-list"' in r_home.text
                assert 'id="pause-banner"' in r_home.text
                assert 'id="plan-review-drawer"' in r_home.text
                assert 'id="plan-patch-filename"' in r_home.text
                assert 'id="approval-banner"' in r_home.text

                # Binding decision: no chaos toggles or raw firehoses on GET /
                assert "Target Chaos Mode" not in r_home.text
                assert "silent_drop_202" not in r_home.text
                assert "drift_v2" not in r_home.text
                assert "/chaos/" not in r_home.text

                # 2. Infrastructure page (GET /infra)
                r_infra = await ac.get("/infra")
                assert r_infra.status_code == 200
                assert "Target Infrastructure Control" in r_infra.text
                assert "live-run-strip" in r_infra.text
                assert "Downstream Fault Injection Mode" in r_infra.text
                assert "Silent 202" in r_infra.text
                assert "Drift v2" in r_infra.text
                assert "Approval Gate" in r_infra.text
                assert "Before Step 3" in r_infra.text
                assert "Before Step 4" in r_infra.text
                assert "Reset Target to Normal" in r_infra.text
                assert "deployments-table" in r_infra.text
                assert "Active" in r_infra.text
                assert "Status" in r_infra.text
                assert "Target OpenAPI &amp; Contract Drift Inspector" in r_infra.text
                assert "callback_uri" in r_infra.text
                assert "max_rps" in r_infra.text
                assert "env_tier" in r_infra.text
                assert "Target Wire Log" in r_infra.text
                assert "requests-feed" in r_infra.text
                assert test_run_id in r_infra.text

                # 3. MongoDB Store page (GET /store)
                r_store = await ac.get("/store")
                assert r_store.status_code == 200
                assert "MongoDB Atlas Store" in r_store.text
                assert "badge-mongo" in r_store.text
                assert "Atlas Cluster0 · MongoDB 9.0.7" in r_store.text
                assert "MongoDB Atlas Data Explorer Filters" in r_store.text
                assert 'id="filter-run-query"' in r_store.text
                assert 'id="filter-cp-query"' in r_store.text
                assert 'id="filter-ev-query"' in r_store.text
                assert 'id="filter-mem-query"' in r_store.text
                assert "$jsonSchema validated" in r_store.text
                assert 'id="run-selector"' in r_store.text
                assert 'id="checkpoints-table"' in r_store.text
                assert 'id="store-events-feed"' in r_store.text
                assert 'id="memory-repo-filter"' in r_store.text
                assert 'id="add-memory-form"' in r_store.text
                assert "Filter Rules" in r_store.text
                assert "Open in Workspace ↗" in r_store.text
                assert "live-run-strip" in r_store.text
                assert test_run_id in r_store.text
    finally:
        await store.runs.delete_many({"run_id": test_run_id})
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_active_run_api_and_sse_stream() -> None:
    """Verify /api/active-run and /api/active-run/stream return live snapshots and track runs."""
    target_state.reset()
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    suffix = uuid.uuid4().hex[:8]
    run_id = f"tst-api-{suffix}"

    try:
        await store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=10,
                issue_title="Active run tracking test",
                issue_body="Tracking active runs",
                target_service_url="http://test-target",
                status=RunStatus.RUNNING,
                current_step=1,
            )
        )
        await store.emit_event(
            run_id,
            "step_1_plan",
            "test_event",
            "Initial active event emitted.",
        )

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
                # Test GET /api/active-run (auto-resolves active running job)
                r_active = await ac.get("/api/active-run")
                assert r_active.status_code == 200
                data = r_active.json()
                assert "run" in data
                assert data["run"]["run_id"] == run_id
                assert data["run"]["status"] == RunStatus.RUNNING.value
                assert "target" in data
                assert "events" in data
                assert any(e["event_type"] == "test_event" for e in data["events"])

                # Test GET /api/active-run?run_id=...
                r_specific = await ac.get(f"/api/active-run?run_id={run_id}")
                assert r_specific.status_code == 200
                assert r_specific.json()["run"]["run_id"] == run_id

                # Test GET /api/active-run for nonexistent run returns empty run
                r_empty = await ac.get("/api/active-run?run_id=nonexistent-run-id")
                assert r_empty.status_code == 200
                assert r_empty.json()["run"] is None

                # Test /api/active-run/stream SSE endpoint and snapshot generation
                from fastapi import Request

                req = Request(scope={"type": "http", "app": ctrl_mod.app, "headers": []})
                resp = await ctrl_mod.stream_active_run_events(req, run_id=run_id)
                assert resp.media_type == "text/event-stream"
                assert resp.headers.get("Cache-Control") == "no-cache"
                assert resp.headers.get("Connection") == "keep-alive"
                first_event = ""
                async for item in resp.body_iterator:
                    first_event = str(item)
                    break
                assert "event: snapshot" in first_event
                assert run_id in first_event
    finally:
        await store.runs.delete_many({"run_id": run_id})
        await store.events.delete_many({"run_id": run_id})
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_workspace_prompt_composer_and_pacing_presets() -> None:
    """Verify GET / renders Linear-inspired prompt composer, repo selector, and demo pacing."""
    target_state.reset()
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
                resp = await ac.get("/")
                assert resp.status_code == 200
                html = resp.text

                # 1. Prompt Composer Card elements
                assert 'id="prompt-input"' in html
                assert 'id="repo-select"' in html
                assert 'id="repo-mode-badge"' in html
                assert 'id="repo-rules-badge"' in html
                assert 'id="btn-toggle-add-repo"' in html
                assert 'id="add-repo-form"' in html
                assert 'id="example-chips"' in html
                assert 'onclick="selectChip(' not in html
                assert 'btn.addEventListener("click"' in html

                # 2. Pacing segmented control with Demo 0.5s active by default
                assert 'id="pacing-control"' in html
                assert 'class="active" data-pacing="demo"' in html
                assert "Demo 0.5s" in html
                assert "Step-by-Step" in html
                assert "Fast 0.1s" in html
                assert "Slow 2.5s" in html
                assert 'id="btn-run-closer"' in html

                # 3. Execution timeline & breakpoint banner
                assert 'id="step-list"' in html
                assert 'id="pause-banner"' in html
                assert 'id="plan-review-drawer"' in html
                assert 'id="btn-advance-step"' in html
                assert 'id="btn-save-plan"' in html
                assert 'id="btn-replan"' in html

                # 4. Human Approval
                assert 'id="approval-banner"' in html
                assert 'id="record-btn"' in html
                assert 'id="briefing-audio"' in html

                # 5. No target chaos controls on GET /
                assert "Target Chaos Mode" not in html
                assert "/chaos/" not in html
                assert "silent_drop_202" not in html
                assert "drift_v2" not in html
    finally:
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_infra_page_api_and_interactions() -> None:
    """Verify /infra OpenAPI inspector, deployments table active badges, and chaos toggles."""
    target_state.reset()
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    # Seed target service state with active and dropped deployments
    target_state.deployments["dep-act-1"] = {
        "deployment_id": "dep-act-1",
        "service_name": "payments-svc",
        "branch": "fix/webhook-resilience",
        "env_tier": "staging",
        "max_rps": 300,
        "api_version": "v1",
        "active": True,
        "status": "active",
    }
    target_state.deployments["dep-drp-2"] = {
        "deployment_id": "dep-drp-2",
        "service_name": "billing-svc",
        "branch": "fix/silent-drop-retry",
        "env_tier": "staging",
        "max_rps": 150,
        "api_version": "v1",
        "active": False,
        "status": "dropped_unverified",
    }
    target_state.request_log.append(
        {
            "ts": "2026-11-14T19:00:00Z",
            "method": "POST",
            "path": "/v1/deployments",
            "status_code": 201,
            "summary": "deployed dep-act-1 (active)",
        }
    )

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as tc:
            ctrl_mod.app.state._external_store = True
            ctrl_mod.app.state.store = store
            gh_cfg = Settings()
            ctrl_mod.app.state.settings = gh_cfg
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                # 1. Test GET /api/target-openapi
                r_api = await ac.get("/api/target-openapi")
                assert r_api.status_code == 200
                api_data = r_api.json()
                assert "openapi" in api_data
                assert "contract_diff" in api_data
                assert api_data["contract_diff"]["v1_endpoint"] == "/v1/deployments"
                assert api_data["contract_diff"]["v2_endpoint"] == "/v2/deployments"
                assert any(
                    c["v2_field"] == "callback_uri"
                    for c in api_data["contract_diff"]["changes"]
                )
                assert any(
                    c["v2_field"] == "max_rps"
                    for c in api_data["contract_diff"]["changes"]
                )
                assert any(
                    c["v2_field"] == "env_tier"
                    for c in api_data["contract_diff"]["changes"]
                )

                # 2. Test GET /infra rendering
                r_infra = await ac.get("/infra")
                assert r_infra.status_code == 200
                html = r_infra.text

                # Verify deployments table with active=true/false and status
                assert "dep-act-1" in html
                assert "dep-drp-2" in html
                assert '<span class="badge badge-ok">true</span>' in html
                assert '<span class="badge badge-danger">false</span>' in html
                assert "dropped_unverified" in html

                # Verify OpenAPI inspector and contract drift
                assert "callback_uri" in html
                assert "max_rps" in html
                assert "env_tier" in html

                # Verify Wire Log
                assert "POST /v1/deployments" in html
                assert "deployed dep-act-1 (active)" in html

                # 3. Test Chaos Toggle and Reset
                r_chaos = await ac.post("/chaos/drift_v2")
                assert r_chaos.status_code == 200
                assert target_state.chaos_mode == ChaosMode.DRIFT_V2

                r_reset = await ac.post("/target/reset")
                assert r_reset.status_code == 200
                assert target_state.chaos_mode == ChaosMode.NORMAL
                assert len(target_state.deployments) == 0
    finally:
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_page_api_and_interactions() -> None:
    """Verify /store Data Explorer filters, checkpoints, service_events, and memory CRUD."""
    target_state.reset()
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    suffix = uuid.uuid4().hex[:8]
    test_run_id = f"tst-store-{suffix}"
    test_repo = f"dry-run/test-repo-{suffix}"
    created_memory_id = ""

    try:
        # Create test run
        await store.create_run(
            JobRun(
                run_id=test_run_id,
                repo=test_repo,
                issue_number=99,
                issue_title="Store verification run",
                issue_body="Testing store page components",
                target_service_url="http://test-target",
                status=RunStatus.RUNNING,
                current_step=1,
            )
        )

        # Upsert atomic $jsonSchema checkpoint
        cp = StepCheckpoint(
            run_id=test_run_id,
            step_key="step_1_plan",
            step_seq=1,
            title="Step 1: Diagnose issue & retrieve experience",
            idempotency_key=f"idem-{test_run_id}-1",
            status=StepStatus.VERIFIED_TOOK_EFFECT,
            attempts=1,
            took_effect=True,
            post_state={"diagnosis": "Found breaking drift v2"},
            probe_result={"status": "confirmed_schema"},
        )
        await store.upsert_checkpoint_atomic(cp)

        # Emit service event
        await store.emit_event(
            test_run_id,
            "step_1_plan",
            "plan_verified",
            "Step 1 plan verified against Atlas vector playbooks",
            {"rule_id": "test-rule-1"},
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as tc:
            ctrl_mod.app.state._external_store = True
            ctrl_mod.app.state.store = store
            gh_cfg = Settings()
            ctrl_mod.app.state.settings = gh_cfg
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                # 1. Test GET /store with run_id and repo query params
                r_store = await ac.get(f"/store?run_id={test_run_id}&repo={test_repo}")
                assert r_store.status_code == 200
                html = r_store.text

                # Prominent Atlas header badges
                assert "Atlas Cluster0 · MongoDB 9.0.7" in html
                assert "job_runs" in html
                assert "step_checkpoints" in html
                assert "service_events" in html
                assert "experience_memories" in html
                assert "demo_repos" in html

                # Atlas Data Explorer filters snippets
                assert f'{{"run_id": "{test_run_id}"}}' in html
                assert f'{{"source_repo": "{test_repo}", "status": "active"}}' in html

                # $jsonSchema validated checkpoints
                assert "$jsonSchema validated" in html
                assert "step_1_plan" in html
                assert f"idem-{test_run_id}-1" in html
                assert "Found breaking drift v2" in html

                # Live service_events tail
                assert "Step 1 plan verified against Atlas vector playbooks" in html

                # 2. Test GET /runs/{run_id} direct endpoint
                r_run = await ac.get(f"/runs/{test_run_id}")
                assert r_run.status_code == 200
                run_snap = r_run.json()
                assert run_snap["run"]["run_id"] == test_run_id
                assert len(run_snap["checkpoints"]) == 1
                assert run_snap["checkpoints"][0]["step_key"] == "step_1_plan"
                assert len(run_snap["events"]) == 1

                # 3. Test Track 2 Memory creation with fix_action
                mem_payload = {
                    "kind": "repo_rule",
                    "source_repo": test_repo,
                    "title": "Enforce canary RPS limit",
                    "content": "Staging canary deployments must not exceed max_rps=100",
                    "fix_action": "Set max_rps=100 and env_tier='canary' in config",
                }
                r_create_mem = await ac.post("/api/memories", json=mem_payload)
                assert r_create_mem.status_code == 201
                created_mem = r_create_mem.json()["memory"]
                created_memory_id = created_mem["memory_id"]
                assert created_mem["source_repo"] == test_repo
                assert created_mem["title"] == "Enforce canary RPS limit"
                assert created_mem["resolution"] == "Set max_rps=100 and env_tier='canary' in config"
                assert created_mem["status"] == "active"

                # 4. Test filtering memories by source_repo
                r_list_mem = await ac.get(
                    f"/api/memories?source_repo={test_repo}&include_global=true"
                )
                assert r_list_mem.status_code == 200
                mem_list = r_list_mem.json()["memories"]
                assert any(m["memory_id"] == created_memory_id for m in mem_list)

                # 5. Test Invalidating memory
                r_inval = await ac.post(
                    f"/memories/{created_memory_id}/invalidate?restore=false"
                )
                assert r_inval.status_code == 200
                assert r_inval.json()["status"] == "invalidated"

                # 6. Test Restoring memory (via json body restore=True)
                r_restore = await ac.post(
                    f"/memories/{created_memory_id}/invalidate",
                    json={"restore": True},
                )
                assert r_restore.status_code == 200
                assert r_restore.json()["status"] == "active"
    finally:
        await store.runs.delete_many({"run_id": test_run_id})
        await store.checkpoints.delete_many({"run_id": test_run_id})
        await store.events.delete_many({"run_id": test_run_id})
        if created_memory_id:
            await store.memories.delete_many({"memory_id": created_memory_id})
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()
