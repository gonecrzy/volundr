from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DesignSpecification(Base):
    __tablename__ = "design_specifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    superseded_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(120), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    raw_response_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    specification_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    supported_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    clarification_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project", back_populates="design_specifications")
    generation_attempt = relationship("GenerationAttempt")
    superseded_specification = relationship("DesignSpecification", remote_side=[id])
    clarification_questions = relationship(
        "ClarificationQuestion",
        back_populates="design_specification",
        cascade="all, delete-orphan",
    )
