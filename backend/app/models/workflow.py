from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    parent_workflow_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    root_workflow_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="running", index=True)
    logging_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    event_schema_version: Mapped[str] = mapped_column(String(80), nullable=False, default="workflow-event-v1")
    diagnosis_version: Mapped[str] = mapped_column(String(80), nullable=False, default="workflow-diagnosis-v1")
    redaction_version: Mapped[str] = mapped_column(String(80), nullable=False, default="workflow-redaction-v1")
    application_commit: Mapped[str | None] = mapped_column(String(80), nullable=True)
    worker_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    workflow_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parent_workflow_run = relationship(
        "WorkflowRun",
        remote_side=[id],
        foreign_keys=[parent_workflow_run_id],
    )


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id",
            "deduplication_key",
            name="uq_workflow_events_run_deduplication_key",
        ),
        UniqueConstraint(
            "workflow_run_id",
            "sequence_number",
            name="uq_workflow_events_run_sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    root_workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    generation_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    design_specification_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    design_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision_output_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    configuration_change_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    worker_job_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    stage: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rule_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    expected_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    caused_by_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_root_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_downstream_symptom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deduplication_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    workflow_run = relationship("WorkflowRun")


class WorkflowArtifact(Base):
    __tablename__ = "workflow_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    root_workflow_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    path: Mapped[str] = mapped_column(String(700), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    redaction_status: Mapped[str] = mapped_column(String(40), nullable=False, default="not_required")
    supersedes_artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    artifact_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workflow_run = relationship("WorkflowRun")


class WorkflowDiagnosis(Base):
    __tablename__ = "workflow_diagnoses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False, default="workflow-diagnosis-v1")
    root_cause_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    repairs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    downstream_effects_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    final_outcome: Mapped[str] = mapped_column(String(80), nullable=False, default="unknown")
    basis_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workflow_run = relationship("WorkflowRun")

    @property
    def root_cause(self) -> dict:
        import json

        return json.loads(self.root_cause_json)

    @property
    def downstream_effects(self) -> list[dict]:
        import json

        return json.loads(self.downstream_effects_json)

    @property
    def repairs(self) -> list[dict]:
        import json

        return json.loads(self.repairs_json)

    @property
    def basis(self) -> dict:
        import json

        return json.loads(self.basis_json)


class FrontendWorkflowEvent(Base):
    __tablename__ = "frontend_workflow_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    frontend_session_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    route: Mapped[str] = mapped_column(String(240), nullable=False)
    action_name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    user_visible_state: Mapped[str] = mapped_column(String(120), nullable=False)
    backend_request_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    workflow_run = relationship("WorkflowRun")
