"""Tests for curated demo_repos registry, source_repo-scoped Vector Search, and API endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from mongodb_hackathon import app as ctrl_mod
from mongodb_hackathon.config import Settings
from mongodb_hackathon.embeddings import embed_text
from mongodb_hackathon.github_adapter import GitHubSandboxAdapter
from mongodb_hackathon.models import DemoRepo, ExperienceMemory, JobRun, RunStatus
from mongodb_hackathon.mongo import MongoStore
from mongodb_hackathon.seed import (
    DRIFT_PLAYBOOKS,
    REPO_RULES,
    STARTER_REPOS,
    _build_starter_repos,
)
from mongodb_hackathon.target_service import app as target_app
from mongodb_hackathon.target_service import state as target_state
from mongodb_hackathon.worker import execute_job


@pytest_asyncio.fixture
async def atlas_store() -> AsyncGenerator[MongoStore]:
    store = MongoStore(Settings())
    await store.ensure_schema_and_indexes()
    try:
        yield store
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_demo_repo_crud_and_seed_shapes(atlas_store: MongoStore) -> None:
    """Verify DemoRepo upsert/list CRUD and curated starter repo + rule definitions."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"tst-{suffix}/payments"
    repo_b = f"tst-{suffix}/billing"
    try:
        saved_a = await atlas_store.upsert_repo(
            DemoRepo(
                repo=repo_a,
                label="Test Payments",
                description="Initial description",
                is_live=False,
                default_prompt="Fix payments webhook",
            )
        )
        assert saved_a.repo == repo_a
        assert saved_a.label == "Test Payments"

        await atlas_store.upsert_repo(
            DemoRepo(
                repo=repo_b,
                label="Test Billing",
                description="Billing worker",
                is_live=True,
                default_prompt="Fix billing batch",
            )
        )
        # Re-upserting repo_a updates fields in place without duplicating.
        updated_a = await atlas_store.upsert_repo(
            DemoRepo(
                repo=repo_a,
                label="Test Payments Updated",
                description="Updated description",
                is_live=False,
                default_prompt="Fix payments webhook v2",
            )
        )
        assert updated_a.label == "Test Payments Updated"

        repos = await atlas_store.list_repos()
        matching_a = [r for r in repos if r.repo == repo_a]
        matching_b = [r for r in repos if r.repo == repo_b]
        assert len(matching_a) == 1
        assert matching_a[0].description == "Updated description"
        assert len(matching_b) == 1
        assert matching_b[0].is_live is True
    finally:
        await atlas_store.repos.delete_many({"repo": {"$in": [repo_a, repo_b]}})

    # Verify seed definitions use global '*' for drift playbooks and distinct repo rules.
    assert all(pb["source_repo"] == "*" for pb in DRIFT_PLAYBOOKS)
    starter_names = {item["repo"] for item in STARTER_REPOS}
    assert {"dry-run/payments-webhook", "dry-run/billing-worker"} <= starter_names
    assert len({r["source_repo"] for r in REPO_RULES}) >= 2

    built_repos, built_rules = _build_starter_repos("octocat/finishline-live")
    assert any(r.repo == "octocat/finishline-live" and r.is_live for r in built_repos)
    assert any(r["source_repo"] == "octocat/finishline-live" for r in built_rules)


@pytest.mark.asyncio
async def test_search_experience_source_repo_isolation_and_invalidation(
    atlas_store: MongoStore,
) -> None:
    """Verify Repo A rules never leak to Repo B, global '*' matches both, and invalidation excludes."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"tst-{suffix}/alpha"
    repo_b = f"tst-{suffix}/beta"
    mem_a_id = f"tst-rule-a-{suffix}"
    mem_b_id = f"tst-rule-b-{suffix}"
    mem_global_id = f"tst-global-{suffix}"

    try:
        text_a = "Alpha webhook rate limit 300 staging callback rule"
        text_b = "Beta billing canary batch size 50 reconciliation rule"
        text_g = "Global schema drift playbook callback_uri max_rps"
        emb_a = await embed_text(text_a, atlas_store.settings)
        emb_b = await embed_text(text_b, atlas_store.settings)
        emb_g = await embed_text(text_g, atlas_store.settings)

        await atlas_store.upsert_memory(
            ExperienceMemory(
                memory_id=mem_a_id,
                kind="repo_rule",
                source_repo=repo_a,
                title="Alpha rate limit rule",
                content=text_a,
                resolution="Set rate_limit=300 for alpha",
                embedding=emb_a,
            )
        )
        await atlas_store.upsert_memory(
            ExperienceMemory(
                memory_id=mem_b_id,
                kind="repo_rule",
                source_repo=repo_b,
                title="Beta batch rule",
                content=text_b,
                resolution="Set batch_size=50 for beta",
                embedding=emb_b,
            )
        )
        await atlas_store.upsert_memory(
            ExperienceMemory(
                memory_id=mem_global_id,
                kind="drift_playbook",
                source_repo="*",
                title="Global drift playbook",
                content=text_g,
                resolution="Map webhook_url -> callback_uri",
                embedding=emb_g,
            )
        )

        res_a = await atlas_store.search_experience(
            "webhook rate limit staging",
            kind="repo_rule",
            limit=10,
            source_repo=repo_a,
        )
        ids_a = [m["memory_id"] for m in res_a]
        assert mem_a_id in ids_a
        assert mem_b_id not in ids_a

        res_b = await atlas_store.search_experience(
            "billing batch canary",
            kind="repo_rule",
            limit=10,
            source_repo=repo_b,
        )
        ids_b = [m["memory_id"] for m in res_b]
        assert mem_b_id in ids_b
        assert mem_a_id not in ids_b

        # Combined query with repo_rule + drift_playbook must still isolate repo_a from repo_b.
        res_combo_a = await atlas_store.search_experience(
            "webhook callback_uri rate limit",
            kind=["repo_rule", "drift_playbook"],
            limit=20,
            source_repo=repo_a,
        )
        combo_ids_a = [m["memory_id"] for m in res_combo_a]
        assert mem_b_id not in combo_ids_a

        # Invalidating mem_a_id excludes it from subsequent search_experience calls.
        modified = await atlas_store.invalidate_memory(mem_a_id)
        assert modified == 1
        res_a_after = await atlas_store.search_experience(
            "webhook rate limit staging",
            kind="repo_rule",
            limit=10,
            source_repo=repo_a,
        )
        assert mem_a_id not in [m["memory_id"] for m in res_a_after]
    finally:
        await atlas_store.memories.delete_many(
            {"memory_id": {"$in": [mem_a_id, mem_b_id, mem_global_id]}}
        )


@pytest.mark.asyncio
async def test_repos_and_memories_api_endpoints(atlas_store: MongoStore) -> None:
    """Verify GET/POST /api/repos and GET/POST /api/memories endpoints via ASGI."""
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"tst-{suffix}/api-alpha"
    repo_b = f"tst-{suffix}/api-beta"
    sandbox_repo = f"tst-{suffix}/api-sandbox"
    mem_a1_id = f"tst-api-a1-{suffix}"
    mem_a2_id = f"tst-api-a2-{suffix}"
    mem_b_id = f"tst-api-b-{suffix}"

    class _StubGitHub(GitHubSandboxAdapter):
        def __init__(self, settings: Settings) -> None:
            super().__init__(settings=settings, token="")
            self.called_with: list[str] = []

        @property
        def has_token(self) -> bool:
            return True

        async def ensure_sandbox_repo(self, full_name: str = "") -> dict[str, Any]:
            self.called_with.append(full_name)
            return {
                "repo": full_name or sandbox_repo,
                "html_url": f"https://github.com/{full_name or sandbox_repo}",
                "created": True,
                "status": "created",
            }

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as tc:
            ctrl_mod.app.state._external_store = True
            ctrl_mod.app.state.store = atlas_store
            cfg = Settings()
            cfg.github_sandbox_repo = "dry-run/finishline-demo-sandbox"
            ctrl_mod.app.state.settings = cfg
            ctrl_mod.app.state.github = GitHubSandboxAdapter(cfg, token="")
            ctrl_mod.app.state.target_client = tc

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=ctrl_mod.app),
                base_url="http://test-control",
            ) as ac:
                bad_repo = await ac.post("/api/repos", json={"repo": "not-a-slug"})
                assert bad_repo.status_code == 400

                no_tok = await ac.post(
                    "/api/repos", json={"repo": sandbox_repo, "create_sandbox": True}
                )
                assert no_tok.status_code == 400

                r_post_a = await ac.post(
                    "/api/repos",
                    json={
                        "repo": repo_a,
                        "label": "API Alpha",
                        "description": "Alpha test repo",
                        "default_prompt": "Check alpha",
                    },
                )
                assert r_post_a.status_code == 201
                assert r_post_a.json()["repo"]["repo"] == repo_a
                assert r_post_a.json()["repo"]["is_live"] is True

                r_post_b = await ac.post(
                    "/api/repos",
                    json={"repo": repo_b, "is_live": False},
                )
                assert r_post_b.status_code == 201
                assert r_post_b.json()["repo"]["is_live"] is False

                stub_gh = _StubGitHub(cfg)
                ctrl_mod.app.state.github = stub_gh
                r_post_sb = await ac.post(
                    "/api/repos",
                    json={"repo": sandbox_repo, "create_sandbox": True},
                )
                assert r_post_sb.status_code == 201
                assert stub_gh.called_with == [sandbox_repo]
                assert r_post_sb.json()["sandbox"]["status"] == "created"

                r_repos = await ac.get("/api/repos")
                assert r_repos.status_code == 200
                repo_names = [item["repo"] for item in r_repos.json()["repos"]]
                assert {repo_a, repo_b, sandbox_repo} <= set(repo_names)

                r_mem_a1 = await ac.post(
                    "/api/memories",
                    json={
                        "memory_id": mem_a1_id,
                        "kind": "repo_rule",
                        "source_repo": repo_a,
                        "title": "Alpha Rule 1",
                        "content": "First alpha rule",
                        "resolution": "Apply first alpha check",
                    },
                )
                assert r_mem_a1.status_code == 201
                assert "embedding" not in r_mem_a1.json()["memory"]

                r_mem_a2 = await ac.post(
                    "/api/memories",
                    json={
                        "memory_id": mem_a2_id,
                        "kind": "repo_rule",
                        "source_repo": repo_a,
                        "title": "Alpha Rule 2",
                        "content": "Second alpha rule",
                    },
                )
                assert r_mem_a2.status_code == 201

                r_mem_b = await ac.post(
                    "/api/memories",
                    json={
                        "memory_id": mem_b_id,
                        "kind": "repo_rule",
                        "source_repo": repo_b,
                        "title": "Beta Rule",
                        "content": "Beta only rule",
                    },
                )
                assert r_mem_b.status_code == 201

                r_list_a = await ac.get(
                    "/api/memories", params={"source_repo": repo_a, "limit": 20}
                )
                assert r_list_a.status_code == 200
                mems_a = r_list_a.json()["memories"]
                assert [m["memory_id"] for m in mems_a] == [mem_a2_id, mem_a1_id]
                assert all("embedding" not in m for m in mems_a)

                r_list_a_global = await ac.get(
                    "/api/memories",
                    params={
                        "source_repo": repo_a,
                        "include_global": "true",
                        "limit": 50,
                    },
                )
                assert r_list_a_global.status_code == 200
                ids_a_global = {m["memory_id"] for m in r_list_a_global.json()["memories"]}
                assert {mem_a1_id, mem_a2_id} <= ids_a_global
                assert mem_b_id not in ids_a_global
    finally:
        await atlas_store.repos.delete_many(
            {"repo": {"$in": [repo_a, repo_b, sandbox_repo]}}
        )
        await atlas_store.memories.delete_many(
            {"memory_id": {"$in": [mem_a1_id, mem_a2_id, mem_b_id]}}
        )
        if hasattr(ctrl_mod.app.state, "_external_store"):
            delattr(ctrl_mod.app.state, "_external_store")


@pytest.mark.asyncio
async def test_worker_scopes_recall_and_stamps_learned_memory_by_repo(
    atlas_store: MongoStore,
) -> None:
    """Verify worker passes run.repo to Step 1/Step 3 recall and stamps learned-{run_id}."""
    target_state.reset()
    suffix = uuid.uuid4().hex[:8]
    run_id = f"tst-{suffix}"
    repo_a = f"dry-run/tst-alpha-{suffix}"
    repo_b = f"dry-run/tst-beta-{suffix}"
    rule_a_id = f"tst-worker-rule-a-{suffix}"
    rule_b_id = f"tst-worker-rule-b-{suffix}"

    try:
        rule_a_text = "Alpha webhook burst rate_limit=300 callback verification"
        rule_b_text = "Beta isolated rule should never appear in alpha runs"
        await atlas_store.upsert_memory(
            ExperienceMemory(
                memory_id=rule_a_id,
                kind="repo_rule",
                source_repo=repo_a,
                title=f"Alpha Rule ({suffix})",
                content=rule_a_text,
                resolution="Use rate_limit=300",
                embedding=await embed_text(rule_a_text, atlas_store.settings),
            )
        )
        await atlas_store.upsert_memory(
            ExperienceMemory(
                memory_id=rule_b_id,
                kind="repo_rule",
                source_repo=repo_b,
                title=f"Beta Rule ({suffix})",
                content=rule_b_text,
                resolution="Use batch=10",
                embedding=await embed_text(rule_b_text, atlas_store.settings),
            )
        )

        await atlas_store.create_run(
            JobRun(
                run_id=run_id,
                repo=repo_a,
                issue_number=0,
                issue_title="Sync alpha webhook deployment config",
                issue_body="Configure rate_limit=300 and adapt to v2 drift.",
                target_service_url="http://test-target",
            )
        )

        cfg = Settings()
        cfg.github_sandbox_repo = repo_a
        gh = GitHubSandboxAdapter(settings=cfg, token="")

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=target_app), base_url="http://test-target"
        ) as client:
            await client.post("/chaos/mode", json={"mode": "drift_v2"})
            final_run = await execute_job(
                run_id=run_id,
                store=atlas_store,
                github=gh,
                target_client=client,
                step_delay=0.0,
            )

        assert final_run.status == RunStatus.COMPLETED
        cp1 = await atlas_store.get_checkpoint(run_id, "step_1_plan")
        assert cp1 is not None
        recalled = cp1.post_state.get("recalled_memories", [])
        assert f"Alpha Rule ({suffix})" in recalled
        assert f"Beta Rule ({suffix})" not in recalled

        learned = await atlas_store.memories.find_one(
            {"memory_id": f"learned-{run_id}"}, {"_id": 0}
        )
        assert learned is not None
        assert learned["source_repo"] == repo_a
        assert learned["kind"] == "drift_playbook"
    finally:
        await atlas_store.runs.delete_many({"run_id": run_id})
        await atlas_store.checkpoints.delete_many({"run_id": run_id})
        await atlas_store.events.delete_many({"run_id": run_id})
        await atlas_store.memories.delete_many(
            {"memory_id": {"$in": [rule_a_id, rule_b_id, f"learned-{run_id}"]}}
        )
        target_state.reset()
