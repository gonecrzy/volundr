from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GeminiBenchmarkExperiment(Base):
    __tablename__ = "gemini_benchmark_experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    corpus_version: Mapped[str] = mapped_column(String(120), nullable=False)
    corpus_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    requested_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    git_head: Mapped[str] = mapped_column(String(80), nullable=False)
    migration_head: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_versions_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    build_identities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    report_root: Mapped[str] = mapped_column(String(700), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    models = relationship("GeminiBenchmarkModel", back_populates="experiment", cascade="all, delete-orphan", order_by="GeminiBenchmarkModel.position")
    runs = relationship("GeminiBenchmarkRun", back_populates="experiment", cascade="all, delete-orphan", order_by="GeminiBenchmarkRun.run_index")


class GeminiBenchmarkModel(Base):
    __tablename__ = "gemini_benchmark_models"
    __table_args__ = (
        UniqueConstraint("experiment_id", "requested_model", name="uq_gemini_benchmark_model_request"),
        UniqueConstraint("experiment_id", "position", name="uq_gemini_benchmark_model_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_id: Mapped[str] = mapped_column(String(36), ForeignKey("gemini_benchmark_experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="gemini_api")
    requested_model: Mapped[str] = mapped_column(String(160), nullable=False)
    actual_model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    actual_digest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    availability_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model_metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    resource_profile_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    experiment = relationship("GeminiBenchmarkExperiment", back_populates="models")
    runs = relationship("GeminiBenchmarkRun", back_populates="model_config", cascade="all, delete-orphan", order_by="GeminiBenchmarkRun.run_index")


class GeminiBenchmarkRun(Base):
    __tablename__ = "gemini_benchmark_runs"
    __table_args__ = (
        UniqueConstraint("experiment_id", "model_config_id", "run_index", name="uq_gemini_benchmark_run_matrix"),
        UniqueConstraint("stable_run_key", name="uq_gemini_benchmark_stable_run_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    experiment_id: Mapped[str] = mapped_column(String(36), ForeignKey("gemini_benchmark_experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    model_config_id: Mapped[str] = mapped_column(String(36), ForeignKey("gemini_benchmark_models.id", ondelete="CASCADE"), nullable=False, index=True)
    run_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stable_run_key: Mapped[str] = mapped_column(String(300), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    identity_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    report_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    experiment = relationship("GeminiBenchmarkExperiment", back_populates="runs")
    model_config = relationship("GeminiBenchmarkModel", back_populates="runs")
    memberships = relationship("GeminiBenchmarkMembership", back_populates="run", cascade="all, delete-orphan", order_by="GeminiBenchmarkMembership.position")


class GeminiBenchmarkMembership(Base):
    __tablename__ = "gemini_benchmark_memberships"
    __table_args__ = (
        UniqueConstraint("run_id", "corpus_case_id", name="uq_gemini_benchmark_membership_case"),
        UniqueConstraint("run_id", "position", name="uq_gemini_benchmark_membership_position"),
        UniqueConstraint("stable_project_key", name="uq_gemini_benchmark_stable_project_key"),
        Index("ix_gemini_benchmark_memberships_project", "project_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("gemini_benchmark_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    corpus_case_id: Mapped[str] = mapped_column(String(32), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    stable_project_key: Mapped[str] = mapped_column(String(360), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="planned", index=True)
    clarification_rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    outcome_state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    final_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    evidence_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    run = relationship("GeminiBenchmarkRun", back_populates="memberships")
