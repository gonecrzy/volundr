from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RequirementLedgerEntry(Base):
    __tablename__ = "requirement_ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requirement_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    target_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_type: Mapped[str] = mapped_column(String(80), nullable=False)
    value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tolerance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    explicit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active", index=True)
    originating_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    originating_revision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    supersedes_requirement_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    superseded_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    verification_evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project = relationship("Project")
    revision = relationship("Revision")


class RequirementDelta(Base):
    __tablename__ = "requirement_deltas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_plan_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("revision_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_message_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project_messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation: Mapped[str] = mapped_column(String(24), nullable=False)
    requirement_id: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(48), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    originating_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    revision_plan = relationship("RevisionPlan")
    revision = relationship("Revision")
    project_message = relationship("ProjectMessage")


class PhysicalTestObservation(Base):
    __tablename__ = "physical_test_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("revisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    requirement_delta_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("requirement_deltas.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(48), nullable=False, default="physical_test_feedback")
    observation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    observation: Mapped[str] = mapped_column(Text, nullable=False)
    interpretation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    revision = relationship("Revision")
    requirement_delta = relationship("RequirementDelta")
