"""geometric analysis results

Revision ID: 0008_geometric_analysis_results
Revises: 0007_source_contract_validation
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_geometric_analysis_results"
down_revision: str | Sequence[str] | None = "0007_source_contract_validation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "geometric_analysis_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("analysis_version", sa.String(length=120), nullable=False),
        sa.Column("tolerance_profile_version", sa.String(length=120), nullable=False),
        sa.Column("mesh_hash", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("result_path", sa.String(length=500), nullable=False),
        sa.Column("analysis_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_geometric_analysis_results_design_specification_id"),
        "geometric_analysis_results",
        ["design_specification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_geometric_analysis_results_mesh_hash"),
        "geometric_analysis_results",
        ["mesh_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_geometric_analysis_results_revision_id"),
        "geometric_analysis_results",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_geometric_analysis_results_source_hash"),
        "geometric_analysis_results",
        ["source_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_geometric_analysis_results_source_hash"), table_name="geometric_analysis_results")
    op.drop_index(op.f("ix_geometric_analysis_results_revision_id"), table_name="geometric_analysis_results")
    op.drop_index(op.f("ix_geometric_analysis_results_mesh_hash"), table_name="geometric_analysis_results")
    op.drop_index(
        op.f("ix_geometric_analysis_results_design_specification_id"),
        table_name="geometric_analysis_results",
    )
    op.drop_table("geometric_analysis_results")
