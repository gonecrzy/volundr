from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


VALIDATED_WORKFLOW_STATES = {
    "awaiting_clarification",
    "requirements_ready",
    "plan_ready",
    "geometry_generating",
    "worker_running",
    "partially_completed",
    "verification_failed",
    "candidate_ready",
    "revision_ready",
    "failed",
}

VALIDATED_OUTPUT_STATES = {
    "pending",
    "completed",
    "invalid_shape",
    "semantic_verification_failed",
    "worker_timeout",
    "export_failed",
    "not_generated",
    "blocked_by_upstream_failure",
}


class ValidatedCadQueryWorkflow(Base):
    __tablename__ = "validated_cadquery_workflows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False, default="anonymous", index=True)
    parent_workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("validated_cadquery_workflows.id", ondelete="SET NULL"), nullable=True
    )
    parent_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    design_specification_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    design_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(48), nullable=False, default="requirements_ready", index=True)
    routing_state: Mapped[str] = mapped_column(String(48), nullable=False, default="selected", index=True)
    failure_boundary: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    route: Mapped[str] = mapped_column(String(120), nullable=False, default="validated-cadquery-v1")
    user_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    requirements_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    verification_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    diagnostics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    package_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    package_manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project = relationship("Project")
    parent_workflow = relationship("ValidatedCadQueryWorkflow", remote_side=[id])
    outputs = relationship(
        "ValidatedCadQueryOutput",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="ValidatedCadQueryOutput.output_id",
    )


class ValidatedCadQueryOutput(Base):
    __tablename__ = "validated_cadquery_outputs"
    __table_args__ = (
        UniqueConstraint("workflow_id", "output_id", name="uq_validated_cadquery_output"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("validated_cadquery_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    output_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    revision_output_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    generation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    worker_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    state: Mapped[str] = mapped_column(String(56), nullable=False, default="pending", index=True)
    solid_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    topology_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    semantic_verification: Mapped[str | None] = mapped_column(String(56), nullable=True)
    artifact_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failure_owner: Mapped[str | None] = mapped_column(String(56), nullable=True)
    safe_diagnostic: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    workflow = relationship("ValidatedCadQueryWorkflow", back_populates="outputs")
