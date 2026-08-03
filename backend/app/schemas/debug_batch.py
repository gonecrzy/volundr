from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DebugBatchStart(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    target_project_count: int = Field(default=5, ge=1, le=20)
    notes: str | None = Field(default=None, max_length=12000)
    baseline_batch_id: str | None = Field(default=None, min_length=1, max_length=36)
    frontend_build_identity: str = Field(default="frontend-dev", min_length=1, max_length=160)

    @field_validator("label")
    @classmethod
    def trim_label(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("batch label cannot be blank")
        return trimmed

    @field_validator("notes")
    @classmethod
    def trim_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None


class DebugBatchMembershipRead(BaseModel):
    project_id: str
    position: int
    project_name: str | None = None
    missing: bool = False
    workflow_phase: str = "Not started"
    worker_reached: bool = False
    current_working_revision_id: str | None = None
    attempt_count: int = 0
    retry_count: int = 0
    provider_call_count: int = 0
    provider_retry_count: int = 0
    content_repair_count: int = 0
    generation_attempt_count: int = 0
    workflow_stage_attempt_count: int = 0
    user_operation_count: int = 0
    outcome_category: str = "not_started"
    final_outcome: str = "Not started"


class DebugBatchRead(BaseModel):
    id: str
    label: str
    notes: str | None
    target_project_count: int
    baseline_batch_id: str | None
    state: str
    git_head: str
    branch: str
    migration_head: str
    application_version: str
    frontend_build_identity: str
    backend_build_identity: str
    worker_build_identity: str
    build_identities: dict[str, Any] = Field(default_factory=dict)
    identity_complete: bool = False
    provider: str
    configured_default_model: str
    stage_model_policy: dict[str, Any]
    actual_provider_models: dict[str, Any]
    prompt_versions: dict[str, Any]
    configuration_hash: str
    started_at: datetime
    finished_at: datetime | None
    report_path: str | None
    report_generation_state: str
    evidence_contract_version: str
    comparison_status: str
    redaction_status: str
    integrity_status: str
    memberships: list[DebugBatchMembershipRead] = Field(default_factory=list)


class DebugBatchFrontendEvent(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    safe_endpoint_path: str | None = Field(default=None, max_length=240)
    project_id: str | None = Field(default=None, max_length=36)
    revision_id: str | None = Field(default=None, max_length=36)
    workflow_id: str | None = Field(default=None, max_length=36)
    visible_error_kind: str | None = Field(default=None, max_length=120)
    http_status: int | None = Field(default=None, ge=100, le=599)
    occurred_at: datetime


class DebugBatchFrontendEventsCreate(BaseModel):
    events: list[DebugBatchFrontendEvent] = Field(min_length=1, max_length=25)


class DebugBatchFrontendEventsRead(BaseModel):
    accepted_count: int


class DebugBatchSummary(BaseModel):
    batch: DebugBatchRead
    summary: dict[str, Any]
    report_path: str | None = None
    codex_review_instruction: str | None = None


class DebugBatchComparisonRead(BaseModel):
    batch_id: str
    baseline_batch_id: str
    status: str
    identity_match: bool
    mismatches: dict[str, dict[str, Any]] = Field(default_factory=dict)
    identity_evidence: dict[str, Any] = Field(default_factory=dict)
    project_comparisons: list[dict[str, Any]] = Field(default_factory=list)
