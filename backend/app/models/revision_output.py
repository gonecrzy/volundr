from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RevisionOutput(Base):
    __tablename__ = "revision_outputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    output_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    component_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    component_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    output_state: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    output_type: Mapped[str] = mapped_column(String(80), nullable=False, default="printable_component")
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    module_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    stl_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stl_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    compile_log_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    compile_ms: Mapped[float | None] = mapped_column(nullable=True)
    compile_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    compile_command_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    validation_summary_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    preferred_orientation_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision = relationship("Revision", back_populates="outputs")
    design_plan = relationship("DesignPlan")
    design_specification = relationship("DesignSpecification")
