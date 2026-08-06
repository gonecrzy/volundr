from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidatedCadQueryOperation(Base):
    """Durable request identity for retry-safe product workflow mutations."""

    __tablename__ = "validated_cadquery_operations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "operation_type",
            "idempotency_key",
            name="uq_validated_cadquery_operation_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(240), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("validated_cadquery_workflows.id", ondelete="CASCADE"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
