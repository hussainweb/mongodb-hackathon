"""Pydantic AI agents for release planning and schema-drift adaptation with LangSmith + Logfire."""

from __future__ import annotations

import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any

import logfire
from dotenv import load_dotenv
from langsmith import trace
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from mongodb_hackathon.config import Settings, get_settings
from mongodb_hackathon.models import DriftAdaptationPlan, FixPlan

_OBS_CONFIGURED = False


def configure_observability() -> None:
    """Configure Logfire and LangSmith tracing once per process without crashing on missing token."""
    global _OBS_CONFIGURED
    if _OBS_CONFIGURED:
        return
    load_dotenv()
    if os.getenv("LOGFIRE_TOKEN") or Path(".logfire").exists():
        logfire.configure()
        logfire.instrument_pydantic_ai()
    _OBS_CONFIGURED = True


def build_model(
    settings: Settings, model_override: Model | None = None
) -> Model | None:
    """Create OpenAIChatModel if API key is present, or return explicit test override."""
    if model_override is not None:
        return model_override
    if not settings.openai_api_key:
        return None
    return OpenAIChatModel(
        settings.openai_model,
        provider=OpenAIProvider(api_key=settings.openai_api_key),
    )


def create_planner_agent(model: Model) -> Agent[None, FixPlan]:
    """Create Pydantic AI agent that inspects repo layout and produces a FixPlan."""
    return Agent(
        model,
        name="finishline_release_planner",
        output_type=FixPlan,
        instructions=(
            "You are a senior release reliability & GitOps engineer. Given a GitHub issue/goal, "
            "the repository's actual file tree, existing config/Terraform file contents, and "
            "similar historical rules/resolutions from MongoDB Atlas Vector Search, decide which "
            "exact file to modify and produce a clean, valid FixPlan.\n"
            "- If the repository contains OpenTofu/Terraform files (*.tf / *.tfvars) anywhere in "
            "its directory tree, set `target_kind='opentofu'`, set `tf_dir` to the directory "
            "containing the `.tf` files (e.g. 'infra', 'terraform/environments/staging', 'deploy/tf', "
            "or '.' if at repo root), pick the appropriate `.tfvars` (or `.tf`) path inside that "
            "directory as `patch_filename`, preserve existing variables, and populate `deployment_config` "
            "with `worker_count` (1..8), `rate_limit` (1..10000), `max_rps` (same integer), "
            "`service_name`, `env_tier` ('staging'|'canary'|'production'), and `callback_uri`.\n"
            "- Otherwise (no .tf files), set `target_kind='service_config'`, `tf_dir=''`, target "
            "`service_config.json`, and populate `deployment_config` with `rate_limit`, "
            "`service_name`, and `webhook_url` compatible with /v1/deployments."
        ),
    )


def create_drift_agent(model: Model) -> Agent[None, DriftAdaptationPlan]:
    """Create Pydantic AI agent that adapts a failed v1 payload to a drifted v2 OpenAPI contract."""
    return Agent(
        model,
        name="finishline_drift_adapter",
        output_type=DriftAdaptationPlan,
        instructions=(
            "You are an autonomous integration recovery agent. A downstream service rejected our "
            "request because its API contract changed mid-run. Inspect the error detail, the live "
            "OpenAPI spec excerpt, and retrieved MongoDB Vector Search drift playbooks. Return a "
            "valid DriftAdaptationPlan with `adapted_endpoint` (e.g. '/v2/deployments'), full "
            "`adapted_payload` JSON (using integer `max_rps` and `env_tier` in {'staging','canary','production'}), "
            "exact `field_mapping`, `confidence` (0..1), and whether human confirmation is needed."
        ),
    )


def _extract_int_near(text: str, patterns: list[str], default: int, lo: int, hi: int) -> int:
    for pat in patterns:
        match = re.search(pat, text, flags=re.IGNORECASE)
        if match:
            val = int(match.group(1))
            return max(lo, min(hi, val))
    return default


def _parse_tfvars_kv(raw: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")) or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        parsed[k.strip()] = v.strip().strip('"')
    return parsed


def _deterministic_fix_plan(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    repo_files: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
) -> FixPlan:
    """Deterministic fallback plan used only when OPENAI_API_KEY is unset (offline dry-run)."""
    combined = f"{issue_title}\n{issue_body}"
    files = repo_files or []
    contents = file_contents or {}

    tf_files = [p for p in files if p.endswith(".tf")]
    tfvars_files = [p for p in files if p.endswith(".tfvars")]

    if tf_files:
        # Pick the tfvars file matching a directory that contains .tf files, or create terraform.tfvars there.
        tf_dirs = sorted({posixpath.dirname(p) or "." for p in tf_files})
        chosen_tfvars = ""
        chosen_dir = tf_dirs[0]
        for cand in tfvars_files:
            cand_dir = posixpath.dirname(cand) or "."
            if cand_dir in tf_dirs:
                chosen_tfvars = cand
                chosen_dir = cand_dir
                break
        if not chosen_tfvars:
            chosen_tfvars = (
                "terraform.tfvars"
                if chosen_dir == "."
                else f"{chosen_dir}/terraform.tfvars"
            )

        existing = _parse_tfvars_kv(contents.get(chosen_tfvars, ""))
        service_name = existing.get("service_name", "payments-webhook")
        if "billing" in combined.lower():
            service_name = "billing-worker"
        elif "payment" in combined.lower():
            service_name = "payments-webhook"

        env_tier = existing.get("env_tier", "staging")
        for tier in ("production", "canary", "staging"):
            if tier in combined.lower():
                env_tier = tier
                break

        worker_count = _extract_int_near(
            combined,
            [
                r"worker_count\s*[=:]\s*(\d+)",
                r"replicas?\s*(?:to|=|:)?\s*(\d+)",
                r"(\d+)\s*(?:workers?|replicas?|containers?|instances?)",
            ],
            default=3 if any(w in combined.lower() for w in ("scale", "worker", "replica", "burst")) else int(existing.get("worker_count", "2") or 2),
            lo=1,
            hi=8,
        )
        max_rps = _extract_int_near(
            combined,
            [
                r"(?:max_rps|rate_limit|rps)\s*(?:to|=|:)?\s*(\d+)",
                r"(\d+)\s*rps",
            ],
            default=300 if ("300" in combined or "burst" in combined.lower()) else int(existing.get("max_rps", "250") or 250),
            lo=1,
            hi=10000,
        )
        callback_uri = existing.get(
            "callback_uri", "https://hooks.example.internal/v1/ingest"
        )
        tfvars_body = (
            f"worker_count = {worker_count}\n"
            f"max_rps      = {max_rps}\n"
            f'service_name = "{service_name}"\n'
            f'env_tier     = "{env_tier}"\n'
            f'callback_uri = "{callback_uri}"\n'
        )
        return FixPlan(
            root_cause=(
                f"Address issue #{issue_number} ({issue_title}) by updating OpenTofu vars in "
                f"`{chosen_tfvars}` (worker_count={worker_count}, max_rps={max_rps})."
            ),
            target_kind="opentofu",
            tf_dir=chosen_dir,
            patch_filename=chosen_tfvars,
            patch_content=tfvars_body,
            commit_message=f"infra: scale {service_name} to {worker_count} workers at {max_rps} RPS",
            deployment_config={
                "service_name": service_name,
                "worker_count": worker_count,
                "rate_limit": max_rps,
                "max_rps": max_rps,
                "env_tier": env_tier,
                "callback_uri": callback_uri,
                "webhook_url": callback_uri,
                "tf_dir": chosen_dir,
            },
            pr_title=f"infra: {issue_title} (#{issue_number})" if issue_number > 0 else f"infra: {issue_title[:60]}",
            pr_body=(
                f"Resolves #{issue_number}.\n\n"
                f"- Discovered OpenTofu root: `{chosen_dir}/`\n"
                f"- Updated `{chosen_tfvars}` (`worker_count={worker_count}`, `max_rps={max_rps}`, `env_tier={env_tier}`)\n"
                f"- Applied via `tofu apply` and verified Docker container `/health` probes"
            ),
        )

    rate_limit = 300 if "300" in issue_body or "burst" in issue_body.lower() else 250
    cfg = {
        "service_name": "payments-webhook",
        "webhook_url": "https://hooks.example.internal/v1/ingest",
        "rate_limit": rate_limit,
        "env_tier": "staging",
    }
    return FixPlan(
        root_cause=f"Address issue #{issue_number} ({issue_title}) by tuning rate_limit={rate_limit}.",
        target_kind="service_config",
        tf_dir="",
        patch_filename="service_config.json",
        patch_content=json.dumps(cfg, indent=2) + "\n",
        commit_message=f"fix: resolve #{issue_number} by raising staging rate_limit to {rate_limit}",
        deployment_config={
            "service_name": "payments-webhook",
            "webhook_url": "https://hooks.example.internal/v1/ingest",
            "rate_limit": rate_limit,
        },
        pr_title=f"fix: {issue_title} (#{issue_number})",
        pr_body=(
            f"Resolves #{issue_number}.\n\n"
            f"- Root cause: burst retries throttled at legacy rate limit\n"
            f"- Updated `service_config.json` (`rate_limit={rate_limit}`)\n"
            f"- Verified downstream deployment via independent health/verify probe"
        ),
    )


def _deterministic_drift_plan(
    original_payload: dict[str, Any],
    playbooks: list[dict[str, Any]],
) -> DriftAdaptationPlan:
    """Fallback adaptation using Vector Search playbook field mappings when no API key is set."""
    mapping = playbooks[0].get("field_mapping", {}) if playbooks else {}
    adapted = {
        "service_name": original_payload.get("service_name", "payments-webhook"),
        "branch": original_payload.get("branch", "main"),
        "commit_sha": original_payload.get("commit_sha", "HEAD"),
        "callback_uri": original_payload.get(
            "webhook_url", "https://hooks.example.internal/v2/ingest"
        ),
        "max_rps": original_payload.get("rate_limit", 300),
        "env_tier": mapping.get("env_tier", "staging"),
        "idempotency_key": original_payload.get("idempotency_key", ""),
    }
    return DriftAdaptationPlan(
        diagnosis="Downstream API upgraded from /v1/deployments to /v2/deployments (callback_uri, max_rps, env_tier).",
        adapted_endpoint=mapping.get("endpoint", "/v2/deployments"),
        adapted_payload=adapted,
        field_mapping={
            "webhook_url": "callback_uri",
            "rate_limit": "max_rps",
            "env_tier": "staging",
        },
        confidence=0.92,
        needs_human_confirmation=False,
        question_for_operator="",
    )


async def plan_release_fix(
    issue_number: int,
    issue_title: str,
    issue_body: str,
    memories: list[dict[str, Any]],
    settings: Settings | None = None,
    model_override: Model | None = None,
    repo_files: list[str] | None = None,
    file_contents: dict[str, str] | None = None,
) -> FixPlan:
    """Plan the GitHub patch and deployment config using Pydantic AI + Vector Search context."""
    configure_observability()
    cfg = settings or get_settings()
    with trace(
        name="plan_release_fix",
        run_type="chain",
        inputs={
            "issue_number": issue_number,
            "issue_title": issue_title,
            "memory_count": len(memories),
            "repo_file_count": len(repo_files or []),
        },
    ) as ls_run:
        model = build_model(cfg, model_override)
        if model is None:
            plan = _deterministic_fix_plan(
                issue_number,
                issue_title,
                issue_body,
                repo_files=repo_files,
                file_contents=file_contents,
            )
            ls_run.end(outputs=plan.model_dump())
            return plan

        agent = create_planner_agent(model)
        memory_summary = "\n".join(
            f"- [{m.get('source_repo')}] {m.get('title')}: {m.get('resolution')}"
            for m in memories
        )
        tree_text = "\n".join(f"- {p}" for p in (repo_files or [])[:40]) or "(not inspected)"
        files_text = ""
        if file_contents:
            chunks = [
                f"### {path}\n```\n{body[:1500]}\n```"
                for path, body in list(file_contents.items())[:6]
            ]
            files_text = "\n\n".join(chunks)

        prompt = (
            f"GitHub Issue #{issue_number}: {issue_title}\n"
            f"Body:\n{issue_body}\n\n"
            f"Discovered Repository File Tree:\n{tree_text}\n\n"
            f"Relevant Existing File Contents:\n{files_text or 'None'}\n\n"
            f"Similar Past Experience (MongoDB Atlas Vector Search):\n{memory_summary or 'None'}\n\n"
            "Inspect the repository structure above, decide whether this repo uses OpenTofu "
            "(`target_kind='opentofu'` + `tf_dir`) or `service_config.json`, and generate the FixPlan."
        )
        result = await agent.run(prompt)
        ls_run.end(outputs=result.output.model_dump())
        return result.output


async def adapt_to_schema_drift(
    error_detail: str,
    openapi_excerpt: dict[str, Any],
    original_payload: dict[str, Any],
    playbooks: list[dict[str, Any]],
    settings: Settings | None = None,
    model_override: Model | None = None,
) -> DriftAdaptationPlan:
    """Adapt a failed deployment payload to a drifted v2 OpenAPI schema."""
    configure_observability()
    cfg = settings or get_settings()
    with trace(
        name="adapt_to_schema_drift",
        run_type="chain",
        inputs={
            "error_detail": error_detail[:300],
            "playbook_count": len(playbooks),
            "original_payload": original_payload,
        },
    ) as ls_run:
        model = build_model(cfg, model_override)
        if model is None:
            plan = _deterministic_drift_plan(original_payload, playbooks)
            ls_run.end(outputs=plan.model_dump())
            return plan

        agent = create_drift_agent(model)
        playbook_text = json.dumps(playbooks, indent=2, default=str)[:3000]
        openapi_text = json.dumps(openapi_excerpt, indent=2)[:4000]
        prompt = (
            f"Error from downstream target:\n{error_detail}\n\n"
            f"Original v1 payload:\n{json.dumps(original_payload, indent=2)}\n\n"
            f"Retrieved MongoDB Drift Playbooks:\n{playbook_text}\n\n"
            f"Live OpenAPI Spec Excerpt:\n{openapi_text}\n\n"
            "Produce the DriftAdaptationPlan preserving the original idempotency_key."
        )
        result = await agent.run(prompt)
        plan = result.output
        # Always preserve the exact idempotency_key across drift retries
        plan.adapted_payload["idempotency_key"] = original_payload.get(
            "idempotency_key", ""
        )
        ls_run.end(outputs=plan.model_dump())
        return plan
