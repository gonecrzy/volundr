"""design artifact consistency

Revision ID: 0020_design_artifact_consistency
Revises: 0019_revision_output_parameter_hash
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0020_design_artifact_consistency"
down_revision: str | None = "0019_revision_output_parameter_hash"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "design_artifact_consistency_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("validator_version", sa.String(length=120), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("parameter_hash", sa.String(length=64), nullable=True),
        sa.Column("output_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("result_path", sa.String(length=500), nullable=False),
        sa.Column("pre_execution_passed", sa.Boolean(), nullable=False),
        sa.Column("post_execution_passed", sa.Boolean(), nullable=False),
        sa.Column("revision_base_ready", sa.Boolean(), nullable=False),
        sa.Column("configuration_ready", sa.Boolean(), nullable=False),
        sa.Column("validation_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_design_artifact_consistency_results_project_id",
        "design_artifact_consistency_results",
        ["project_id"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_revision_id",
        "design_artifact_consistency_results",
        ["revision_id"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_design_specification_id",
        "design_artifact_consistency_results",
        ["design_specification_id"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_design_plan_id",
        "design_artifact_consistency_results",
        ["design_plan_id"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_generation_attempt_id",
        "design_artifact_consistency_results",
        ["generation_attempt_id"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_source_hash",
        "design_artifact_consistency_results",
        ["source_hash"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_parameter_hash",
        "design_artifact_consistency_results",
        ["parameter_hash"],
    )
    op.create_index(
        "ix_design_artifact_consistency_results_output_manifest_hash",
        "design_artifact_consistency_results",
        ["output_manifest_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_design_artifact_consistency_results_output_manifest_hash", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_parameter_hash", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_source_hash", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_generation_attempt_id", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_design_plan_id", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_design_specification_id", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_revision_id", table_name="design_artifact_consistency_results")
    op.drop_index("ix_design_artifact_consistency_results_project_id", table_name="design_artifact_consistency_results")
    op.drop_table("design_artifact_consistency_results")
