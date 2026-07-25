from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClarificationAnswer(Base):
    __tablename__ = "clarification_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clarification_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    design_specification_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    related_requirement_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    question = relationship("ClarificationQuestion", back_populates="answers")
