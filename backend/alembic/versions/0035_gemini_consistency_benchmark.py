"""add API-driven Gemini consistency benchmark persistence

Revision ID: 0035_gemini_consistency_benchmark
Revises: 0034_revision_output_feature_trace_status
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0035_gemini_consistency_benchmark"
down_revision: str | None = "0034_revision_output_feature_trace_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gemini_benchmark_experiments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("corpus_version", sa.String(length=120), nullable=False),
        sa.Column("corpus_hash", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False),
        sa.Column("requested_runs", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("git_head", sa.String(length=80), nullable=False),
        sa.Column("migration_head", sa.String(length=120), nullable=False),
        sa.Column("prompt_versions_json", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("build_identities_json", sa.Text(), nullable=False),
        sa.Column("model_settings_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_root", sa.String(length=700), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_gemini_benchmark_experiments_state", "gemini_benchmark_experiments", ["state"])

    op.create_table(
        "gemini_benchmark_models",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("requested_model", sa.String(length=160), nullable=False),
        sa.Column("actual_model", sa.String(length=160), nullable=True),
        sa.Column("availability_state", sa.String(length=32), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["gemini_benchmark_experiments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "requested_model", name="uq_gemini_benchmark_model_request"),
        sa.UniqueConstraint("experiment_id", "position", name="uq_gemini_benchmark_model_position"),
    )
    op.create_index("ix_gemini_benchmark_models_experiment_id", "gemini_benchmark_models", ["experiment_id"])

    op.create_table(
        "gemini_benchmark_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("model_config_id", sa.String(length=36), nullable=False),
        sa.Column("run_index", sa.Integer(), nullable=False),
        sa.Column("stable_run_key", sa.String(length=300), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("identity_json", sa.Text(), nullable=False),
        sa.Column("report_path", sa.String(length=700), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["experiment_id"], ["gemini_benchmark_experiments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_config_id"], ["gemini_benchmark_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("experiment_id", "model_config_id", "run_index", name="uq_gemini_benchmark_run_matrix"),
        sa.UniqueConstraint("stable_run_key", name="uq_gemini_benchmark_stable_run_key"),
    )
    op.create_index("ix_gemini_benchmark_runs_experiment_id", "gemini_benchmark_runs", ["experiment_id"])
    op.create_index("ix_gemini_benchmark_runs_model_config_id", "gemini_benchmark_runs", ["model_config_id"])
    op.create_index("ix_gemini_benchmark_runs_state", "gemini_benchmark_runs", ["state"])

    op.create_table(
        "gemini_benchmark_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("corpus_case_id", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("stable_project_key", sa.String(length=360), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("clarification_rounds", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("outcome_category", sa.String(length=80), nullable=True),
        sa.Column("outcome_state", sa.String(length=120), nullable=True),
        sa.Column("final_outcome", sa.Text(), nullable=True),
        sa.Column("metrics_json", sa.Text(), nullable=False),
        sa.Column("evidence_path", sa.String(length=700), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["gemini_benchmark_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "corpus_case_id", name="uq_gemini_benchmark_membership_case"),
        sa.UniqueConstraint("run_id", "position", name="uq_gemini_benchmark_membership_position"),
        sa.UniqueConstraint("stable_project_key", name="uq_gemini_benchmark_stable_project_key"),
    )
    op.create_index("ix_gemini_benchmark_memberships_run_id", "gemini_benchmark_memberships", ["run_id"])
    op.create_index("ix_gemini_benchmark_memberships_project", "gemini_benchmark_memberships", ["project_id"])
    op.create_index("ix_gemini_benchmark_memberships_state", "gemini_benchmark_memberships", ["state"])


def downgrade() -> None:
    op.drop_index("ix_gemini_benchmark_memberships_state", table_name="gemini_benchmark_memberships")
    op.drop_index("ix_gemini_benchmark_memberships_project", table_name="gemini_benchmark_memberships")
    op.drop_index("ix_gemini_benchmark_memberships_run_id", table_name="gemini_benchmark_memberships")
    op.drop_table("gemini_benchmark_memberships")
    op.drop_index("ix_gemini_benchmark_runs_state", table_name="gemini_benchmark_runs")
    op.drop_index("ix_gemini_benchmark_runs_model_config_id", table_name="gemini_benchmark_runs")
    op.drop_index("ix_gemini_benchmark_runs_experiment_id", table_name="gemini_benchmark_runs")
    op.drop_table("gemini_benchmark_runs")
    op.drop_index("ix_gemini_benchmark_models_experiment_id", table_name="gemini_benchmark_models")
    op.drop_table("gemini_benchmark_models")
    op.drop_index("ix_gemini_benchmark_experiments_state", table_name="gemini_benchmark_experiments")
    op.drop_table("gemini_benchmark_experiments")
