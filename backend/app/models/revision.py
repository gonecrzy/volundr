from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Revision(Base):
    __tablename__ = "revisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id"),
        nullable=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    user_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    scad_source_path: Mapped[str] = mapped_column(String(500), nullable=False)
    stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    compile_log_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ai_output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    is_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project", back_populates="revisions", foreign_keys=[project_id])
    parent_revision = relationship("Revision", remote_side=[id])
    validation_findings = relationship(
        "ValidationFinding",
        back_populates="revision",
        cascade="all, delete-orphan",
    )
