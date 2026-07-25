from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidationFinding(Base):
    __tablename__ = "validation_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    revision_output_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revision_outputs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_validation_result_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_validation_results.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_correction: Mapped[str] = mapped_column(Text, nullable=False)
    detected_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    threshold_value: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_line_start: Mapped[int | None] = mapped_column(nullable=True)
    source_line_end: Mapped[int | None] = mapped_column(nullable=True)
    orientation_dependent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    affected_geometry_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    finding_state: Mapped[str] = mapped_column(String(40), nullable=False, default="open")
    dismissal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision = relationship("Revision", back_populates="validation_findings")
    revision_output = relationship("RevisionOutput")
    generation_attempt = relationship("GenerationAttempt")
    design_specification = relationship("DesignSpecification")
    source_validation_result = relationship("SourceValidationResult")
