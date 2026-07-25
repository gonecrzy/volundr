"""design specifications

Revision ID: 0006_design_specifications
Revises: 0005_candidate_revisions
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_design_specifications"
down_revision: str | Sequence[str] | None = "0005_candidate_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "design_specifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_specification_id", sa.String(length=36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=False),
        sa.Column("gemini_ruleset_version", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=True),
        sa.Column("user_instruction", sa.Text(), nullable=False),
        sa.Column("raw_response_path", sa.String(length=500), nullable=True),
        sa.Column("specification_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("supported_scope", sa.Boolean(), nullable=False),
        sa.Column("clarification_required", sa.Boolean(), nullable=False),
        sa.Column("generation_ready", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["superseded_specification_id"],
            ["design_specifications.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_design_specifications_generation_attempt_id"),
        "design_specifications",
        ["generation_attempt_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_design_specifications_project_id"),
        "design_specifications",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "clarification_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=120), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clarification_questions_design_specification_id"),
        "clarification_questions",
        ["design_specification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_questions_project_id"),
        "clarification_questions",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "clarification_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=False),
        sa.Column("related_requirement_id", sa.String(length=120), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["clarification_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_clarification_answers_design_specification_id"),
        "clarification_answers",
        ["design_specification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_answers_project_id"),
        "clarification_answers",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_clarification_answers_question_id"),
        "clarification_answers",
        ["question_id"],
        unique=False,
    )
    with op.batch_alter_table("revisions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "design_specification_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "design_specifications.id",
                    name="fk_revisions_design_specification_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.create_index(
            batch_op.f("ix_revisions_design_specification_id"),
            ["design_specification_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("revisions") as batch_op:
        batch_op.drop_index(batch_op.f("ix_revisions_design_specification_id"))
        batch_op.drop_column("design_specification_id")
    op.drop_index(op.f("ix_clarification_answers_question_id"), table_name="clarification_answers")
    op.drop_index(op.f("ix_clarification_answers_project_id"), table_name="clarification_answers")
    op.drop_index(
        op.f("ix_clarification_answers_design_specification_id"),
        table_name="clarification_answers",
    )
    op.drop_table("clarification_answers")
    op.drop_index(op.f("ix_clarification_questions_project_id"), table_name="clarification_questions")
    op.drop_index(
        op.f("ix_clarification_questions_design_specification_id"),
        table_name="clarification_questions",
    )
    op.drop_table("clarification_questions")
    op.drop_index(op.f("ix_design_specifications_project_id"), table_name="design_specifications")
    op.drop_index(
        op.f("ix_design_specifications_generation_attempt_id"),
        table_name="design_specifications",
    )
    op.drop_table("design_specifications")
