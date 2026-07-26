"""design plan clarifications

Revision ID: 0014_design_plan_clarifications
Revises: 0013_component_revision_summaries
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0014_design_plan_clarifications"
down_revision: str | None = "0013_component_revision_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "design_plan_clarification_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("design_plan_id", sa.String(length=36), nullable=False),
        sa.Column("related_plan_field", sa.String(length=120), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_design_plan_clarification_questions_design_plan_id"),
        "design_plan_clarification_questions",
        ["design_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_plan_clarification_questions_project_id"),
        "design_plan_clarification_questions",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "design_plan_clarification_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("design_plan_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("related_plan_field", sa.String(length=120), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["design_plan_clarification_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_design_plan_clarification_answers_design_plan_id"),
        "design_plan_clarification_answers",
        ["design_plan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_plan_clarification_answers_project_id"),
        "design_plan_clarification_answers",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_plan_clarification_answers_question_id"),
        "design_plan_clarification_answers",
        ["question_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_design_plan_clarification_answers_question_id"), table_name="design_plan_clarification_answers")
    op.drop_index(op.f("ix_design_plan_clarification_answers_project_id"), table_name="design_plan_clarification_answers")
    op.drop_index(op.f("ix_design_plan_clarification_answers_design_plan_id"), table_name="design_plan_clarification_answers")
    op.drop_table("design_plan_clarification_answers")
    op.drop_index(op.f("ix_design_plan_clarification_questions_project_id"), table_name="design_plan_clarification_questions")
    op.drop_index(op.f("ix_design_plan_clarification_questions_design_plan_id"), table_name="design_plan_clarification_questions")
    op.drop_table("design_plan_clarification_questions")
