"""component revision summaries

Revision ID: 0013_component_revision_summaries
Revises: 0012_configuration_changes
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0013_component_revision_summaries"
down_revision: str | None = "0012_configuration_changes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "component_revision_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("base_revision_id", sa.String(length=36), nullable=True),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("base_source_hash", sa.String(length=64), nullable=True),
        sa.Column("revised_source_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "equivalence_profile_version",
            sa.String(length=80),
            nullable=False,
            server_default="output-preservation-v1",
        ),
        sa.Column("summary_path", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["base_revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_component_revision_summaries_base_revision_id"),
        "component_revision_summaries",
        ["base_revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_component_revision_summaries_project_id"),
        "component_revision_summaries",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_component_revision_summaries_revision_id"),
        "component_revision_summaries",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_component_revision_summaries_revision_plan_id"),
        "component_revision_summaries",
        ["revision_plan_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_component_revision_summaries_revision_plan_id"), table_name="component_revision_summaries")
    op.drop_index(op.f("ix_component_revision_summaries_revision_id"), table_name="component_revision_summaries")
    op.drop_index(op.f("ix_component_revision_summaries_project_id"), table_name="component_revision_summaries")
    op.drop_index(op.f("ix_component_revision_summaries_base_revision_id"), table_name="component_revision_summaries")
    op.drop_table("component_revision_summaries")
