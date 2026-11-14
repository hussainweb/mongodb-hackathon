"""Integration tests for Pydantic AI agents, Atlas checkpoints, chaos recovery, and rollback."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from pydantic_ai.models.test import TestModel

from mongodb_hackathon.agent import adapt_to_schema_drift, plan_release_fix
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
from mongodb_hackathon.worker import AUDIO_DIR, execute_job


async def _cleanup_run(store: MongoStore, run_id: str) -> None:
    await store.runs.delete_many({"run_id": run_id})
    await store.checkpoints.delete_many({"run_id": run_id})
    await store.events.delete_many({"run_id": run_id})
    await store.memories.delete_many({"memory_id": f"learned-{run_id}"})


@pytest_asyncio.fixture
async def atlas_store() -> AsyncGenerator[MongoStore]:
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()
    try:
        yield store
    finally:
        await store.close()


def _dry_github() -> GitHubSandboxAdapter:
    cfg = Settings()
    cfg.github_sandbox_repo = "dry-run/finishline-demo-sandbox"
    return GitHubSandboxAdapter(settings=cfg, token="")


@pytest.mark.asyncio
async def test_pydantic_ai_testmodel_planner_and_drift_adapter() -> None:
    """Verify Pydantic AI structured outputs work cleanly under TestModel."""
    fix = await plan_release_fix(
        issue_number=7,
        issue_title="Add retry backoff to webhook dispatcher",
        issue_body="Prevent 429 drops on /v1/deployments",
        memories=[],
        model_override=TestModel(),
    )
    assert fix.patch_filename
    assert fix.root_cause

    drift = await adapt_to_schema_drift(
        error_detail="422 Unprocessable Entity: expected /v2/deployments",
        openapi_excerpt={"paths": {"/v2/deployments": {}}},
        original_payload={
            "service_name": "svc",
            "branch": "b",
            "commit_sha": "sha",
            "webhook_url": "https://x/y",
            "rate_limit": 200,
            "idempotency_key": "preserve-me",
        },
        playbooks=[],
        model_override=TestModel(),
    )
    assert drift.adapted_payload["idempotency_key"] == "preserve-me"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_catches_silent_202_and_completes(atlas_store: MongoStore) -> None:
    """Worker detects 202 silent drop via /verify probe, retries idempotently, and verifies."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=1,
                issue_title="Fix webhook silent drop",
                issue_body="Ensure delivery verification succeeds.",
                target_service_url="http://test-target",
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            await client.post("/chaos/mode", json={"mode": "silent_drop_202"})
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )

        assert final_run.status == RunStatus.COMPLETED
        cps = {cp.step_key: cp for cp in await atlas_store.get_checkpoints(run_id)}
        assert len(cps) == 5
        assert cps["step_3_deploy_and_verify"].attempts >= 2
        assert cps["step_3_deploy_and_verify"].took_effect is True
        events = await atlas_store.list_events(run_id, limit=50)
        assert any(ev.event_type == "probe_mismatch" for ev in events)
    finally:
        await _cleanup_run(atlas_store, run_id)
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_adapts_to_v2_drift(atlas_store: MongoStore) -> None:
    """Worker detects 422 drift on /v1/deployments, retrieves playbooks, and succeeds on /v2."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=2,
                issue_title="Sync drifted v2 deployment config",
                issue_body="Target moved from webhook_url to callback_uri.",
                target_service_url="http://test-target",
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            await client.post("/chaos/mode", json={"mode": "drift_v2"})
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )

        assert final_run.status == RunStatus.COMPLETED
        cps = {cp.step_key: cp for cp in await atlas_store.get_checkpoints(run_id)}
        cp3 = cps["step_3_deploy_and_verify"]
        assert cp3.took_effect is True
        assert cp3.probe_result.get("api_version") == "v2"
        assert cp3.adaptation_used
        events = await atlas_store.list_events(run_id, limit=50)
        assert any(ev.event_type == "drift_adapted" for ev in events)
    finally:
        await _cleanup_run(atlas_store, run_id)
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_resumes_after_crash_without_duplicate_steps(
    atlas_store: MongoStore,
) -> None:
    """After simulated SIGKILL following Step 2, resumed worker skips steps 1 & 2 cleanly."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=3,
                issue_title="Crash recovery test issue",
                issue_body="Verify idempotent skip on resume.",
                target_service_url="http://test-target",
                status=RunStatus.CRASHED,
                current_step=2,
            )
        )
        await atlas_store.upsert_checkpoint_atomic(
            StepCheckpoint(
                run_id=run_id,
                step_key="step_1_plan",
                step_seq=1,
                title="Plan",
                idempotency_key=f"{run_id}:step_1_plan",
                status=StepStatus.VERIFIED_TOOK_EFFECT,
                attempts=1,
                took_effect=True,
                post_state={
                    "fix_plan": {
                        "root_cause": "pre-planned",
                        "patch_filename": "service_config.json",
                        "patch_content": '{"service_name": "payments-webhook"}\n',
                        "commit_message": "fix: pre-planned",
                        "pr_title": "Fix pre-planned",
                        "pr_body": "Body",
                        "deployment_config": {
                            "service_name": "payments-webhook",
                            "webhook_url": "https://hooks.example.internal/v1/ingest",
                            "rate_limit": 250,
                        },
                    }
                },
            ),
            run_step=1,
        )
        await atlas_store.upsert_checkpoint_atomic(
            StepCheckpoint(
                run_id=run_id,
                step_key="step_2_github_patch",
                step_seq=2,
                title="Patch",
                idempotency_key=f"{run_id}:step_2_github_patch",
                status=StepStatus.VERIFIED_TOOK_EFFECT,
                attempts=1,
                took_effect=True,
                external_ref="dry-run://branch",
                post_state={
                    "branch": f"finishline/issue-3-{run_id[:6]}",
                    "commit_sha": "deadbeef1234",
                },
            ),
            run_step=2,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )

        assert final_run.status == RunStatus.COMPLETED
        cps = {cp.step_key: cp for cp in await atlas_store.get_checkpoints(run_id)}
        assert cps["step_1_plan"].attempts == 1
        assert cps["step_2_github_patch"].attempts == 1
        assert cps["step_5_finalize"].took_effect is True
        events = await atlas_store.list_events(run_id, limit=50)
        skipped = [ev for ev in events if ev.event_type == "checkpoint_skipped"]
        assert len(skipped) == 2
    finally:
        await _cleanup_run(atlas_store, run_id)
        target_state.reset()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compensating_rollback_removes_deployment(
    atlas_store: MongoStore,
) -> None:
    """Setting halt_requested=True executes Track 1 compensating rollback cleanly."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=4,
                issue_title="Rollback check",
                issue_body="Ensure deployment is deleted on halt.",
                target_service_url="http://test-target",
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            completed = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
            assert completed.status == RunStatus.COMPLETED
            assert len(target_state.deployments) == 1

            await atlas_store.update_run(run_id, halt_requested=True)
            rolled_back = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
            assert rolled_back.status == RunStatus.ROLLED_BACK
            assert len(target_state.deployments) == 0
    finally:
        await _cleanup_run(atlas_store, run_id)
        target_state.reset()


@pytest.mark.asyncio
async def test_audio_dir_matches_package_static_mount() -> None:
    """Worker AUDIO_DIR must resolve inside src/mongodb_hackathon/static/audio."""
    assert AUDIO_DIR.is_absolute()
    assert AUDIO_DIR.parts[-3:] == ("mongodb_hackathon", "static", "audio")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_approval_gate_and_freeform_issue_zero(
    atlas_store: MongoStore,
) -> None:
    """REQUIRE_APPROVAL_GATE triggers AWAITING_APPROVAL even without 422 drift, and issue_number=0 completes."""
    import asyncio

    target_state.reset()
    target_state.chaos_mode = ChaosMode.REQUIRE_APPROVAL_GATE
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=0,
                issue_title="Free-form staging rollout",
                issue_body="Roll out staging config and pause for operator approval.",
                target_service_url="http://test-target",
            )
        )

        async def _approve_when_waiting() -> None:
            for _ in range(40):
                cur = await atlas_store.get_run(run_id)
                if cur and cur.status == RunStatus.AWAITING_APPROVAL:
                    await atlas_store.update_run(
                        run_id, approval_granted=True, approval_note="Approved in test"
                    )
                    return
                await asyncio.sleep(0.15)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            approver = asyncio.create_task(_approve_when_waiting())
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
            await approver

        assert final_run.status == RunStatus.COMPLETED
        assert len(target_state.deployments) == 1
        events = await atlas_store.list_events(run_id, limit=50)
        assert any(ev.event_type == "awaiting_approval" for ev in events)
        assert any(ev.event_type == "approval_received" for ev in events)
    finally:
        await _cleanup_run(atlas_store, run_id)
        target_state.reset()
