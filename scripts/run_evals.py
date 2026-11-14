"""Track 3 evaluation suite verifying silent-drop probes, v2 drift adaptation, and crash resume."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx

from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import JobRun, RunStatus, StepCheckpoint, StepStatus
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.target_service import state as target_state
from mongodb_hackathon.worker import execute_job


def _dry_github() -> GitHubSandboxAdapter:
    cfg = Settings()
    cfg.github_sandbox_repo = "dry-run/finishline-demo-sandbox"
    return GitHubSandboxAdapter(cfg, token="")


async def _eval_silent_drop(store: MongoStore) -> dict[str, Any]:
    target_state.reset()
    run_id = f"eval-202-{uuid.uuid4().hex[:6]}"
    await store.create_run(
        JobRun(
            run_id=run_id,
            repo="dry-run/finishline-demo-sandbox",
            issue_number=101,
            issue_title="Silent 202 acceptance probe",
            issue_body="Catch optimistic 202 lie via GET /verify/{id}.",
            target_service_url="http://eval-target",
        )
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://eval-target"
        ) as client:
            await client.post("/chaos/mode", json={"mode": "silent_drop_202"})
            run = await execute_job(
                run_id=run_id,
                store=store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
        events = await store.list_events(run_id, limit=40)
        caught = any(e.event_type == "probe_mismatch" for e in events)
        cps = {c.step_key: c for c in await store.get_checkpoints(run_id)}
        passed = (
            run.status == RunStatus.COMPLETED
            and caught
            and cps["step_3_deploy_and_verify"].took_effect
        )
        return {
            "scenario": "silent_drop_202",
            "passed": passed,
            "attempts": cps["step_3_deploy_and_verify"].attempts,
        }
    finally:
        await store.runs.delete_many({"run_id": run_id})
        await store.checkpoints.delete_many({"run_id": run_id})
        await store.events.delete_many({"run_id": run_id})
        target_state.reset()


async def _eval_drift_v2(store: MongoStore) -> dict[str, Any]:
    target_state.reset()
    run_id = f"eval-v2-{uuid.uuid4().hex[:6]}"
    await store.create_run(
        JobRun(
            run_id=run_id,
            repo="dry-run/finishline-demo-sandbox",
            issue_number=102,
            issue_title="Schema drift v1->v2 adaptation",
            issue_body="Adapt 422 rejection to /v2/deployments via OpenAPI + Atlas playbooks.",
            target_service_url="http://eval-target",
        )
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://eval-target"
        ) as client:
            await client.post("/chaos/mode", json={"mode": "drift_v2"})
            run = await execute_job(
                run_id=run_id,
                store=store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
        cps = {c.step_key: c for c in await store.get_checkpoints(run_id)}
        cp3 = cps["step_3_deploy_and_verify"]
        passed = (
            run.status == RunStatus.COMPLETED
            and cp3.took_effect
            and cp3.probe_result.get("api_version") == "v2"
        )
        return {
            "scenario": "drift_v2",
            "passed": passed,
            "adaptation": cp3.adaptation_used,
        }
    finally:
        await store.runs.delete_many({"run_id": run_id})
        await store.checkpoints.delete_many({"run_id": run_id})
        await store.events.delete_many({"run_id": run_id})
        target_state.reset()


async def _eval_crash_resume(store: MongoStore) -> dict[str, Any]:
    target_state.reset()
    run_id = f"eval-crash-{uuid.uuid4().hex[:6]}"
    await store.create_run(
        JobRun(
            run_id=run_id,
            repo="dry-run/finishline-demo-sandbox",
            issue_number=103,
            issue_title="Crash resume without duplicate writes",
            issue_body="Skip completed checkpoint steps.",
            target_service_url="http://eval-target",
            status=RunStatus.CRASHED,
            current_step=1,
        )
    )
    await store.upsert_checkpoint_atomic(
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
                    "patch_content": "{}\n",
                    "commit_message": "fix: eval",
                    "pr_title": "Eval PR",
                    "pr_body": "Eval Body",
                    "deployment_config": {"service_name": "eval", "rate_limit": 200},
                }
            },
        ),
        run_step=1,
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://eval-target"
        ) as client:
            run = await execute_job(
                run_id=run_id,
                store=store,
                github=_dry_github(),
                target_client=client,
                step_delay=0.0,
            )
        cps = {c.step_key: c for c in await store.get_checkpoints(run_id)}
        passed = run.status == RunStatus.COMPLETED and cps["step_1_plan"].attempts == 1
        return {"scenario": "crash_resume_no_duplicates", "passed": passed}
    finally:
        await store.runs.delete_many({"run_id": run_id})
        await store.checkpoints.delete_many({"run_id": run_id})
        await store.events.delete_many({"run_id": run_id})
        target_state.reset()


async def main() -> None:
    """Execute Track 3 evaluation benchmarks against Atlas + Target Service."""
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()
    try:
        results = [
            await _eval_silent_drop(store),
            await _eval_drift_v2(store),
            await _eval_crash_resume(store),
        ]
    finally:
        await store.close()

    score = sum(1 for r in results if r["passed"]) / len(results)
    print(json.dumps({"pass_rate": score, "results": results}, indent=2))
    if score < 1.0:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
