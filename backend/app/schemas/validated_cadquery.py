from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ValidatedCadQueryStart(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=20_000)


class ValidatedClarificationAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=120)
    answer: str = Field(min_length=1, max_length=4_000)


class ValidatedClarificationSubmit(BaseModel):
    answers: list[ValidatedClarificationAnswer] = Field(min_length=1, max_length=20)


class ValidatedBoundedRevision(BaseModel):
    instruction: str = Field(min_length=1, max_length=8_000)
    dimension_changes: dict[str, float | int | str] = Field(default_factory=dict)
    added_features: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    protected_facts: list[str] = Field(default_factory=list, max_length=40)


class ValidatedIndependentReviewSubmit(BaseModel):
    """The narrow persisted input from the blind final-package reviewer."""

    reviewer: str = Field(default="blind_codex_cad_qa_v1", min_length=1, max_length=120)
    review_cycle: int = Field(default=1, ge=1, le=3)
    final_verdict: Literal["PASS", "FAIL", "UNCERTAIN"]
    requirements: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    revision_preservation: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    discrepancies: list[str] = Field(default_factory=list, max_length=100)


class ValidatedOutputRead(BaseModel):
    output_id: str
    required: bool
    generation_status: str
    worker_status: str
    state: str
    solid_count: int | None = None
    topology_status: str | None = None
    semantic_verification: str | None = None
    artifact_available: bool
    failure_owner: str | None = None
    safe_diagnostic: str | None = None
    artifact_metadata: dict[str, Any] = Field(default_factory=dict)


class ValidatedArtifactRead(BaseModel):
    artifact_id: str
    kind: str
    output_id: str | None = None
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    available: bool
    download_url: str | None = None


class ValidatedWorkflowRead(BaseModel):
    id: str
    project_id: str
    parent_workflow_id: str | None = None
    parent_revision_id: str | None = None
    revision_id: str | None = None
    state: str
    route: str
    user_instruction: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    plan: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    concept_state: Literal["concept_unavailable", "concept_available"] | None = None
    candidate_policy: dict[str, Any] = Field(default_factory=dict)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    package_manifest: dict[str, Any] = Field(default_factory=dict)
    package_available: bool = False
    outputs: list[ValidatedOutputRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ValidatedRequirementsRead(BaseModel):
    workflow_id: str
    requirements: dict[str, Any] = Field(default_factory=dict)


class ValidatedPlanRead(BaseModel):
    workflow_id: str
    plan: dict[str, Any] = Field(default_factory=dict)


class ValidatedVerificationRead(BaseModel):
    workflow_id: str
    state: str
    verification: dict[str, Any] = Field(default_factory=dict)
    concept_state: Literal["concept_unavailable", "concept_available"] | None = None
    candidate_policy: dict[str, Any] = Field(default_factory=dict)
    outputs: list[ValidatedOutputRead] = Field(default_factory=list)


class ValidatedDiagnosticsRead(BaseModel):
    workflow_id: str
    diagnostics: dict[str, Any] = Field(default_factory=dict)
