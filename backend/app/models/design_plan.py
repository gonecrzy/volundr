from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DesignPlan(Base):
    __tablename__ = "design_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_specification_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    generation_attempt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_attempts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    superseded_design_plan_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_template_version: Mapped[str] = mapped_column(String(120), nullable=False)
    gemini_ruleset_version: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_response_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    plan_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    review_state: Mapped[str] = mapped_column(String(40), nullable=False)
    clarification_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    plan_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    design_specification = relationship("DesignSpecification")
    generation_attempt = relationship("GenerationAttempt")
    superseded_design_plan = relationship("DesignPlan", remote_side=[id])
    clarification_questions = relationship(
        "DesignPlanClarificationQuestion",
        back_populates="design_plan",
        cascade="all, delete-orphan",
    )


class DesignPlanClarificationQuestion(Base):
    __tablename__ = "design_plan_clarification_questions"

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
    related_plan_field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    design_plan = relationship("DesignPlan", back_populates="clarification_questions")


class DesignPlanClarificationAnswer(Base):
    __tablename__ = "design_plan_clarification_answers"

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
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("design_plan_clarification_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_plan_field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    design_plan = relationship("DesignPlan")
    question = relationship("DesignPlanClarificationQuestion")
