"""Tests for repo-agnostic OpenTofu discovery, Docker execution/rollback, and /super-secret-page."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon import tofu_adapter
from mongodb_hackathon.agent import plan_release_fix
from mongodb_hackathon.config import Settings
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import JobRun, RunStatus, StepStatus
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.worker import execute_job


@pytest_asyncio.fixture
async def atlas_store() -> AsyncGenerator[MongoStore]:
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()
    try:
        yield store
    finally:
        await store.close()


async def _cleanup_run(store: MongoStore, run_id: str) -> None:
    await store.runs.delete_many({"run_id": run_id})
    await store.checkpoints.delete_many({"run_id": run_id})
    await store.events.delete_many({"run_id": run_id})
    await store.memories.delete_many({"memory_id": f"learned-{run_id}"})


@pytest.mark.asyncio
async def test_multi_structure_repo_discovery_chooses_correct_tf_paths() -> None:
    """Agent discovers .tf/.tfvars regardless of repo folder layout and falls back to service_config.json."""
    gh = GitHubSandboxAdapter(Settings(), token="")
    offline_cfg = Settings()
    offline_cfg.openai_api_key = ""

    # Repo A: terraform/environments/staging/terraform.tfvars
    files_a, contents_a = await gh.discover_infra_context("dry-run/payments-infra")
    assert "terraform/environments/staging/main.tf" in files_a
    plan_a = await plan_release_fix(
        issue_number=0,
        issue_title="Scale workers to 3 and max_rps 300",
        issue_body="Burst webhook traffic dropping; scale worker_count=3 and max_rps=300",
        memories=[],
        settings=offline_cfg,
        repo_files=files_a,
        file_contents=contents_a,
    )
    assert plan_a.target_kind == "opentofu"
    assert plan_a.tf_dir == "terraform/environments/staging"
    assert plan_a.patch_filename == "terraform/environments/staging/terraform.tfvars"
    assert "worker_count = 3" in plan_a.patch_content
    assert "max_rps      = 300" in plan_a.patch_content

    # Repo B: deploy/tf/prod.tfvars
    files_b, contents_b = await gh.discover_infra_context("dry-run/billing-stack")
    assert "deploy/tf/prod.tfvars" in files_b
    plan_b = await plan_release_fix(
        issue_number=0,
        issue_title="Scale billing canary to 2 workers at 150 rps",
        issue_body="Keep canary max_rps=150 and 2 replicas",
        memories=[],
        settings=offline_cfg,
        repo_files=files_b,
        file_contents=contents_b,
    )
    assert plan_b.target_kind == "opentofu"
    assert plan_b.tf_dir == "deploy/tf"
    assert plan_b.patch_filename == "deploy/tf/prod.tfvars"
    assert "worker_count = 2" in plan_b.patch_content
    assert 'env_tier     = "canary"' in plan_b.patch_content

    # Repo C: legacy service_config.json repo
    files_c, contents_c = await gh.discover_infra_context("dry-run/payments-webhook")
    plan_c = await plan_release_fix(
        issue_number=1,
        issue_title="Raise staging rate_limit to 300",
        issue_body="rate_limit=300",
        memories=[],
        settings=offline_cfg,
        repo_files=files_c,
        file_contents=contents_c,
    )
    assert plan_c.target_kind == "service_config"
    assert plan_c.patch_filename == "service_config.json"


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_lock_cleanup_and_live_opentofu_docker_lifecycle(
    atlas_store: MongoStore,
) -> None:
    """Verify real OpenTofu + Docker container apply, /health probe, stale lock cleanup, and rollback."""
    suffix = uuid.uuid4().hex[:6]
    repo = f"dry-run/live-tofu-{suffix}"
    ws_dir: Path = tofu_adapter.workspace_dir_for_repo(repo)
    gh = GitHubSandboxAdapter(Settings(), token="")
    run_id = f"tst-tofu-{suffix}"

    try:
        # Prepare workspace and simulate a stale lock left by SIGKILLed worker
        ws_dir, pre_files = await tofu_adapter.prepare_workspace(
            github=gh,
            repo=repo,
            branch_name=f"finishline/task-{suffix}",
            tf_dir="infra",
            patch_filename="infra/terraform.tfvars",
            patch_content=(
                'worker_count = 2\n'
                'max_rps      = 300\n'
                'service_name = "payments-webhook"\n'
                'env_tier     = "staging"\n'
                'callback_uri = "https://hooks.example.internal/v1/ingest"\n'
            ),
        )
        lock_file = ws_dir / ".terraform.tfstate.lock.info"
        lock_file.write_text('{"ID":"dead-pid-lock"}', encoding="utf-8")
        assert tofu_adapter._clear_stale_lock(ws_dir) is True
        assert not lock_file.exists()

        # Apply real OpenTofu against local Docker daemon
        apply_res = await tofu_adapter.apply_opentofu(
            ws_dir=ws_dir,
            repo=repo,
            extra_vars={"worker_count": 2, "max_rps": 300},
        )
        workers = apply_res["workers"]
        assert len(workers) == 2

        # Probe real Docker containers /health
        probe = await tofu_adapter.probe_workers(workers, expected_count=2)
        assert probe["healthy"] is True
        assert probe["active"] is True
        assert probe["worker_count"] == 2
        assert probe["max_rps"] == 600  # 2 containers x 300 max_rps

        # Inspect live topology endpoint helper
        topo = await tofu_adapter.inspect_live_docker_workers(simulate_traffic=True)
        matched = [w for w in topo["workers"] if suffix in str(w.get("name", ""))]
        assert len(matched) == 2
        assert topo["traffic"] is not None
        assert topo["traffic"]["delivered"] >= 1

        # Verify rollback destroys ephemeral containers cleanly when no pre_files existed
        rb_msg = await tofu_adapter.rollback_opentofu(repo=repo, pre_files=pre_files)
        assert "destroyed" in rb_msg or "restored" in rb_msg

        topo_after = await tofu_adapter.inspect_live_docker_workers(simulate_traffic=False)
        assert not [w for w in topo_after["workers"] if suffix in str(w.get("name", ""))]
    finally:
        await tofu_adapter.rollback_opentofu(repo=repo, pre_files={})
        if ws_dir.exists():
            shutil.rmtree(ws_dir, ignore_errors=True)
        await _cleanup_run(atlas_store, run_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_opentofu_worker_pipeline_with_mocked_tofu(
    atlas_store: MongoStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify full 5-stage worker pipeline handles OpenTofu drift adaptation and rollback."""
    suffix = uuid.uuid4().hex[:8]
    run_id = f"tst-tfw-{suffix}"
    probe_calls = 0

    async def fake_prepare_workspace(**kwargs: Any) -> tuple[Path, dict[str, str]]:
        return Path("/tmp/fake-ws"), {"terraform.tfvars": "worker_count = 1\nmax_rps = 120\n"}

    async def fake_apply_opentofu(**kwargs: Any) -> dict[str, Any]:
        return {
            "workers": [
                {"name": "w1", "container_id": "abc123", "port": 18081, "url": "http://127.0.0.1:18081"},
                {"name": "w2", "container_id": "def456", "port": 18082, "url": "http://127.0.0.1:18082"},
            ]
        }

    async def fake_probe_workers(workers: list[dict[str, Any]], expected_count: int = 1) -> dict[str, Any]:
        nonlocal probe_calls
        probe_calls += 1
        if probe_calls == 1:
            return {
                "healthy": False,
                "active": False,
                "workers": workers,
                "drift_errors": ["missing MAX_RPS (v1 RATE_LIMIT is deprecated)"],
            }
        return {
            "healthy": True,
            "active": True,
            "workers": workers,
            "drift_errors": [],
            "api_version": "v2",
            "max_rps": 600,
            "worker_count": 2,
        }

    monkeypatch.setattr("mongodb_hackathon.worker.prepare_workspace", fake_prepare_workspace)
    monkeypatch.setattr("mongodb_hackathon.worker.apply_opentofu", fake_apply_opentofu)
    monkeypatch.setattr("mongodb_hackathon.worker.probe_workers", fake_probe_workers)

    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/payments-infra",
                issue_number=0,
                issue_title="Scale to 2 workers and 300 RPS",
                issue_body="Scale worker_count=2 max_rps=300",
                target_service_url="http://test-target",
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=GitHubSandboxAdapter(Settings(), token=""),
                target_client=client,
                step_delay=0.0,
            )

        assert final_run.status == RunStatus.COMPLETED
        cps = {cp.step_key: cp for cp in await atlas_store.get_checkpoints(run_id)}
        assert cps["step_1_plan"].post_state["fix_plan"]["tf_dir"] == "terraform/environments/staging"
        assert cps["step_3_deploy_and_verify"].status == StepStatus.VERIFIED_TOOK_EFFECT
        assert cps["step_3_deploy_and_verify"].compensating_action["type"] == "opentofu_rollback"
        events = await atlas_store.list_events(run_id, limit=30)
        assert any(ev.event_type == "drift_adapted" for ev in events)
    finally:
        await _cleanup_run(atlas_store, run_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_super_secret_page_and_audience_controls(atlas_store: MongoStore) -> None:
    """Verify /super-secret-page renders, /api/docker-topology responds, and audience kill guards work."""
    run_id = f"tst-sec-{uuid.uuid4().hex[:8]}"
    try:
        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo="dry-run/payments-infra",
                issue_number=0,
                issue_title="Audience test run",
                issue_body="Test /super-secret-page",
                target_service_url="http://test-target",
                status=RunStatus.RUNNING,
                worker_pid=None,
            )
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as tc:
            ctrl_mod.app.state._external_store = True
            ctrl_mod.app.state.store = atlas_store
            ctrl_mod.app.state.settings = Settings()
            ctrl_mod.app.state.github = GitHubSandboxAdapter(Settings(), token="")
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                r_secret = await ac.get("/super-secret-page")
                assert r_secret.status_code == 200
                assert "worker-lane-canvas" in r_secret.text
                assert "btn-audience-kill" in r_secret.text
                # Minimal standalone illustration + single button: no operator nav links
                assert 'href="/infra"' not in r_secret.text
                assert 'href="/store"' not in r_secret.text
                # Must stay unpinned by default so new runs update the page dynamically
                assert 'const REQUESTED_RUN_ID = "";' in r_secret.text

                r_topo = await ac.get("/api/docker-topology")
                assert r_topo.status_code == 200
                assert "workers" in r_topo.json()

                # Toggle auto-respawn on then off before testing live kill
                r_ar = await ac.post(
                    f"/runs/{run_id}/auto-respawn", json={"enabled": True}
                )
                assert r_ar.status_code == 200
                assert r_ar.json()["auto_respawn"] is True
                await ac.post(f"/runs/{run_id}/auto-respawn", json={"enabled": False})

                # Audience kill rejects cleanly with 409 when no worker PID is active
                r_kill_guard = await ac.post(f"/runs/{run_id}/kill?source=audience")
                assert r_kill_guard.status_code == 409

                # Dead worker_pid should not be treated as alive or active
                await atlas_store.update_run(run_id, worker_pid=999999)
                r_snap_dead = await ac.get(f"/api/active-run?run_id={run_id}")
                assert r_snap_dead.status_code == 200
                assert r_snap_dead.json()["run"]["worker_alive"] is False

                # Live subprocess PID can be killed cleanly by audience SIGKILL
                proc = await asyncio.create_subprocess_exec("sleep", "30")
                try:
                    await atlas_store.update_run(
                        run_id, status=RunStatus.RUNNING.value, worker_pid=proc.pid
                    )
                    r_snap_live = await ac.get(f"/api/active-run?run_id={run_id}")
                    assert r_snap_live.status_code == 200
                    assert r_snap_live.json()["run"]["worker_alive"] is True

                    r_kill_live = await ac.post(
                        f"/runs/{run_id}/kill?source=audience"
                    )
                    assert r_kill_live.status_code == 200
                    kill_data = r_kill_live.json()
                    assert kill_data["sigkill_delivered"] is True
                    assert kill_data["killed_pid"] == proc.pid
                    assert kill_data["run"]["status"] == RunStatus.CRASHED.value
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                finally:
                    if proc.returncode is None:
                        proc.kill()
                        await asyncio.wait_for(proc.wait(), timeout=3.0)
    finally:
        await _cleanup_run(atlas_store, run_id)


@pytest.mark.asyncio
async def test_super_secret_page_and_active_run_resolution_unit() -> None:
    """Offline unit check for /super-secret-page standalone HTML, dead-PID filtering, and SSE pinning."""
    from datetime import UTC, datetime, timedelta

    stale_orphan = JobRun(
        run_id="stale-orphan",
        repo="dry-run/payments-infra",
        issue_number=0,
        issue_title="Stale orphan",
        issue_body="Old stuck run",
        target_service_url="http://test-target",
        status=RunStatus.RUNNING,
        worker_pid=999999,
        updated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    recent_completed = JobRun(
        run_id="recent-completed",
        repo="dry-run/payments-infra",
        issue_number=0,
        issue_title="Recent done",
        issue_body="Finished cleanly",
        target_service_url="http://test-target",
        status=RunStatus.COMPLETED,
        worker_pid=None,
        updated_at=datetime.now(UTC),
    )

    class _FakeStore:
        def __init__(self, runs: list[JobRun]) -> None:
            self._runs = {r.run_id: r for r in runs}
            self._order = runs

        async def list_runs(self, limit: int = 25) -> list[JobRun]:
            return self._order[:limit]

        async def get_run(self, run_id: str) -> JobRun | None:
            return self._runs.get(run_id)

        async def get_checkpoints(self, run_id: str) -> list[Any]:
            return []

        async def list_events(self, run_id: str, limit: int = 40) -> list[Any]:
            return []

    fake_store: Any = _FakeStore([recent_completed, stale_orphan])
    resolved = await ctrl_mod._resolve_active_run_id(fake_store)
    assert resolved == "recent-completed"

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
    ) as tc:
        ctrl_mod.app.state._external_store = True
        ctrl_mod.app.state.store = fake_store
        ctrl_mod.app.state.settings = Settings()
        ctrl_mod.app.state.github = GitHubSandboxAdapter(Settings(), token="")
        ctrl_mod.app.state.target_client = tc

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=ctrl_mod.app),
            base_url="http://test-control",
        ) as ac:
            r_secret = await ac.get("/super-secret-page")
            assert r_secret.status_code == 200
            assert "worker-lane-canvas" in r_secret.text
            assert "btn-audience-kill" in r_secret.text
            assert 'href="/infra"' not in r_secret.text
            assert 'href="/store"' not in r_secret.text
            assert 'const REQUESTED_RUN_ID = "";' in r_secret.text

            r_active = await ac.get("/api/active-run")
            assert r_active.status_code == 200
            assert r_active.json()["run"]["run_id"] == "recent-completed"
            assert r_active.json()["run"]["worker_alive"] is False
