from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DesignArtifactConsistencyResult(Base):
    __tablename__ = "design_artifact_consistency_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    design_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    parameter_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    output_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pre_execution_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    post_execution_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision_base_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    configuration_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    revision = relationship("Revision")
    design_specification = relationship("DesignSpecification")
    design_plan = relationship("DesignPlan")
    generation_attempt = relationship("GenerationAttempt")
