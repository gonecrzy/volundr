from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RevisionPlan(Base):
    __tablename__ = "revision_plans"

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
    base_design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    base_design_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    superseded_revision_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    generated_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revised_design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
    )
    revised_design_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(120), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    user_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    raw_response_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    plan_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    base_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_output_manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_design_specification_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_design_plan_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[str] = mapped_column(String(40), nullable=False)
    clarification_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    base_revision = relationship("Revision", foreign_keys=[base_revision_id])
    base_design_specification = relationship(
        "DesignSpecification",
        foreign_keys=[base_design_specification_id],
    )
    base_design_plan = relationship("DesignPlan", foreign_keys=[base_design_plan_id])
    generation_attempt = relationship("GenerationAttempt")
    superseded_revision_plan = relationship("RevisionPlan", remote_side=[id])
    generated_revision = relationship("Revision", foreign_keys=[generated_revision_id])
    clarification_questions = relationship(
        "RevisionPlanClarificationQuestion",
        back_populates="revision_plan",
        cascade="all, delete-orphan",
    )


class RevisionPlanClarificationQuestion(Base):
    __tablename__ = "revision_plan_clarification_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision_plan = relationship("RevisionPlan", back_populates="clarification_questions")


class RevisionPlanClarificationAnswer(Base):
    __tablename__ = "revision_plan_clarification_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plan_clarification_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision_plan = relationship("RevisionPlan")
    question = relationship("RevisionPlanClarificationQuestion")


class RevisionComplianceResult(Base):
    __tablename__ = "revision_compliance_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    base_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revised_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_path: Mapped[str] = mapped_column(String(500), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision_plan = relationship("RevisionPlan")


class RevisionSuccessResult(Base):
    __tablename__ = "revision_success_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    criterion_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    verification_state: Mapped[str] = mapped_column(String(40), nullable=False)
    expected_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tolerance: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    is_blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision_plan = relationship("RevisionPlan")


class ComponentRevisionSummary(Base):
    __tablename__ = "component_revision_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_plan_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revision_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    base_revision_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    base_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    revised_source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    equivalence_profile_version: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="output-preservation-v1",
    )
    summary_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision_plan = relationship("RevisionPlan")
    revision = relationship("Revision", foreign_keys=[revision_id])
    base_revision = relationship("Revision", foreign_keys=[base_revision_id])
    generation_attempt = relationship("GenerationAttempt")
