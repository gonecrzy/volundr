"""add developer live debug batch persistence

Revision ID: 0028_debug_batches
Revises: 0027_export_records
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0028_debug_batches"
down_revision: str | None = "0027_export_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "debug_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("target_project_count", sa.Integer(), nullable=False),
        sa.Column("baseline_batch_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("git_head", sa.String(length=80), nullable=False),
        sa.Column("branch", sa.String(length=240), nullable=False),
        sa.Column("migration_head", sa.String(length=120), nullable=False),
        sa.Column("application_version", sa.String(length=160), nullable=False),
        sa.Column("frontend_build_identity", sa.String(length=160), nullable=False),
        sa.Column("backend_build_identity", sa.String(length=160), nullable=False),
        sa.Column("worker_build_identity", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("configured_default_model", sa.String(length=160), nullable=False),
        sa.Column("stage_model_policy_json", sa.Text(), nullable=False),
        sa.Column("actual_provider_models_json", sa.Text(), nullable=False),
        sa.Column("prompt_versions_json", sa.Text(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_path", sa.String(length=700), nullable=True),
        sa.Column("report_generation_state", sa.String(length=32), nullable=False),
        sa.Column("evidence_contract_version", sa.String(length=80), nullable=False),
        sa.Column("comparison_status", sa.String(length=32), nullable=False),
        sa.Column("redaction_status", sa.String(length=32), nullable=False),
        sa.Column("integrity_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["baseline_batch_id"], ["debug_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_debug_batches_baseline_batch_id", "debug_batches", ["baseline_batch_id"])
    op.create_index("ix_debug_batches_state", "debug_batches", ["state"])
    op.create_index(
        "uq_debug_batches_open_state",
        "debug_batches",
        ["state"],
        unique=True,
        sqlite_where=sa.text("state IN ('active', 'finishing')"),
    )

    op.create_table(
        "debug_batch_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["debug_batches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "project_id", name="uq_debug_batch_membership_batch_project"),
        sa.UniqueConstraint("batch_id", "position", name="uq_debug_batch_membership_batch_position"),
        sa.UniqueConstraint("project_id", name="uq_debug_batch_membership_project"),
    )
    op.create_index("ix_debug_batch_memberships_batch_id", "debug_batch_memberships", ["batch_id"])
    op.create_index("ix_debug_batch_memberships_project_id", "debug_batch_memberships", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_debug_batch_memberships_project_id", table_name="debug_batch_memberships")
    op.drop_index("ix_debug_batch_memberships_batch_id", table_name="debug_batch_memberships")
    op.drop_table("debug_batch_memberships")
    op.drop_index("uq_debug_batches_open_state", table_name="debug_batches")
    op.drop_index("ix_debug_batches_state", table_name="debug_batches")
    op.drop_index("ix_debug_batches_baseline_batch_id", table_name="debug_batches")
    op.drop_table("debug_batches")
