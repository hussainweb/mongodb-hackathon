"""Standalone crash-resumable Track 3 worker executing GitHub + Target Service workflows."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

import httpx
from langsmith import trace
from pydantic_ai.models import Model

from mongodb_hackathon.agent import (
    adapt_to_schema_drift,
    configure_observability,
    plan_release_fix,
)
from mongodb_hackathon.config import Settings, get_settings
from mongodb_hackathon.embeddings import embed_text
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import (
    ExperienceMemory,
    FixPlan,
    JobRun,
    RunStatus,
    StepCheckpoint,
    StepStatus,
    utc_now,
)
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.voice import synthesize_briefing

AUDIO_DIR = Path(__file__).resolve().parent / "static" / "audio"


async def _check_halt_or_rollback(
    store: MongoStore,
    github: GitHubSandboxAdapter,
    target_client: httpx.AsyncClient,
    run_id: str,
) -> bool:
    """Check if operator requested halt & compensating rollback via MongoDB."""
    run = await store.get_run(run_id)
    if not run or not run.halt_requested:
        return False

    checkpoints = await store.get_checkpoints(run_id)
    rollback_notes: list[str] = []
    for cp in reversed(checkpoints):
        if cp.status not in {
            StepStatus.VERIFIED_TOOK_EFFECT,
            StepStatus.ADAPTED,
            StepStatus.SENT_UNVERIFIED,
        }:
            continue
        comp = cp.compensating_action
        action_type = comp.get("type")
        if action_type == "delete_deployment" and comp.get("deployment_id"):
            await target_client.delete(f"/deployments/{comp['deployment_id']}")
            rollback_notes.append(f"reverted deployment {comp['deployment_id']}")
        elif action_type == "github_rollback":
            res = await github.rollback_changes(
                repo=run.repo,
                branch_name=str(comp.get("branch_name", "")),
                pr_number=comp.get("pr_number"),
                issue_number=run.issue_number,
                remove_labels=list(comp.get("labels", [])),
            )
            rollback_notes.extend(res.get("actions", []))

        cp.status = StepStatus.ROLLED_BACK
        await store.upsert_checkpoint_atomic(cp)

    await store.update_run(run_id, status=RunStatus.ROLLED_BACK.value, worker_pid=None)
    await store.emit_event(
        run_id,
        "rollback",
        "rolled_back",
        "Executed compensating rollback across GitHub and Target Service.",
        {"actions": rollback_notes},
    )
    return True


async def _wait_for_operator_approval(
    store: MongoStore,
    run_id: str,
    briefing_text: str,
    settings: Settings,
    poll_seconds: float = 0.5,
) -> bool:
    """Pause at policy/human escalation gate with ElevenLabs voice prompt until approved or halted."""
    audio_file = synthesize_briefing(run_id, briefing_text, AUDIO_DIR, settings)
    await store.update_run(
        run_id,
        status=RunStatus.AWAITING_APPROVAL.value,
        voice_briefing_text=briefing_text,
        voice_audio_path=f"/static/audio/{audio_file}" if audio_file else "",
    )
    await store.emit_event(
        run_id,
        "step_3_deploy_and_verify",
        "awaiting_approval",
        briefing_text,
        {"audio_url": f"/static/audio/{audio_file}" if audio_file else ""},
    )

    while True:
        run = await store.get_run(run_id)
        if not run:
            return False
        if run.halt_requested:
            return False
        if run.approval_granted:
            await store.update_run(run_id, status=RunStatus.RUNNING.value)
            await store.emit_event(
                run_id,
                "step_3_deploy_and_verify",
                "approval_received",
                f"Operator approved gate: {run.approval_note or 'approved'}",
            )
            return True
        await asyncio.sleep(poll_seconds)


async def execute_job(
    run_id: str,
    store: MongoStore | None = None,
    github: GitHubSandboxAdapter | None = None,
    target_client: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
    model_override: Model | None = None,
    step_delay: float = 0.8,
) -> JobRun:
    """Run or resume a 5-stage Track 3 job from MongoDB Atlas checkpoints."""
    with trace(
        name="execute_finishline_job", run_type="chain", inputs={"run_id": run_id}
    ):
        return await _execute_job_impl(
            run_id=run_id,
            store=store,
            github=github,
            target_client=target_client,
            settings=settings,
            model_override=model_override,
            step_delay=step_delay,
        )


async def _execute_job_impl(
    run_id: str,
    store: MongoStore | None = None,
    github: GitHubSandboxAdapter | None = None,
    target_client: httpx.AsyncClient | None = None,
    settings: Settings | None = None,
    model_override: Model | None = None,
    step_delay: float = 0.8,
) -> JobRun:
    configure_observability()
    cfg = settings or get_settings()
    own_store = store is None
    db_store = store or MongoStore(cfg)
    gh = github or GitHubSandboxAdapter(cfg)
    own_http = target_client is None
    http = target_client or httpx.AsyncClient(
        base_url=cfg.target_service_url, timeout=15.0
    )

    try:
        run = await db_store.get_run(run_id)
        if run is None:
            raise RuntimeError(f"Run {run_id} not found in MongoDB")

        is_resume = run.current_step > 0 or run.status == RunStatus.CRASHED
        await db_store.update_run(
            run_id,
            status=RunStatus.RUNNING.value,
            worker_pid=os.getpid(),
        )
        await db_store.emit_event(
            run_id,
            "worker",
            "worker_resumed" if is_resume else "worker_started",
            (
                f"Worker PID {os.getpid()} resumed from MongoDB checkpoint step {run.current_step}."
                if is_resume
                else f"Worker PID {os.getpid()} started job for {run.repo}#{run.issue_number}."
            ),
            {"pid": os.getpid(), "resumed": is_resume},
        )

        existing_cps = {
            cp.step_key: cp for cp in await db_store.get_checkpoints(run_id)
        }

        # --- STEP 1: Diagnose & Plan (Atlas Vector Search + Pydantic AI) ---
        cp1 = existing_cps.get("step_1_plan")
        if cp1 and cp1.status == StepStatus.VERIFIED_TOOK_EFFECT:
            fix_plan = FixPlan.model_validate(cp1.post_state["fix_plan"])
            await db_store.emit_event(
                run_id,
                "step_1_plan",
                "checkpoint_skipped",
                "Skipped Step 1 (already verified in MongoDB checkpoint).",
            )
        else:
            cp1 = StepCheckpoint(
                run_id=run_id,
                step_key="step_1_plan",
                step_seq=1,
                title="Diagnose issue & retrieve Vector Search experience",
                idempotency_key=f"{run_id}:step_1_plan",
                attempts=(cp1.attempts + 1) if cp1 else 1,
            )
            memories = await db_store.search_experience(
                f"{run.issue_title}\n{run.issue_body}",
                kind="github_fix",
                limit=3,
            )
            fix_plan = await plan_release_fix(
                issue_number=run.issue_number,
                issue_title=run.issue_title,
                issue_body=run.issue_body,
                memories=memories,
                settings=cfg,
                model_override=model_override,
            )
            cp1.status = StepStatus.VERIFIED_TOOK_EFFECT
            cp1.took_effect = True
            cp1.post_state = {
                "fix_plan": fix_plan.model_dump(mode="json"),
                "recalled_memories": [m.get("title", "") for m in memories],
            }
            await db_store.upsert_checkpoint_atomic(cp1, run_step=1)
            await db_store.emit_event(
                run_id,
                "step_1_plan",
                "step_verified",
                f"Planned patch using {len(memories)} Atlas Vector Search precedents.",
                {"memories": cp1.post_state["recalled_memories"]},
            )

        if step_delay > 0:
            await asyncio.sleep(step_delay)
        if await _check_halt_or_rollback(db_store, gh, http, run_id):
            return await db_store.get_run(run_id) or run

        # --- STEP 2: Create Branch & Commit Patch on GitHub ---
        branch_slug = (
            f"issue-{run.issue_number}" if run.issue_number > 0 else "task"
        )
        branch_name = f"finishline/{branch_slug}-{run_id[:6]}"
        cp2 = existing_cps.get("step_2_github_patch")
        if cp2 and cp2.status == StepStatus.VERIFIED_TOOK_EFFECT:
            commit_sha = str(cp2.post_state.get("commit_sha", "HEAD"))
            await db_store.emit_event(
                run_id,
                "step_2_github_patch",
                "checkpoint_skipped",
                f"Skipped Step 2 (branch {branch_name} already committed & verified).",
            )
        else:
            cp2 = StepCheckpoint(
                run_id=run_id,
                step_key="step_2_github_patch",
                step_seq=2,
                title="Create GitHub branch & commit config patch",
                idempotency_key=f"{run_id}:step_2_github_patch",
                attempts=(cp2.attempts + 1) if cp2 else 1,
            )
            branch_info = await gh.ensure_branch(run.repo, branch_name)
            commit_info = await gh.upsert_file_on_branch(
                repo=run.repo,
                branch_name=branch_name,
                path=fix_plan.patch_filename,
                content=fix_plan.patch_content,
                commit_message=fix_plan.commit_message,
            )
            commit_sha = str(commit_info.get("commit_sha", branch_info["sha"]))
            cp2.status = StepStatus.VERIFIED_TOOK_EFFECT
            cp2.took_effect = True
            cp2.external_ref = str(branch_info["url"])
            cp2.post_state = {
                "branch": branch_name,
                "commit_sha": commit_sha,
                "commit": commit_info,
            }
            cp2.compensating_action = {
                "type": "github_rollback",
                "branch_name": branch_name,
            }
            await db_store.upsert_checkpoint_atomic(cp2, run_step=2)
            await db_store.emit_event(
                run_id,
                "step_2_github_patch",
                "step_verified",
                f"Committed {fix_plan.patch_filename} on GitHub branch {branch_name}.",
                {"branch_url": cp2.external_ref, "commit_sha": commit_sha[:8]},
            )

        if step_delay > 0:
            await asyncio.sleep(step_delay)
        if await _check_halt_or_rollback(db_store, gh, http, run_id):
            return await db_store.get_run(run_id) or run

        # --- STEP 3: Deploy & Independently Verify (catches silent 202 drops & v1->v2 drift) ---
        cp3 = existing_cps.get("step_3_deploy_and_verify")
        if cp3 and cp3.status == StepStatus.VERIFIED_TOOK_EFFECT:
            dep_id = str(cp3.post_state.get("deployment_id", ""))
            verify_data = dict(cp3.probe_result)
            await db_store.emit_event(
                run_id,
                "step_3_deploy_and_verify",
                "checkpoint_skipped",
                f"Skipped Step 3 (deployment {dep_id} already verified active).",
            )
        else:
            idemp_key = f"{run_id}-deploy"
            cp3 = StepCheckpoint(
                run_id=run_id,
                step_key="step_3_deploy_and_verify",
                step_seq=3,
                title="Deploy to target service & verify took-effect",
                idempotency_key=f"{run_id}:step_3_deploy",
                attempts=(cp3.attempts + 1) if cp3 else 1,
            )

            def _coerce_positive_int(value: Any, default: int = 300) -> int:
                if isinstance(value, bool):
                    return default
                if isinstance(value, int):
                    return max(1, min(10000, value))
                match = re.search(r"\d+", str(value))
                if match:
                    return max(1, min(10000, int(match.group(0))))
                return default

            v1_payload: dict[str, Any] = {
                "service_name": str(
                    fix_plan.deployment_config.get("service_name", "payments-webhook")
                ),
                "branch": branch_name,
                "commit_sha": commit_sha,
                "webhook_url": str(
                    fix_plan.deployment_config.get(
                        "webhook_url", "https://hooks.example.internal/v1/ingest"
                    )
                ),
                "rate_limit": _coerce_positive_int(
                    fix_plan.deployment_config.get("rate_limit", 300)
                ),
                "idempotency_key": idemp_key,
            }

            dep_id = ""
            verify_data = {}
            adapted_note = ""
            adapted_endpoint = ""
            adapted_payload: dict[str, Any] | None = None

            # Check operator approval gate up-front when chaos_mode=require_approval_gate
            run_latest = await db_store.get_run(run_id)
            if not (run_latest and run_latest.approval_granted):
                health_resp = await http.get("/health")
                gate_active = (
                    health_resp.json().get("chaos_mode") == "require_approval_gate"
                    if health_resp.status_code == 200
                    else False
                )
                if gate_active:
                    brief = (
                        f"Release {run_id} hit policy approval gate on target service "
                        f"for {v1_payload['service_name']}. Say approve to continue deployment."
                    )
                    approved = await _wait_for_operator_approval(
                        db_store, run_id, brief, cfg
                    )
                    if not approved:
                        await _check_halt_or_rollback(db_store, gh, http, run_id)
                        return await db_store.get_run(run_id) or run

            for attempt in range(1, 5):
                cp3.attempts = attempt
                if adapted_endpoint and adapted_payload is not None:
                    cp3.sent_payload = adapted_payload
                    resp = await http.post(adapted_endpoint, json=adapted_payload)
                else:
                    cp3.sent_payload = v1_payload
                    resp = await http.post("/v1/deployments", json=v1_payload)

                if resp.status_code == 422:
                    # Schema drift detected! Query OpenAPI + Vector Search playbooks and adapt.
                    err_body = resp.text
                    cp3.status = StepStatus.DRIFTED
                    cp3.error_message = err_body[:400]
                    await db_store.upsert_checkpoint_atomic(cp3)
                    await db_store.emit_event(
                        run_id,
                        "step_3_deploy_and_verify",
                        "drift_detected",
                        "Target rejected /v1/deployments (422). Querying Atlas Vector Search playbooks...",
                        {"status_code": 422},
                    )

                    openapi_resp = await http.get("/openapi.json")
                    openapi_json = (
                        openapi_resp.json() if openapi_resp.status_code == 200 else {}
                    )
                    playbooks = await db_store.search_experience(
                        f"API contract drift 422 {err_body}",
                        kind="drift_playbook",
                        limit=3,
                    )
                    adapt_plan = await adapt_to_schema_drift(
                        error_detail=err_body,
                        openapi_excerpt=openapi_json,
                        original_payload=v1_payload,
                        playbooks=playbooks,
                        settings=cfg,
                        model_override=model_override,
                    )

                    run_latest = await db_store.get_run(run_id)
                    if not (run_latest and run_latest.approval_granted) and (
                        adapt_plan.needs_human_confirmation
                        or adapt_plan.confidence < 0.75
                    ):
                        brief = (
                            f"Release {run_id} hit API schema drift on target service. "
                            f"Proposed mapping: {json.dumps(adapt_plan.field_mapping)}. "
                            "Say approve to continue deployment."
                        )
                        approved = await _wait_for_operator_approval(
                            db_store, run_id, brief, cfg
                        )
                        if not approved:
                            await _check_halt_or_rollback(db_store, gh, http, run_id)
                            return await db_store.get_run(run_id) or run

                    cp3.status = StepStatus.ADAPTED
                    adapted_note = adapt_plan.diagnosis
                    cp3.adaptation_used = adapted_note
                    await db_store.upsert_checkpoint_atomic(cp3)
                    await db_store.emit_event(
                        run_id,
                        "step_3_deploy_and_verify",
                        "drift_adapted",
                        f"Adapted to {adapt_plan.adapted_endpoint}: {adapt_plan.field_mapping}",
                        {
                            "mapping": adapt_plan.field_mapping,
                            "diagnosis": adapt_plan.diagnosis,
                        },
                    )
                    adapted_payload = dict(adapt_plan.adapted_payload)
                    adapted_payload.setdefault(
                        "service_name", v1_payload["service_name"]
                    )
                    adapted_payload.setdefault("branch", branch_name)
                    adapted_payload.setdefault("commit_sha", commit_sha)
                    adapted_payload.setdefault(
                        "callback_uri", v1_payload["webhook_url"]
                    )
                    adapted_payload["max_rps"] = _coerce_positive_int(
                        adapted_payload.get("max_rps", v1_payload["rate_limit"])
                    )
                    if adapted_payload.get("env_tier") not in {
                        "staging",
                        "canary",
                        "production",
                    }:
                        adapted_payload["env_tier"] = "staging"
                    adapted_payload["idempotency_key"] = idemp_key
                    adapted_endpoint = adapt_plan.adapted_endpoint

                    resp = await http.post(adapted_endpoint, json=adapted_payload)

                if resp.status_code >= 400:
                    cp3.error_message = f"HTTP {resp.status_code}: {resp.text[:300]}"
                    await db_store.upsert_checkpoint_atomic(cp3)
                    await db_store.emit_event(
                        run_id,
                        "step_3_deploy_and_verify",
                        "deploy_http_error",
                        f"Target deployment endpoint returned HTTP {resp.status_code}; retrying...",
                        {"http_status": resp.status_code},
                    )
                    await asyncio.sleep(0.4)
                    continue

                resp_json = resp.json()
                dep_id = str(resp_json.get("deployment_id", ""))
                cp3.status = StepStatus.SENT_UNVERIFIED
                cp3.external_ref = dep_id
                await db_store.upsert_checkpoint_atomic(cp3)

                # Independent verification probe: separate only-sent from took-effect
                probe_resp = await http.get(f"/verify/{dep_id}")
                verify_data = (
                    probe_resp.json()
                    if probe_resp.status_code == 200
                    else {"active": False}
                )
                cp3.probe_result = verify_data

                if verify_data.get("active"):
                    cp3.status = StepStatus.VERIFIED_TOOK_EFFECT
                    cp3.took_effect = True
                    cp3.post_state = {"deployment_id": dep_id, "verify": verify_data}
                    cp3.compensating_action = {
                        "type": "delete_deployment",
                        "deployment_id": dep_id,
                    }
                    await db_store.upsert_checkpoint_atomic(cp3, run_step=3)
                    await db_store.emit_event(
                        run_id,
                        "step_3_deploy_and_verify",
                        "step_verified",
                        f"Verified deployment {dep_id} took effect (active=True).",
                        {
                            "deployment_id": dep_id,
                            "api_version": verify_data.get("api_version"),
                        },
                    )
                    break

                await db_store.upsert_checkpoint_atomic(cp3)
                await db_store.emit_event(
                    run_id,
                    "step_3_deploy_and_verify",
                    "probe_mismatch",
                    (
                        f"Caught silent drop! POST returned {resp.status_code} (only-sent), "
                        f"but GET /verify/{dep_id} reported active=False. Retrying idempotently..."
                    ),
                    {"http_status": resp.status_code, "probe": verify_data},
                )
                await asyncio.sleep(0.4)
            else:
                cp3.status = StepStatus.FAILED
                cp3.error_message = "Deployment verification failed after retries"
                await db_store.upsert_checkpoint_atomic(cp3)
                await db_store.update_run(
                    run_id, status=RunStatus.FAILED.value, worker_pid=None
                )
                return await db_store.get_run(run_id) or run

        if step_delay > 0:
            await asyncio.sleep(step_delay)
        if await _check_halt_or_rollback(db_store, gh, http, run_id):
            return await db_store.get_run(run_id) or run

        # --- STEP 4: Open PR, Post Verified Evidence, Apply Adaptive Labels ---
        cp4 = existing_cps.get("step_4_github_pr")
        if cp4 and cp4.status == StepStatus.VERIFIED_TOOK_EFFECT:
            pr_url = str(cp4.external_ref)
            await db_store.emit_event(
                run_id,
                "step_4_github_pr",
                "checkpoint_skipped",
                f"Skipped Step 4 (PR already opened: {pr_url}).",
            )
        else:
            cp4 = StepCheckpoint(
                run_id=run_id,
                step_key="step_4_github_pr",
                step_seq=4,
                title="Open GitHub PR & record verification evidence",
                idempotency_key=f"{run_id}:step_4_github_pr",
                attempts=(cp4.attempts + 1) if cp4 else 1,
            )
            evidence_md = (
                f"{fix_plan.pr_body}\n\n"
                f"### FinishLine Verification Proof\n"
                f"- Run ID: `{run_id}`\n"
                f"- Deployment ID: `{dep_id}` (`active={verify_data.get('active')}`)\n"
                f"- Drift Adaptation: `{cp3.adaptation_used or 'None needed'}`"
            )
            pr_info = await gh.ensure_pull_request(
                repo=run.repo,
                head_branch=branch_name,
                title=fix_plan.pr_title,
                body=evidence_md,
            )
            marker = f"<!-- finishline-run:{run_id} -->"
            comment_target = run.issue_number if run.issue_number > 0 else int(pr_info["pr_number"])
            comment_info = await gh.ensure_issue_comment(
                repo=run.repo,
                issue_number=comment_target,
                marker=marker,
                body=(
                    f"FinishLine verified deployment `{dep_id}` took effect and opened PR "
                    f"#{pr_info['pr_number']}: {pr_info['html_url']}"
                ),
            )
            applied_labels = await gh.apply_verified_label(
                run.repo, comment_target, "verified"
            )
            pr_url = str(pr_info["html_url"])
            cp4.status = StepStatus.VERIFIED_TOOK_EFFECT
            cp4.took_effect = True
            cp4.external_ref = pr_url
            cp4.post_state = {
                "pr": pr_info,
                "comment": comment_info,
                "labels": applied_labels,
            }
            cp4.compensating_action = {
                "type": "github_rollback",
                "branch_name": branch_name,
                "pr_number": pr_info["pr_number"],
                "labels": applied_labels,
            }
            await db_store.upsert_checkpoint_atomic(cp4, run_step=4)
            await db_store.emit_event(
                run_id,
                "step_4_github_pr",
                "step_verified",
                f"Opened PR #{pr_info['pr_number']} and verified PR/issue comment & labels.",
                {"pr_url": pr_url, "labels": applied_labels},
            )

        # --- STEP 5: Persist Learned Experience & Complete ---
        summary = f"Completed all 5 stages cleanly. PR: {pr_url} | Deployment: {dep_id}"
        if cp3.adaptation_used:
            learned_id = f"learned-{run_id}"
            learned_text = f"Recovered from contract drift during {run.repo}#{run.issue_number}: {cp3.adaptation_used}"
            emb = await embed_text(learned_text, cfg)
            mem = ExperienceMemory(
                memory_id=learned_id,
                kind="drift_playbook",
                source_repo=run.repo,
                title=f"Learned adaptation ({run_id[:6]})",
                content=learned_text,
                resolution=cp3.adaptation_used,
                embedding=emb,
            )
            await db_store.memories.update_one(
                {"memory_id": learned_id},
                {"$set": mem.model_dump(mode="python")},
                upsert=True,
            )

        cp5 = StepCheckpoint(
            run_id=run_id,
            step_key="step_5_finalize",
            step_seq=5,
            title="Finalize verified run & persist learned experience",
            idempotency_key=f"{run_id}:step_5_finalize",
            status=StepStatus.VERIFIED_TOOK_EFFECT,
            attempts=1,
            took_effect=True,
            post_state={"summary": summary},
            updated_at=utc_now(),
        )
        await db_store.upsert_checkpoint_atomic(cp5, run_step=5)
        await db_store.update_run(
            run_id,
            status=RunStatus.COMPLETED.value,
            worker_pid=None,
            summary=summary,
        )
        await db_store.emit_event(
            run_id,
            "step_5_finalize",
            "run_completed",
            summary,
            {"pr_url": pr_url, "deployment_id": dep_id},
        )
        return await db_store.get_run(run_id) or run
    finally:
        if own_http:
            await http.aclose()
        if own_store:
            await db_store.close()


def main() -> None:
    """CLI entrypoint for spawning the standalone OS worker process."""
    parser = argparse.ArgumentParser(
        description="Run or resume a FinishLine Track 3 job"
    )
    parser.add_argument(
        "--run-id", required=True, help="MongoDB job_runs.run_id to execute"
    )
    parser.add_argument(
        "--step-delay",
        type=float,
        default=0.8,
        help="Delay between steps for live demo pacing",
    )
    args = parser.parse_args()
    asyncio.run(execute_job(args.run_id, step_delay=args.step_delay))


if __name__ == "__main__":
    main()
