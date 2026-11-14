"""Pydantic AI agents for release planning and schema-drift adaptation with LangSmith + Logfire."""

from __future__ import annotations

import json
import os
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
    """Create Pydantic AI agent that converts a GitHub issue + past experience into a FixPlan."""
    return Agent(
        model,
        name="finishline_release_planner",
        output_type=FixPlan,
        instructions=(
            "You are a senior release reliability engineer. Given a GitHub issue, current service "
            "configuration, and similar historical resolutions from MongoDB Atlas Vector Search, "
            "produce a clean, minimal FixPlan updating service_config.json, a deployment_config dict "
            "compatible with /v1/deployments (webhook_url, rate_limit), and a concise PR summary."
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
            "valid DriftAdaptationPlan with the new endpoint path, full adapted_payload JSON, "
            "exact field_mapping, confidence (0..1), and whether human confirmation is needed."
        ),
    )


def _deterministic_fix_plan(
    issue_number: int, issue_title: str, issue_body: str
) -> FixPlan:
    """Deterministic fallback plan used only when OPENAI_API_KEY is unset (offline dry-run)."""
    rate_limit = 300 if "300" in issue_body or "burst" in issue_body.lower() else 250
    cfg = {
        "service_name": "payments-webhook",
        "webhook_url": "https://hooks.example.internal/v1/ingest",
        "rate_limit": rate_limit,
        "env_tier": "staging",
    }
    return FixPlan(
        root_cause=f"Address issue #{issue_number} ({issue_title}) by tuning rate_limit={rate_limit}.",
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
        },
    ) as ls_run:
        model = build_model(cfg, model_override)
        if model is None:
            plan = _deterministic_fix_plan(issue_number, issue_title, issue_body)
            ls_run.end(outputs=plan.model_dump())
            return plan

        agent = create_planner_agent(model)
        memory_summary = "\n".join(
            f"- [{m.get('source_repo')}] {m.get('title')}: {m.get('resolution')}"
            for m in memories
        )
        prompt = (
            f"GitHub Issue #{issue_number}: {issue_title}\n"
            f"Body:\n{issue_body}\n\n"
            f"Similar Past Experience (MongoDB Atlas Vector Search):\n{memory_summary or 'None'}\n\n"
            "Generate a FixPlan targeting `service_config.json`."
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
