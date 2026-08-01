from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExportRecord(Base):
    __tablename__ = "export_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("revisions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    export_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    selection_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="started")
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    output_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    component_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
    revision = relationship("Revision")
