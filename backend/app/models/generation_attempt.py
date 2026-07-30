from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.services.generation.failure_taxonomy import FailureClass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    resulting_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prompt_template_version: Mapped[str] = mapped_column(String(120), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    cad_backend: Mapped[str] = mapped_column(String(40), nullable=False, default="openscad")
    source_language: Mapped[str] = mapped_column(String(40), nullable=False, default="openscad")
    source_contract_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    request_payload_path: Mapped[str] = mapped_column(String(500), nullable=False)
    prompt_path: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    extracted_source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    intermediate_artifacts_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    design_spec_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    design_plan_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="started")
    failure_class: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default=FailureClass.NONE.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="generation_attempts")
    base_revision = relationship("Revision", foreign_keys=[base_revision_id])
    resulting_revision = relationship("Revision", foreign_keys=[resulting_revision_id])
