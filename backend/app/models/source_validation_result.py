from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceValidationResult(Base):
    __tablename__ = "source_validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_attempt_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    validator_id: Mapped[str] = mapped_column(String(120), nullable=False, default="openscad-static-validator")
    cad_backend: Mapped[str] = mapped_column(String(40), nullable=False, default="openscad")
    source_language: Mapped[str] = mapped_column(String(40), nullable=False, default="openscad")
    contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    validator_version: Mapped[str] = mapped_column(String(120), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result_path: Mapped[str] = mapped_column(String(500), nullable=False)
    passed_hard_checks: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    generation_attempt = relationship("GenerationAttempt")
    design_specification = relationship("DesignSpecification")
    revision = relationship("Revision")
