"""Tests for standalone pages (/, /infra, /store), static assets, and active run API."""

from __future__ import annotations

import uuid

import httpx
import pytest

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import JobRun, RunStatus
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
                assert "Target Chaos Mode" in r_infra.text
                assert "silent_drop_202" in r_infra.text
                assert "drift_v2" in r_infra.text
                assert test_run_id in r_infra.text

                # 3. MongoDB Store page (GET /store)
                r_store = await ac.get("/store")
                assert r_store.status_code == 200
                assert "MongoDB Atlas Store" in r_store.text
                assert "badge-mongo" in r_store.text
                assert "Atlas Cluster0" in r_store.text
                assert "live-run-strip" in r_store.text
                assert test_run_id in r_store.text
    finally:
        await store.runs.delete_many({"run_id": test_run_id})
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


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
