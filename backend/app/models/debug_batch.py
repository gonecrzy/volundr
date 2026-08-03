from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DebugBatch(Base):
    __tablename__ = "debug_batches"
    __table_args__ = (
        Index(
            "uq_debug_batches_open_state",
            "state",
            unique=True,
            sqlite_where=text("state IN ('active', 'finishing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_project_count: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_batch_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("debug_batches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    git_head: Mapped[str] = mapped_column(String(80), nullable=False)
    branch: Mapped[str] = mapped_column(String(240), nullable=False)
    migration_head: Mapped[str] = mapped_column(String(120), nullable=False)
    application_version: Mapped[str] = mapped_column(String(160), nullable=False)
    frontend_build_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    backend_build_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    worker_build_identity: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    configured_default_model: Mapped[str] = mapped_column(String(160), nullable=False)
    stage_model_policy_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    actual_provider_models_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    prompt_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    report_generation_state: Mapped[str] = mapped_column(String(32), nullable=False, default="not_started")
    evidence_contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_applicable")
    redaction_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    integrity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    memberships = relationship(
        "DebugBatchMembership",
        back_populates="batch",
        cascade="all, delete-orphan",
        order_by="DebugBatchMembership.position",
    )
    baseline_batch = relationship("DebugBatch", remote_side=[id], foreign_keys=[baseline_batch_id])


class DebugBatchMembership(Base):
    __tablename__ = "debug_batch_memberships"
    __table_args__ = (
        UniqueConstraint("batch_id", "project_id", name="uq_debug_batch_membership_batch_project"),
        UniqueConstraint("batch_id", "position", name="uq_debug_batch_membership_batch_position"),
        UniqueConstraint("project_id", name="uq_debug_batch_membership_project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    batch_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("debug_batches.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # This deliberately remains a stable identifier rather than a cascading
    # project relationship so a deleted project can be reported as missing.
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    batch = relationship("DebugBatch", back_populates="memberships")
