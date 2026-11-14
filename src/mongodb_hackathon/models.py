"""Domain models for runs, checkpoints, verification probes, drift playbooks, and events."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class RunStatus(StrEnum):
    """Lifecycle status of an end-to-end job run."""

    PENDING = "pending"
    RUNNING = "running"
    CRASHED = "crashed"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class StepStatus(StrEnum):
    """Checkpoint state for a single idempotent step."""

    PENDING = "pending"
    SENT_UNVERIFIED = "sent_unverified"
    VERIFIED_TOOK_EFFECT = "verified_took_effect"
    DRIFTED = "drifted"
    ADAPTED = "adapted"
    BLOCKED_POLICY = "blocked_policy"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class ChaosMode(StrEnum):
    """Chaos injection modes supported by the target microservice."""

    NORMAL = "normal"
    SILENT_DROP_202 = "silent_drop_202"
    DRIFT_V2 = "drift_v2"
    REQUIRE_APPROVAL_GATE = "require_approval_gate"


class StepCheckpoint(BaseModel):
    """Persisted checkpoint document for a workflow step."""

    run_id: str
    step_key: str
    step_seq: int
    title: str
    idempotency_key: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    took_effect: bool = False
    sent_payload: dict[str, Any] = Field(default_factory=dict)
    probe_result: dict[str, Any] = Field(default_factory=dict)
    pre_state: dict[str, Any] = Field(default_factory=dict)
    post_state: dict[str, Any] = Field(default_factory=dict)
    compensating_action: dict[str, Any] = Field(default_factory=dict)
    external_ref: str = ""
    adaptation_used: str = ""
    error_message: str = ""
    updated_at: datetime = Field(default_factory=utc_now)


class JobRun(BaseModel):
    """Top-level MongoDB document tracking a multi-system release/remediation job."""

    run_id: str
    repo: str
    issue_number: int
    issue_title: str
    issue_body: str
    target_service_url: str
    status: RunStatus = RunStatus.PENDING
    current_step: int = 0
    worker_pid: int | None = None
    halt_requested: bool = False
    approval_granted: bool = False
    approval_note: str = ""
    step_mode: str = "auto"  # "auto" | "step_by_step"
    step_paused: bool = False
    step_gate_approved: bool = False
    paused_after_step: int = 0
    voice_audio_path: str = ""
    voice_briefing_text: str = ""
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DemoRepo(BaseModel):
    """Curated repository entry stored in the MongoDB Atlas `demo_repos` registry."""

    repo: str
    label: str
    description: str = ""
    is_live: bool = False
    default_prompt: str = ""
    created_at: datetime = Field(default_factory=utc_now)


PACING_PRESETS: dict[str, float] = {
    "fast": 0.1,
    "demo": 0.5,
    "slow": 2.5,
}


class ExperienceMemory(BaseModel):
    """Past fix, repo rule, or OpenAPI schema-drift playbook stored for Vector Search recall."""

    memory_id: str
    kind: str  # "github_fix" | "drift_playbook" | "repo_rule"
    source_repo: str
    title: str
    content: str
    resolution: str
    field_mapping: dict[str, str] = Field(default_factory=dict)
    status: str = "active"  # "active" | "invalidated"
    embedding: list[float] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ServiceEvent(BaseModel):
    """Append-only operational event watched via MongoDB Change Streams and auto-expired via TTL."""

    run_id: str
    step_key: str
    event_type: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime = Field(default_factory=lambda: utc_now() + timedelta(days=7))


class DriftAdaptationPlan(BaseModel):
    """Structured output returned by Pydantic AI when adapting to a drifted downstream schema."""

    diagnosis: str
    adapted_endpoint: str
    adapted_payload: dict[str, Any]
    field_mapping: dict[str, str]
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human_confirmation: bool = False
    question_for_operator: str = ""


class FixPlan(BaseModel):
    """Structured release/remediation plan produced by Pydantic AI for an issue."""

    root_cause: str
    patch_filename: str
    patch_content: str
    commit_message: str
    deployment_config: dict[str, Any]
    pr_title: str
    pr_body: str
