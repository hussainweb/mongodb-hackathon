"""FastAPI + SSE Operator Control Room for FinishLine (port 8000)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from mongodb_hackathon.config import Settings, get_settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import ChaosMode, JobRun, RunStatus, utc_now
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.seed import seed_atlas
from mongodb_hackathon.voice import transcribe_operator_audio

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
AUDIO_DIR = STATIC_DIR / "audio"

FALLBACK_DEMO_ISSUES: list[dict[str, Any]] = [
    {
        "number": 1,
        "title": "Enable resilient rate limiter on /v1/deployments callback webhook",
        "body": (
            "Release blocker: configure callback delivery and safe rate_limit=300 "
            "before deploying the release configuration."
        ),
        "url": "",
        "labels": ["release-blocker"],
    },
    {
        "number": 2,
        "title": "Harden webhook timeout verification after downstream 202 acceptance",
        "body": (
            "Ensure deployment workers verify downstream registration instead of "
            "trusting optimistic 202 Accepted responses."
        ),
        "url": "",
        "labels": ["reliability"],
    },
]


class StartRunRequest(BaseModel):
    """Request payload to start a new autonomous Track 3 closing run."""

    repo: str = ""
    issue_number: int = 1
    issue_title: str = "Release blocker: sync service deployment configuration"
    issue_body: str = ""
    step_delay: float = Field(default=0.8, ge=0.0, le=5.0)
    auto_spawn: bool = True


class ApproveRunRequest(BaseModel):
    """Text approval payload when no audio recording is uploaded."""

    note: str = "Approved by operator"


def _spawn_worker_process(run_id: str, step_delay: float = 0.8) -> int:
    """Spawn a standalone OS worker process so SIGKILL crash tests are genuine."""
    cmd = [
        sys.executable,
        "-m",
        "mongodb_hackathon.worker",
        "--run-id",
        run_id,
        "--step-delay",
        str(step_delay),
    ]
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


async def _fetch_target_state(http: httpx.AsyncClient) -> dict[str, Any]:
    """Read target deployment microservice state cleanly with offline fallback."""
    try:
        resp = await http.get("/state", timeout=2.0)
        if resp.status_code == 200:
            return dict(resp.json())
    except httpx.HTTPError:
        pass
    return {
        "online": False,
        "chaos_mode": ChaosMode.NORMAL.value,
        "deployments": [],
        "request_log": [],
    }


async def _build_run_snapshot(
    store: MongoStore,
    http: httpx.AsyncClient,
    run_id: str,
) -> dict[str, Any] | None:
    """Assemble current run state, ordered checkpoints, recent events, and target state."""
    run = await store.get_run(run_id)
    if run is None:
        return None
    checkpoints = await store.get_checkpoints(run_id)
    events = await store.list_events(run_id, limit=40)
    target = await _fetch_target_state(http)
    crash_count = sum(1 for ev in events if ev.event_type == "worker_sigkilled")
    pr_url = next(
        (
            cp.external_ref
            for cp in checkpoints
            if cp.step_key == "step_2_open_pr_and_comment" and cp.external_ref
        ),
        "",
    )
    branch_name = next(
        (
            str(cp.post_state.get("branch", ""))
            for cp in checkpoints
            if cp.step_key == "step_1_branch_and_patch"
        ),
        "",
    )
    deployment_id = next(
        (
            cp.external_ref
            for cp in checkpoints
            if cp.step_key == "step_3_deploy_and_verify" and cp.external_ref
        ),
        "",
    )
    return {
        "run": {
            **run.model_dump(mode="json"),
            "crash_count": crash_count,
            "pr_url": pr_url,
            "branch_name": branch_name,
            "deployment_id": deployment_id,
        },
        "checkpoints": [cp.model_dump(mode="json") for cp in checkpoints],
        "events": [ev.model_dump(mode="json") for ev in events],
        "target": target,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize MongoStore, GitHub adapter, and target HTTP client once at startup."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    store: MongoStore = getattr(app.state, "store", None) or MongoStore(settings)
    await store.ensure_schema_and_indexes()

    github: GitHubSandboxAdapter = getattr(
        app.state, "github", None
    ) or GitHubSandboxAdapter(settings)
    http: httpx.AsyncClient = getattr(
        app.state, "target_client", None
    ) or httpx.AsyncClient(base_url=settings.target_service_url, timeout=4.0)

    app.state.settings = settings
    app.state.store = store
    app.state.github = github
    app.state.target_client = http
    app.state.owns_store = not hasattr(app.state, "_external_store")

    yield

    await http.aclose()
    if app.state.owns_store:
        await store.close()


app = FastAPI(
    title="FinishLine Operator Control Room", version="1.0.0", lifespan=lifespan
)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _deps(
    request: Request,
) -> tuple[MongoStore, GitHubSandboxAdapter, httpx.AsyncClient, Settings]:
    state = request.app.state
    return state.store, state.github, state.target_client, state.settings


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the single-screen FinishLine Operator & Chaos Control Room."""
    store, github, http, settings = _deps(request)
    runs = await store.list_runs(limit=15)
    target = await _fetch_target_state(http)
    memories = (
        await store.memories.find({}, {"_id": 0, "embedding": 0})
        .sort("updated_at", -1)
        .to_list(length=12)
    )

    repo = settings.github_sandbox_repo.strip()
    issues: list[dict[str, Any]] = []
    if github.has_token and repo:
        try:
            issues = await github.list_open_issues(repo, limit=8)
        except httpx.HTTPError, OSError, RuntimeError:
            issues = []
    if not issues:
        issues = FALLBACK_DEMO_ISSUES

    initial_run_id = runs[0].run_id if runs else ""
    initial_snapshot = (
        await _build_run_snapshot(store, http, initial_run_id)
        if initial_run_id
        else None
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "sandbox_repo": repo or "dry-run/finishline-demo-sandbox",
            "has_github_token": github.has_token,
            "runs": [r.model_dump(mode="json") for r in runs],
            "issues": issues,
            "memories": memories,
            "target": target,
            "chaos_modes": [m.value for m in ChaosMode],
            "initial_run_id": initial_run_id,
            "initial_snapshot": initial_snapshot,
        },
    )


@app.post("/sandbox/bootstrap")
async def bootstrap_sandbox(request: Request, repo: str = "") -> JSONResponse:
    """Ensure the public GitHub sandbox repository, seed issues, and Atlas playbooks."""
    store, github, _, settings = _deps(request)
    target_repo = repo.strip() or settings.github_sandbox_repo.strip()
    info = await github.ensure_sandbox_repo(target_repo)
    resolved_repo = str(
        info.get("repo", target_repo or "dry-run/finishline-demo-sandbox")
    )
    if info.get("created") or info.get("status") == "exists":
        settings.github_sandbox_repo = resolved_repo

    seed_summary = await seed_atlas(store)
    issues = await github.list_open_issues(resolved_repo, limit=8)
    if not issues:
        issues = FALLBACK_DEMO_ISSUES

    return JSONResponse(
        {
            "sandbox": info,
            "repo": resolved_repo,
            "issues": issues,
            "seed": seed_summary,
        }
    )


@app.get("/api/issues")
async def list_issues(request: Request, repo: str = "") -> JSONResponse:
    """Return open issues from the configured GitHub sandbox repository."""
    _, github, _, settings = _deps(request)
    target_repo = repo.strip() or settings.github_sandbox_repo.strip()
    issues = await github.list_open_issues(target_repo, limit=10) if target_repo else []
    if not issues:
        issues = FALLBACK_DEMO_ISSUES
    return JSONResponse({"repo": target_repo, "issues": issues})


@app.get("/api/runs")
async def list_runs(request: Request) -> JSONResponse:
    """Return recent job runs from MongoDB Atlas."""
    store, _, _, _ = _deps(request)
    runs = await store.list_runs(limit=20)
    return JSONResponse({"runs": [r.model_dump(mode="json") for r in runs]})


@app.get("/api/runs/{run_id}")
async def get_run_snapshot(request: Request, run_id: str) -> JSONResponse:
    """Return full run, checkpoint, event, and target microservice snapshot."""
    store, _, http, _ = _deps(request)
    snapshot = await _build_run_snapshot(store, http, run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return JSONResponse(snapshot)


@app.post("/runs")
async def create_and_start_run(request: Request, body: StartRunRequest) -> JSONResponse:
    """Create a JobRun in MongoDB Atlas and spawn a standalone OS worker PID."""
    store, github, _, settings = _deps(request)
    repo = body.repo.strip() or settings.github_sandbox_repo.strip()
    if not repo and github.has_token:
        info = await github.ensure_sandbox_repo()
        repo = str(info.get("repo", "dry-run/finishline-demo-sandbox"))
        settings.github_sandbox_repo = repo
    repo = repo or "dry-run/finishline-demo-sandbox"

    issue_title = body.issue_title
    issue_body = body.issue_body
    if (
        github.has_token
        and repo != "dry-run/finishline-demo-sandbox"
        and not issue_body
    ):
        gh_issue = await github.get_issue(repo, body.issue_number)
        issue_title = str(gh_issue.get("title", issue_title))
        issue_body = str(gh_issue.get("body", issue_body))

    run_id = uuid.uuid4().hex[:12]
    run = JobRun(
        run_id=run_id,
        repo=repo,
        issue_number=body.issue_number,
        issue_title=issue_title,
        issue_body=issue_body,
        target_service_url=settings.target_service_url,
        status=RunStatus.RUNNING,
    )
    await store.create_run(run)
    await store.emit_event(
        run_id,
        "run",
        "run_created",
        f"Created Track 3 run for {repo}#{body.issue_number}: {issue_title}",
    )

    pid: int | None = None
    if body.auto_spawn:
        pid = _spawn_worker_process(run_id, step_delay=body.step_delay)
        await store.update_run(run_id, worker_pid=pid)
        await store.emit_event(
            run_id,
            "run",
            "worker_spawned",
            f"Spawned standalone OS worker PID {pid}.",
            {"worker_pid": pid},
        )

    created = await store.get_run(run_id) or run
    return JSONResponse(
        {
            "run_id": run_id,
            "worker_pid": pid,
            "run": created.model_dump(mode="json"),
        },
        status_code=201,
    )


@app.post("/runs/{run_id}/kill")
async def kill_worker_pid(request: Request, run_id: str) -> JSONResponse:
    """Send SIGKILL to the active worker OS process to demonstrate crash survival."""
    store, _, _, _ = _deps(request)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    killed = False
    pid = run.worker_pid
    if pid and pid != os.getpid():
        try:
            os.kill(pid, signal.SIGKILL)
            killed = True
        except ProcessLookupError:
            killed = False

    await store.update_run(
        run_id,
        status=RunStatus.CRASHED.value,
        worker_pid=None,
    )
    await store.emit_event(
        run_id,
        f"step_{max(run.current_step, 1)}",
        "worker_sigkilled",
        f"Simulated crash: sent SIGKILL to worker PID {pid or 'N/A'}. Checkpoints preserved in MongoDB Atlas.",
        {"killed_pid": pid, "sigkill_delivered": killed},
    )
    updated = await store.get_run(run_id)
    return JSONResponse(
        {
            "run_id": run_id,
            "killed_pid": pid,
            "sigkill_delivered": killed,
            "run": updated.model_dump(mode="json") if updated else None,
        }
    )


@app.post("/runs/{run_id}/resume")
async def resume_worker(
    request: Request, run_id: str, step_delay: float = 0.8
) -> JSONResponse:
    """Spawn a fresh OS worker process that resumes strictly from Atlas checkpoints."""
    store, _, _, _ = _deps(request)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    pid = _spawn_worker_process(run_id, step_delay=step_delay)
    await store.update_run(
        run_id,
        status=RunStatus.RUNNING.value,
        worker_pid=pid,
    )
    await store.emit_event(
        run_id,
        f"step_{max(run.current_step, 1)}",
        "worker_resumed",
        f"Spawned fresh OS worker PID {pid}; skipping completed checkpoints without duplicate writes.",
        {"worker_pid": pid},
    )
    updated = await store.get_run(run_id)
    return JSONResponse(
        {
            "run_id": run_id,
            "worker_pid": pid,
            "run": updated.model_dump(mode="json") if updated else None,
        }
    )


@app.post("/runs/{run_id}/approve")
async def approve_run(
    request: Request,
    run_id: str,
    note: Annotated[str | None, Form()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
) -> JSONResponse:
    """Grant approval via text or uploaded operator audio (transcribed via ElevenLabs Scribe v2)."""
    store, _, _, settings = _deps(request)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    approval_text = (note or "").strip()
    if audio is not None:
        raw_bytes = await audio.read()
        approval_text = await asyncio.to_thread(
            transcribe_operator_audio,
            raw_bytes,
            filename=audio.filename or "approval.webm",
            settings=settings,
        )
    elif not approval_text and request.headers.get("content-type", "").startswith(
        "application/json"
    ):
        payload = ApproveRunRequest.model_validate(await request.json())
        approval_text = payload.note

    approval_text = approval_text or "Approved by operator"
    lowered = approval_text.lower()
    if any(word in lowered for word in ("abort", "halt", "rollback", "cancel", "stop")):
        await store.update_run(
            run_id,
            halt_requested=True,
            approval_note=approval_text,
        )
        await store.emit_event(
            run_id,
            "step_3_deploy_and_verify",
            "voice_abort_received",
            f"Operator instructed halt/rollback via voice: '{approval_text}'",
        )
    else:
        await store.update_run(
            run_id,
            approval_granted=True,
            approval_note=approval_text,
        )
        await store.emit_event(
            run_id,
            "step_3_deploy_and_verify",
            "operator_approved",
            f"Operator approved gate: '{approval_text}'",
        )

    # Ensure a worker is alive to act on the decision if previously crashed
    refreshed = await store.get_run(run_id)
    if refreshed and refreshed.status == RunStatus.CRASHED:
        pid = _spawn_worker_process(run_id, step_delay=0.6)
        await store.update_run(run_id, status=RunStatus.RUNNING.value, worker_pid=pid)

    final_run = await store.get_run(run_id)
    return JSONResponse(
        {
            "run_id": run_id,
            "transcript": approval_text,
            "run": final_run.model_dump(mode="json") if final_run else None,
        }
    )


@app.post("/runs/{run_id}/rollback")
async def trigger_rollback(request: Request, run_id: str) -> JSONResponse:
    """Request Track 1 compensating rollback across Target Service and GitHub."""
    store, _, _, _ = _deps(request)
    run = await store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    await store.update_run(run_id, halt_requested=True)
    await store.emit_event(
        run_id,
        f"step_{max(run.current_step, 1)}",
        "halt_requested",
        "Operator requested Halt & Compensating Rollback.",
    )
    if run.status in {
        RunStatus.CRASHED,
        RunStatus.COMPLETED,
        RunStatus.AWAITING_APPROVAL,
    }:
        pid_alive = False
        if run.worker_pid:
            try:
                os.kill(run.worker_pid, 0)
                pid_alive = True
            except OSError:
                pid_alive = False
        if not pid_alive:
            pid = _spawn_worker_process(run_id, step_delay=0.2)
            await store.update_run(
                run_id, worker_pid=pid, status=RunStatus.RUNNING.value
            )

    updated = await store.get_run(run_id)
    return JSONResponse(
        {
            "run_id": run_id,
            "halt_requested": True,
            "run": updated.model_dump(mode="json") if updated else None,
        }
    )


@app.post("/chaos/{mode}")
async def set_chaos_mode(request: Request, mode: ChaosMode) -> JSONResponse:
    """Toggle chaos mode on the local target deployment microservice."""
    _, _, http, _ = _deps(request)
    try:
        resp = await http.post("/chaos/mode", json={"mode": mode.value})
        resp.raise_for_status()
        return JSONResponse(resp.json())
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Target service unreachable for chaos toggle: {exc}",
        ) from exc


@app.post("/target/reset")
async def reset_target_service(request: Request) -> JSONResponse:
    """Reset the target deployment microservice state and set chaos_mode=normal."""
    _, _, http, _ = _deps(request)
    try:
        resp = await http.post("/reset")
        resp.raise_for_status()
        return JSONResponse(resp.json())
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Target service unreachable for reset: {exc}",
        ) from exc


@app.get("/api/target-state")
async def get_target_state(request: Request) -> JSONResponse:
    """Fetch current chaos mode, deployed records, and request log from target service."""
    _, _, http, _ = _deps(request)
    return JSONResponse(await _fetch_target_state(http))


@app.get("/api/memories")
async def list_memories(request: Request) -> JSONResponse:
    """List Atlas Vector Search experience memories (without raw float vectors)."""
    store, _, _, _ = _deps(request)
    docs = (
        await store.memories.find({}, {"_id": 0, "embedding": 0})
        .sort("updated_at", -1)
        .to_list(length=20)
    )
    return JSONResponse({"memories": jsonable_encoder(docs)})


@app.post("/memories/{memory_id}/invalidate")
async def invalidate_memory_endpoint(
    request: Request, memory_id: str, restore: bool = False
) -> JSONResponse:
    """Invalidate (or restore) a drift playbook memory in Atlas (Track 2 crossover)."""
    store, _, _, _ = _deps(request)
    new_status = "active" if restore else "invalidated"
    res = await store.memories.update_one(
        {"memory_id": memory_id},
        {"$set": {"status": new_status, "updated_at": utc_now()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return JSONResponse({"memory_id": memory_id, "status": new_status})


@app.get("/runs/{run_id}/stream")
async def stream_run_events(request: Request, run_id: str) -> StreamingResponse:
    """Stream real-time MongoDB Atlas Change Streams snapshots as Server-Sent Events."""
    store, _, http, _ = _deps(request)

    async def event_generator() -> AsyncGenerator[str]:
        initial = await _build_run_snapshot(store, http, run_id)
        if initial is not None:
            yield f"event: snapshot\ndata: {json.dumps(initial)}\n\n"

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=32)

        async def _pump_changes() -> None:
            try:
                async for change in store.watch_run_stream(run_id):
                    if queue.full():
                        with suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                    await queue.put(change)
            except PyMongoError, OSError, RuntimeError:
                return

        pump_task = asyncio.create_task(_pump_changes())
        last_signature = json.dumps(initial, sort_keys=True) if initial else ""

        try:
            while True:
                if await request.is_disconnected():
                    break
                with suppress(TimeoutError):
                    await asyncio.wait_for(queue.get(), timeout=2.0)
                    # Drain any burst of rapid Atlas updates
                    while not queue.empty():
                        with suppress(asyncio.QueueEmpty):
                            queue.get_nowait()

                snap = await _build_run_snapshot(store, http, run_id)
                if snap is not None:
                    sig = json.dumps(snap, sort_keys=True)
                    if sig != last_signature:
                        last_signature = sig
                        yield f"event: snapshot\ndata: {json.dumps(snap)}\n\n"
                    else:
                        yield ": keepalive\n\n"
        finally:
            pump_task.cancel()
            with suppress(asyncio.CancelledError):
                await pump_task

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
