"""Integration tests for demo pacing presets, step-by-step mode, and Step 1 FixPlan edit/re-plan."""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import (
    PACING_PRESETS,
    FixPlan,
    JobRun,
    RunStatus,
    StepStatus,
)
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.target_service import state as target_state
from mongodb_hackathon.worker import execute_job


async def _cleanup_run(store: MongoStore, run_id: str) -> None:
    """Clean up only documents created by this test run."""
    await store.runs.delete_many({"run_id": run_id})
    await store.checkpoints.delete_many({"run_id": run_id})
    await store.events.delete_many({"run_id": run_id})
    await store.memories.delete_many({"memory_id": f"learned-{run_id}"})


def _dry_github() -> GitHubSandboxAdapter:
    cfg = Settings()
    cfg.github_sandbox_repo = "dry-run/finishline-demo-sandbox"
    return GitHubSandboxAdapter(settings=cfg, token="")


def test_pacing_presets_and_defaults() -> None:
    """Verify default pacing is Demo (0.5s) and all supported presets exist."""
    req = ctrl_mod.StartRunRequest()
    assert req.step_delay == 0.5
    assert req.step_mode == "auto"

    assert PACING_PRESETS["fast"] == 0.1
    assert PACING_PRESETS["demo"] == 0.5
    assert PACING_PRESETS["slow"] == 2.5

    run = JobRun(
        run_id="test-pacing",
        repo="dry-run/demo",
        issue_number=1,
        issue_title="Pacing check",
        issue_body="Validate defaults",
        target_service_url="http://test",
    )
    assert run.step_mode == "auto"
    assert run.step_paused is False
    assert run.paused_after_step == 0


@pytest.mark.asyncio
async def test_step_by_step_pauses_at_checkpoints_and_advances() -> None:
    """Verify that step_by_step mode pauses cleanly after steps 1, 2, and 3, and advances upon operator request."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    try:
        await store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=1,
                issue_title="Step-by-step test run",
                issue_body="Verify pause and advance after checkpoints.",
                target_service_url="http://test-target",
                step_mode="step_by_step",
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
            ctrl_mod.app.state.github = _dry_github()
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                # Spawn job in background
                worker_task = asyncio.create_task(
                    execute_job(
                        run_id=run_id,
                        store=store,
                        github=_dry_github(),
                        target_client=tc,
                        step_delay=0.0,
                    )
                )

                # 1. Wait for pause after Step 1
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 1:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 1")

                cps = {cp.step_key: cp for cp in await store.get_checkpoints(run_id)}
                assert "step_1_plan" in cps
                assert cps["step_1_plan"].status == StepStatus.VERIFIED_TOOK_EFFECT
                assert "step_2_github_patch" not in cps

                # Advance past Step 1
                r_adv1 = await ac.post(f"/runs/{run_id}/advance")
                assert r_adv1.status_code == 200
                assert r_adv1.json()["step_paused"] is False

                # 2. Wait for pause after Step 2
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 2:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 2")

                cps = {cp.step_key: cp for cp in await store.get_checkpoints(run_id)}
                assert "step_2_github_patch" in cps
                assert cps["step_2_github_patch"].status == StepStatus.VERIFIED_TOOK_EFFECT
                assert "step_3_deploy_and_verify" not in cps

                # Advance past Step 2
                r_adv2 = await ac.post(f"/runs/{run_id}/advance")
                assert r_adv2.status_code == 200
                assert r_adv2.json()["step_paused"] is False

                # 3. Wait for pause after Step 3
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 3:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 3")

                cps = {cp.step_key: cp for cp in await store.get_checkpoints(run_id)}
                assert "step_3_deploy_and_verify" in cps
                assert cps["step_3_deploy_and_verify"].status == StepStatus.VERIFIED_TOOK_EFFECT

                # Advance past Step 3 to let worker complete Steps 4 and 5
                r_adv3 = await ac.post(f"/runs/{run_id}/advance")
                assert r_adv3.status_code == 200

                final_run = await asyncio.wait_for(worker_task, timeout=10.0)
                assert final_run.status == RunStatus.COMPLETED

                all_cps = await store.get_checkpoints(run_id)
                assert len(all_cps) == 5
                assert all(cp.status == StepStatus.VERIFIED_TOOK_EFFECT for cp in all_cps)
    finally:
        await _cleanup_run(store, run_id)
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.asyncio
async def test_step_1_fix_plan_edit_takes_effect_on_step_2_and_3() -> None:
    """Verify operator editing FixPlan fields while paused after Step 1 propagates to Step 2 and 3."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    try:
        await store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=1,
                issue_title="Edit FixPlan test",
                issue_body="Verify operator edits take effect in Step 2 and 3.",
                target_service_url="http://test-target",
                step_mode="step_by_step",
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
            ctrl_mod.app.state.github = _dry_github()
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                worker_task = asyncio.create_task(
                    execute_job(
                        run_id=run_id,
                        store=store,
                        github=_dry_github(),
                        target_client=tc,
                        step_delay=0.0,
                    )
                )

                # Wait until paused after Step 1
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 1:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 1")

                # Verify default FixPlan from step_1_plan checkpoint
                cp1 = await store.get_checkpoint(run_id, "step_1_plan")
                assert cp1 is not None
                initial_plan = FixPlan.model_validate(cp1.post_state["fix_plan"])
                assert bool(initial_plan.patch_filename)

                # Operator edits FixPlan fields: change patch_filename, commit_message, and deployment_config
                custom_patch_file = "custom_operator_config.json"
                assert initial_plan.patch_filename != custom_patch_file
                custom_commit_msg = "feat(operator): customized release configuration"
                custom_service_name = "payments-operator-override"
                custom_rate_limit = 450

                r_edit = await ac.post(
                    f"/runs/{run_id}/plan",
                    json={
                        "fix_plan": {
                            "patch_filename": custom_patch_file,
                            "commit_message": custom_commit_msg,
                            "deployment_config": {
                                "service_name": custom_service_name,
                                "rate_limit": custom_rate_limit,
                            },
                        }
                    },
                )
                assert r_edit.status_code == 200
                edited_resp = r_edit.json()["fix_plan"]
                assert edited_resp["patch_filename"] == custom_patch_file
                assert edited_resp["commit_message"] == custom_commit_msg
                assert edited_resp["deployment_config"]["service_name"] == custom_service_name
                assert edited_resp["deployment_config"]["rate_limit"] == custom_rate_limit

                # Advance past Step 1
                await ac.post(f"/runs/{run_id}/advance")

                # Wait until paused after Step 2
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 2:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 2")

                # Verify Step 2 committed the operator's customized file!
                cp2 = await store.get_checkpoint(run_id, "step_2_github_patch")
                assert cp2 is not None
                commit_info = cp2.post_state.get("commit", {})
                assert commit_info.get("path") == custom_patch_file

                # Advance past Step 2
                await ac.post(f"/runs/{run_id}/advance")

                # Wait until paused after Step 3
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 3:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 3")

                # Verify Step 3 deployed with operator's customized deployment_config!
                cp3 = await store.get_checkpoint(run_id, "step_3_deploy_and_verify")
                assert cp3 is not None
                assert cp3.sent_payload.get("service_name") == custom_service_name
                assert cp3.sent_payload.get("rate_limit") == custom_rate_limit

                # Advance past Step 3 to let worker complete
                await ac.post(f"/runs/{run_id}/advance")
                final_run = await asyncio.wait_for(worker_task, timeout=10.0)
                assert final_run.status == RunStatus.COMPLETED
    finally:
        await _cleanup_run(store, run_id)
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.asyncio
async def test_replan_prompt_and_plan_edit_guards() -> None:
    """Verify replan_prompt re-evaluates FixPlan and endpoint enforces pause / step-1 guards."""
    target_state.reset()
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()

    try:
        await store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=2,
                issue_title="Replan guard test",
                issue_body="Verify replan_prompt and guardrails.",
                target_service_url="http://test-target",
                step_mode="step_by_step",
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
            ctrl_mod.app.state.github = _dry_github()
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                # Guard 1: Cannot edit plan before Step 1 has run
                r_pre = await ac.post(
                    f"/runs/{run_id}/plan",
                    json={"replan_prompt": "Try now"},
                )
                assert r_pre.status_code == 400

                worker_task = asyncio.create_task(
                    execute_job(
                        run_id=run_id,
                        store=store,
                        github=_dry_github(),
                        target_client=tc,
                        step_delay=0.0,
                    )
                )

                # Wait for Step 1 pause
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 1:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 1")

                # Test replan_prompt while paused
                r_replan = await ac.post(
                    f"/runs/{run_id}/plan",
                    json={"replan_prompt": "Replan for critical burst traffic rate_limit=300"},
                )
                assert r_replan.status_code == 200
                new_plan = r_replan.json()["fix_plan"]
                assert new_plan["deployment_config"]["rate_limit"] == 300

                # Advance past Step 1
                await ac.post(f"/runs/{run_id}/advance")

                # Wait for Step 2 pause
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 2:
                        break
                else:
                    pytest.fail("Worker did not pause after Step 2")

                # Guard 2: Cannot edit plan after Step 2 has executed
                r_post_step2 = await ac.post(
                    f"/runs/{run_id}/plan",
                    json={"fix_plan": {"commit_message": "too late"}},
                )
                assert r_post_step2.status_code == 400

                # Advance remaining steps
                await ac.post(f"/runs/{run_id}/advance")
                for _ in range(50):
                    await asyncio.sleep(0.1)
                    r = await store.get_run(run_id)
                    if r and r.step_paused and r.paused_after_step == 3:
                        break
                await ac.post(f"/runs/{run_id}/advance")

                final_run = await asyncio.wait_for(worker_task, timeout=10.0)
                assert final_run.status == RunStatus.COMPLETED
    finally:
        await _cleanup_run(store, run_id)
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
        target_state.reset()


@pytest.mark.asyncio
async def test_advance_handles_crashed_status() -> None:
    """Verify /runs/{run_id}/advance unpauses and sets status back to RUNNING if marked CRASHED."""
    run_id = f"tst-{uuid.uuid4().hex[:8]}"
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()
    try:
        await store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/finishline-demo-sandbox",
                issue_number=1,
                issue_title="Crashed advance test",
                issue_body="Verify advance handling of crashed state.",
                target_service_url="http://test-target",
                status=RunStatus.CRASHED,
                step_mode="step_by_step",
                step_paused=True,
                paused_after_step=1,
                worker_pid=None,
            )
        )

        ctrl_mod.app.state._external_store = True
        ctrl_mod.app.state.store = store
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ctrl_mod.app),
            base_url="http://test-control",
        ) as ac:
            r = await ac.post(f"/runs/{run_id}/advance")
            assert r.status_code == 200
            data = r.json()
            assert data["step_paused"] is False

        updated = await store.get_run(run_id)
        assert updated is not None
        assert updated.step_paused is False
    finally:
        await _cleanup_run(store, run_id)
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")
        await store.close()
