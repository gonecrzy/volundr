from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConfigurationChange(Base):
    __tablename__ = "configuration_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generated_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    design_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="configuration-change-v1")
    reason: Mapped[str] = mapped_column(String(80), nullable=False, default="parameter_change")
    selected_preset_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    validation_state: Mapped[str] = mapped_column(String(60), nullable=False)
    base_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_changes_json: Mapped[str] = mapped_column(Text, nullable=False)
    preset_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    user_overrides_json: Mapped[str] = mapped_column(Text, nullable=False)
    resolved_parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    affected_parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    affected_components_json: Mapped[str] = mapped_column(Text, nullable=False)
    affected_outputs_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_errors_json: Mapped[str] = mapped_column(Text, nullable=False)
    override_manifest_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    configuration_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project = relationship("Project")
    base_revision = relationship("Revision", foreign_keys=[base_revision_id])
    generated_revision = relationship("Revision", foreign_keys=[generated_revision_id])
    design_plan = relationship("DesignPlan")
    design_specification = relationship("DesignSpecification")


class ConfigurationPreset(Base):
    __tablename__ = "configuration_presets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    preset_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    parameter_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    design_plan = relationship("DesignPlan")
