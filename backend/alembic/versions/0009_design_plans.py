"""design plans

Revision ID: 0009_design_plans
Revises: 0008_geometric_analysis_results
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_design_plans"
down_revision: str | Sequence[str] | None = "0008_geometric_analysis_results"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generation_attempts", sa.Column("design_plan_path", sa.String(length=500), nullable=True))
    op.create_table(
        "design_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=False),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=False),
        sa.Column("gemini_ruleset_version", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=True),
        sa.Column("raw_response_path", sa.String(length=500), nullable=True),
        sa.Column("plan_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("review_state", sa.String(length=40), nullable=False),
        sa.Column("clarification_required", sa.Boolean(), nullable=False),
        sa.Column("plan_ready", sa.Boolean(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["superseded_design_plan_id"], ["design_plans.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_design_plans_design_specification_id"), "design_plans", ["design_specification_id"], unique=False)
    op.create_index(op.f("ix_design_plans_generation_attempt_id"), "design_plans", ["generation_attempt_id"], unique=False)
    op.create_index(op.f("ix_design_plans_project_id"), "design_plans", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_design_plans_project_id"), table_name="design_plans")
    op.drop_index(op.f("ix_design_plans_generation_attempt_id"), table_name="design_plans")
    op.drop_index(op.f("ix_design_plans_design_specification_id"), table_name="design_plans")
    op.drop_table("design_plans")
    op.drop_column("generation_attempts", "design_plan_path")
