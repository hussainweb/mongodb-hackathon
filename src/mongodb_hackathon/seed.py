"""Seed MongoDB Atlas experience_memories with real GitHub issues and OpenAPI drift playbooks."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from mongodb_hackathon.config import Settings
from mongodb_hackathon.embeddings import embed_text
from mongodb_hackathon.models import DemoRepo, ExperienceMemory
from mongodb_hackathon.mongo import MongoStore

STARTER_REPOS: list[dict[str, Any]] = [
    {
        "repo": "dry-run/payments-infra",
        "label": "Payments Infra (OpenTofu + Docker)",
        "description": (
            "OpenTofu infrastructure in terraform/environments/staging/ provisioning local Docker worker containers."
        ),
        "is_live": False,
        "default_prompt": (
            "Burst webhook traffic is dropping at 120 RPS. Scale worker_count to 3 and raise "
            "max_rps=300 in OpenTofu, apply to Docker, and verify container /health probes."
        ),
    },
    {
        "repo": "dry-run/billing-stack",
        "label": "Billing Stack (OpenTofu deploy/tf)",
        "description": (
            "Alternate repo layout with OpenTofu modules under deploy/tf/prod.tfvars."
        ),
        "is_live": False,
        "default_prompt": (
            "Scale billing-worker containers to 2 replicas with canary max_rps=150 and verify live health."
        ),
    },
    {
        "repo": "dry-run/payments-webhook",
        "label": "Payments Webhook (Dry-Run)",
        "description": (
            "High-throughput payment webhook relay and rate-limited deployment pipeline (local dry-run)."
        ),
        "is_live": False,
        "default_prompt": (
            "Enable resilient rate limiter on /v1/deployments callback webhook with safe "
            "rate_limit=300 and verify downstream acceptance."
        ),
    },
    {
        "repo": "dry-run/billing-worker",
        "label": "Billing Worker (Dry-Run)",
        "description": (
            "Async invoice and billing reconciliation worker with strict staging concurrency caps (local dry-run)."
        ),
        "is_live": False,
        "default_prompt": (
            "Harden billing worker retry backoff and verify deployment health before promoting release."
        ),
    },
]

REPO_RULES: list[dict[str, Any]] = [
    {
        "memory_id": "rule-payments-infra-tofu-guard",
        "kind": "repo_rule",
        "source_repo": "dry-run/payments-infra",
        "title": "Payments Infra: cap staging worker_count <= 4 and max_rps <= 300",
        "content": (
            "Repo rule for dry-run/payments-infra: OpenTofu files live under terraform/environments/staging/. "
            "Staging runs must cap worker_count <= 4, max_rps <= 300, and verify all Docker containers return healthy."
        ),
        "resolution": (
            "Update terraform/environments/staging/terraform.tfvars with worker_count <= 4, max_rps=300, "
            "apply via tofu, and verify every worker container /health returns active=true."
        ),
        "field_mapping": {"tf_dir": "terraform/environments/staging", "max_workers": "4"},
    },
    {
        "memory_id": "rule-billing-stack-canary-guard",
        "kind": "repo_rule",
        "source_repo": "dry-run/billing-stack",
        "title": "Billing Stack: use deploy/tf/prod.tfvars with canary max_rps=150",
        "content": (
            "Repo rule for dry-run/billing-stack: OpenTofu root is deploy/tf/ (not infra/). "
            "Use prod.tfvars with conservative max_rps=150 and env_tier='canary'."
        ),
        "resolution": (
            "Update deploy/tf/prod.tfvars with worker_count=2, max_rps=150, env_tier='canary', "
            "and verify Docker container health before opening PR."
        ),
        "field_mapping": {"tf_dir": "deploy/tf", "rate_limit_max": "150"},
    },
    {
        "memory_id": "rule-payments-webhook-rate-limit",
        "kind": "repo_rule",
        "source_repo": "dry-run/payments-webhook",
        "title": "Payments Webhook: cap staging rate_limit <= 300 and verify callback URI",
        "content": (
            "Repo rule for dry-run/payments-webhook: staging webhook deployments must cap "
            "rate_limit <= 300 (or max_rps <= 300) and route callbacks through verified ingest URI."
        ),
        "resolution": (
            "Configure service_config.json with service_name='payments-webhook', rate_limit=300, "
            "and verify downstream active=true before opening PR."
        ),
        "field_mapping": {"service_name": "payments-webhook", "rate_limit_max": "300"},
    },
    {
        "memory_id": "rule-billing-worker-canary-batch",
        "kind": "repo_rule",
        "source_repo": "dry-run/billing-worker",
        "title": "Billing Worker: enforce canary batch limit 150 and idempotent verification",
        "content": (
            "Repo rule for dry-run/billing-worker: billing reconciliation jobs must use conservative "
            "rate_limit=150, service_name='billing-worker', and confirm active=true before issue close."
        ),
        "resolution": (
            "Set service_name='billing-worker' and conservative rate_limit=150 in service_config.json, "
            "and verify GET /verify/{deployment_id} returns active=true."
        ),
        "field_mapping": {"service_name": "billing-worker", "rate_limit_max": "150"},
    },
]

DRIFT_PLAYBOOKS: list[dict[str, Any]] = [
    {
        "memory_id": "drift-deployments-v1-to-v2",
        "kind": "drift_playbook",
        "source_repo": "*",
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
        "source_repo": "*",
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
        "source_repo": "*",
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
    {
        "memory_id": "drift-opentofu-docker-v1-to-v2",
        "kind": "drift_playbook",
        "source_repo": "*",
        "title": "OpenTofu Docker worker v1 -> v2 env contract drift (MAX_RPS, CALLBACK_URI, ENV_TIER)",
        "content": (
            "Docker worker container image upgraded to v2 and rejects legacy v1 env vars RATE_LIMIT / WEBHOOK_URL "
            "with HTTP 503 contract_drift, requiring MAX_RPS, CALLBACK_URI, and ENV_TIER."
        ),
        "resolution": (
            "Set use_v2_env=true (mapping webhook_url -> callback_uri, rate_limit -> max_rps, "
            "and env_tier='staging') in OpenTofu tfvars/apply variables and re-apply containers."
        ),
        "field_mapping": {
            "endpoint": "/v2/deployments",
            "webhook_url": "callback_uri",
            "rate_limit": "max_rps",
            "env_tier": "staging",
            "use_v2_env": "true",
        },
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


def _build_starter_repos(sandbox_repo: str) -> tuple[list[DemoRepo], list[dict[str, Any]]]:
    """Assemble curated starter repos and per-repo governance rules."""
    repos = [DemoRepo(**item) for item in STARTER_REPOS]
    rules = list(REPO_RULES)
    clean_sandbox = sandbox_repo.strip()
    if clean_sandbox and not any(r.repo == clean_sandbox for r in repos):
        is_live = not clean_sandbox.startswith("dry-run/")
        repos.append(
            DemoRepo(
                repo=clean_sandbox,
                label=f"{clean_sandbox} ({'Live Sandbox' if is_live else 'Dry-Run'})",
                description=(
                    "Live GitHub sandbox repository for real branch, commit, PR, comment, and label execution."
                    if is_live
                    else "Configured sandbox repository for Track 3 verification."
                ),
                is_live=is_live,
                default_prompt=(
                    "Enable resilient rate limiter on /v1/deployments callback webhook with "
                    "rate_limit=300 and verify live PR + deployment."
                ),
            )
        )
        rules.append(
            {
                "memory_id": f"rule-{clean_sandbox.replace('/', '-')}-sandbox-guard",
                "kind": "repo_rule",
                "source_repo": clean_sandbox,
                "title": f"{clean_sandbox}: verify live PR and staging deployment before issue close",
                "content": (
                    f"Repo rule for {clean_sandbox}: never close an issue or mark PR ready until "
                    "service_config.json patch is committed, target deployment returns active=true, "
                    "and PR proof comment is posted."
                ),
                "resolution": (
                    "Commit service_config.json to feature branch, verify downstream active=true, "
                    "open PR, and attach proof comment + verified label."
                ),
                "field_mapping": {"env_tier": "staging", "require_pr_proof": "true"},
            }
        )
    return repos, rules


async def seed_atlas(store: MongoStore | None = None) -> dict[str, Any]:
    """Initialize Atlas schemas/indexes, curated demo_repos, and Vector Search memories."""
    own_store = store is None
    db_store = store or MongoStore()
    try:
        schema_info = await db_store.ensure_schema_and_indexes()
        sandbox_repo = (
            db_store.settings.github_sandbox_repo.strip()
            or Settings().github_sandbox_repo.strip()
        )
        starter_repos, repo_rules = _build_starter_repos(sandbox_repo)
        for repo_entry in starter_repos:
            await db_store.upsert_repo(repo_entry)

        github_items = await fetch_real_github_issues(limit_per_repo=8)
        all_items = DRIFT_PLAYBOOKS + repo_rules + github_items

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
            await db_store.upsert_memory(mem)
            inserted += 1

        return {
            "schema": schema_info,
            "seeded_total": inserted,
            "repos_seeded": len(starter_repos),
            "drift_playbooks": len(DRIFT_PLAYBOOKS),
            "repo_rules": len(repo_rules),
            "github_issues": len(github_items),
        }
    finally:
        if own_store:
            await db_store.close()


if __name__ == "__main__":
    result = asyncio.run(seed_atlas())
    print(result)
