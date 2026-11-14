"""Seed MongoDB Atlas experience_memories with real GitHub issues and OpenAPI drift playbooks."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from mongodb_hackathon.embeddings import embed_text
from mongodb_hackathon.models import ExperienceMemory
from mongodb_hackathon.mongo import MongoStore

DRIFT_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "memory_id": "drift-deployments-v1-to-v2",
        "kind": "drift_playbook",
        "source_repo": "finishline/target-service",
        "title": "Deployments API v1 -> v2 contract migration (callback_uri & max_rps)",
        "content": (
            "HTTP 422 or 404 on /v1/deployments when target service upgrades to v2. "
            "Field webhook_url was renamed to callback_uri, rate_limit was renamed to max_rps, "
            "and endpoint moved from /v1/deployments to /v2/deployments with required field env_tier."
        ),
        "resolution": (
            "Switch POST path from /v1/deployments to /v2/deployments, map webhook_url -> callback_uri, "
            "rate_limit -> max_rps, and set env_tier='staging' unless production approval is granted."
        ),
        "field_mapping": {
            "endpoint": "/v2/deployments",
            "webhook_url": "callback_uri",
            "rate_limit": "max_rps",
            "env_tier": "staging",
        },
    },
    {
        "memory_id": "drift-silent-202-verification",
        "kind": "drift_playbook",
        "source_repo": "finishline/target-service",
        "title": "Async 202 Accepted silent drop verification pattern",
        "content": (
            "Deployment POST returns 202 Accepted with a deployment_id, indicating queued work, "
            "but GET /verify/{deployment_id} returns not_found or pending_dropped because the async "
            "worker dropped the job before taking effect."
        ),
        "resolution": (
            "Never mark a deployment complete on HTTP 202 alone. Poll GET /verify/{deployment_id} and "
            "GET /health; if verification reports dropped/not_found, retry with the same idempotency_key "
            "until GET /verify/{deployment_id} returns active=true."
        ),
        "field_mapping": {"verify_endpoint": "/verify/{deployment_id}"},
    },
    {
        "memory_id": "drift-github-label-rename",
        "kind": "drift_playbook",
        "source_repo": "github/governance",
        "title": "GitHub label taxonomy shift (bug -> type:bug, release-blocker -> priority:p1)",
        "content": (
            "Repository label automation fails or skips when repo migrates flat labels like bug or "
            "needs-triage to scoped prefix labels such as type:bug or status:verified."
        ),
        "resolution": (
            "Inspect live repository labels via GitHub API and map legacy label names to existing "
            "prefixed labels before adding labels to an issue or PR."
        ),
        "field_mapping": {"bug": "type:bug", "verified": "status:verified"},
    },
]

PUBLIC_REPOS = [
    "pydantic/pydantic-ai",
    "fastapi/fastapi",
]


async def fetch_real_github_issues(limit_per_repo: int = 8) -> list[dict[str, Any]]:
    """Fetch recent real public issues from GitHub REST API as past-experience records."""
    records: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for repo in PUBLIC_REPOS:
            url = f"https://api.github.com/repos/{repo}/issues"
            try:
                resp = await client.get(
                    url,
                    params={"state": "all", "per_page": limit_per_repo},
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "finishline-seed",
                    },
                )
                if resp.status_code != 200:
                    continue
                for item in resp.json():
                    if "pull_request" in item:
                        continue
                    number = item["number"]
                    title = str(item.get("title", "")).strip()
                    body = str(item.get("body") or "")[:900].strip()
                    labels = [lbl.get("name", "") for lbl in item.get("labels", [])]
                    records.append(
                        {
                            "memory_id": f"gh-{repo.replace('/', '-')}-{number}",
                            "kind": "github_fix",
                            "source_repo": repo,
                            "title": title,
                            "content": f"Repo: {repo} | Labels: {', '.join(labels)}\n{title}\n{body}",
                            "resolution": (
                                f"Reference historical issue #{number} ({item.get('state', 'open')}) "
                                f"from {repo}: verify reproduction, patch config/handler, add regression test."
                            ),
                            "field_mapping": {},
                        }
                    )
            except httpx.HTTPError:
                continue
    return records


async def seed_atlas(store: MongoStore | None = None) -> dict[str, Any]:
    """Initialize Atlas schemas/indexes and upsert real GitHub + drift experience memories."""
    own_store = store is None
    db_store = store or MongoStore()
    try:
        schema_info = await db_store.ensure_schema_and_indexes()
        github_items = await fetch_real_github_issues(limit_per_repo=8)
        all_items = DRIFT_PLAYBOOKS + github_items

        inserted = 0
        for item in all_items:
            emb_text = f"{item['title']}\n{item['content']}\n{item['resolution']}"
            embedding = await embed_text(emb_text, db_store.settings)
            mem = ExperienceMemory(
                memory_id=item["memory_id"],
                kind=item["kind"],
                source_repo=item["source_repo"],
                title=item["title"],
                content=item["content"],
                resolution=item["resolution"],
                field_mapping=item.get("field_mapping", {}),
                embedding=embedding,
            )
            await db_store.memories.update_one(
                {"memory_id": mem.memory_id},
                {"$set": mem.model_dump(mode="python")},
                upsert=True,
            )
            inserted += 1

        return {
            "schema": schema_info,
            "seeded_total": inserted,
            "drift_playbooks": len(DRIFT_PLAYBOOKS),
            "github_issues": len(github_items),
        }
    finally:
        if own_store:
            await db_store.close()


if __name__ == "__main__":
    result = asyncio.run(seed_atlas())
    print(result)
