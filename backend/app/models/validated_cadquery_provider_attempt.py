from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidatedCadQueryProviderAttempt(Base):
    __tablename__ = "validated_cadquery_provider_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("validated_cadquery_workflows.id", ondelete="CASCADE"), nullable=True, index=True)
    logical_operation_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    credential_slot: Mapped[str] = mapped_column(String(24), nullable=False)
    credential_env_var: Mapped[str] = mapped_column(String(80), nullable=False)
    credential_present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_delay_seconds: Mapped[float | None] = mapped_column(nullable=True)
    request_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_received: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    response_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_response_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    exception_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    normalized_transport_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    transport_retry_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rate_limit_429_classification: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
