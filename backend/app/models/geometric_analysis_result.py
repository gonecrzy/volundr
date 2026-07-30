from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeometricAnalysisResult(Base):
    __tablename__ = "geometric_analysis_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    revision_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_output_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("revision_outputs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    design_specification_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("design_specifications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    analysis_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="mesh")
    analysis_version: Mapped[str] = mapped_column(String(120), nullable=False)
    tolerance_profile_version: Mapped[str] = mapped_column(String(120), nullable=False)
    mesh_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_path: Mapped[str] = mapped_column(String(500), nullable=False)
    analysis_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    revision = relationship("Revision")
    revision_output = relationship("RevisionOutput")
    design_specification = relationship("DesignSpecification")
