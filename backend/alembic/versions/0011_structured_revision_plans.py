"""structured revision plans

Revision ID: 0011_structured_revision_plans
Revises: 0010_multi_output_artifacts
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0011_structured_revision_plans"
down_revision: str | None = "0010_multi_output_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "revision_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("base_revision_id", sa.String(length=36), nullable=False),
        sa.Column("base_design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("base_design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("superseded_revision_plan_id", sa.String(length=36), nullable=True),
        sa.Column("generated_revision_id", sa.String(length=36), nullable=True),
        sa.Column("revised_design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("revised_design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=False),
        sa.Column("gemini_ruleset_version", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=True),
        sa.Column("user_instruction", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("raw_response_path", sa.String(length=500), nullable=True),
        sa.Column("plan_path", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("base_source_hash", sa.String(length=64), nullable=True),
        sa.Column("base_output_manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("base_design_specification_hash", sa.String(length=64), nullable=True),
        sa.Column("base_design_plan_hash", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("review_state", sa.String(length=40), nullable=False),
        sa.Column("clarification_required", sa.Boolean(), nullable=False),
        sa.Column("revision_ready", sa.Boolean(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["base_design_plan_id"], ["design_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["base_design_specification_id"],
            ["design_specifications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["base_revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["generation_attempt_id"],
            ["generation_attempts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["revised_design_plan_id"],
            ["design_plans.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["revised_design_specification_id"],
            ["design_specifications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_revision_plan_id"],
            ["revision_plans.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revision_plans_project_id", "revision_plans", ["project_id"])
    op.create_index("ix_revision_plans_base_revision_id", "revision_plans", ["base_revision_id"])
    op.create_index(
        "ix_revision_plans_base_design_specification_id",
        "revision_plans",
        ["base_design_specification_id"],
    )
    op.create_index("ix_revision_plans_base_design_plan_id", "revision_plans", ["base_design_plan_id"])
    op.create_index("ix_revision_plans_generation_attempt_id", "revision_plans", ["generation_attempt_id"])
    op.create_index("ix_revision_plans_generated_revision_id", "revision_plans", ["generated_revision_id"])

    op.create_table(
        "revision_plan_clarification_questions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=120), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_revision_plan_clarification_questions_project_id",
        "revision_plan_clarification_questions",
        ["project_id"],
    )
    op.create_index(
        "ix_revision_plan_clarification_questions_revision_plan_id",
        "revision_plan_clarification_questions",
        ["revision_plan_id"],
    )

    op.create_table(
        "revision_plan_clarification_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("related_requirement_id", sa.String(length=120), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["question_id"], ["revision_plan_clarification_questions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_revision_plan_clarification_answers_project_id",
        "revision_plan_clarification_answers",
        ["project_id"],
    )
    op.create_index(
        "ix_revision_plan_clarification_answers_revision_plan_id",
        "revision_plan_clarification_answers",
        ["revision_plan_id"],
    )
    op.create_index(
        "ix_revision_plan_clarification_answers_question_id",
        "revision_plan_clarification_answers",
        ["question_id"],
    )

    op.create_table(
        "revision_compliance_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=False),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("base_source_hash", sa.String(length=64), nullable=True),
        sa.Column("revised_source_hash", sa.String(length=64), nullable=True),
        sa.Column("result_path", sa.String(length=500), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("validation_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revision_compliance_results_project_id", "revision_compliance_results", ["project_id"])
    op.create_index(
        "ix_revision_compliance_results_revision_plan_id",
        "revision_compliance_results",
        ["revision_plan_id"],
    )
    op.create_index("ix_revision_compliance_results_revision_id", "revision_compliance_results", ["revision_id"])

    op.create_table(
        "revision_success_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("criterion_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=160), nullable=False),
        sa.Column("verification_state", sa.String(length=40), nullable=False),
        sa.Column("expected_value_json", sa.Text(), nullable=True),
        sa.Column("detected_value_json", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("tolerance", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_revision_success_results_project_id", "revision_success_results", ["project_id"])
    op.create_index(
        "ix_revision_success_results_revision_plan_id",
        "revision_success_results",
        ["revision_plan_id"],
    )
    op.create_index("ix_revision_success_results_revision_id", "revision_success_results", ["revision_id"])
    op.create_index(
        "ix_revision_success_results_generation_attempt_id",
        "revision_success_results",
        ["generation_attempt_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_revision_success_results_generation_attempt_id", table_name="revision_success_results")
    op.drop_index("ix_revision_success_results_revision_id", table_name="revision_success_results")
    op.drop_index("ix_revision_success_results_revision_plan_id", table_name="revision_success_results")
    op.drop_index("ix_revision_success_results_project_id", table_name="revision_success_results")
    op.drop_table("revision_success_results")

    op.drop_index("ix_revision_compliance_results_revision_id", table_name="revision_compliance_results")
    op.drop_index("ix_revision_compliance_results_revision_plan_id", table_name="revision_compliance_results")
    op.drop_index("ix_revision_compliance_results_project_id", table_name="revision_compliance_results")
    op.drop_table("revision_compliance_results")

    op.drop_index(
        "ix_revision_plan_clarification_answers_question_id",
        table_name="revision_plan_clarification_answers",
    )
    op.drop_index(
        "ix_revision_plan_clarification_answers_revision_plan_id",
        table_name="revision_plan_clarification_answers",
    )
    op.drop_index(
        "ix_revision_plan_clarification_answers_project_id",
        table_name="revision_plan_clarification_answers",
    )
    op.drop_table("revision_plan_clarification_answers")

    op.drop_index(
        "ix_revision_plan_clarification_questions_revision_plan_id",
        table_name="revision_plan_clarification_questions",
    )
    op.drop_index(
        "ix_revision_plan_clarification_questions_project_id",
        table_name="revision_plan_clarification_questions",
    )
    op.drop_table("revision_plan_clarification_questions")

    op.drop_index("ix_revision_plans_generated_revision_id", table_name="revision_plans")
    op.drop_index("ix_revision_plans_generation_attempt_id", table_name="revision_plans")
    op.drop_index("ix_revision_plans_base_design_plan_id", table_name="revision_plans")
    op.drop_index("ix_revision_plans_base_design_specification_id", table_name="revision_plans")
    op.drop_index("ix_revision_plans_base_revision_id", table_name="revision_plans")
    op.drop_index("ix_revision_plans_project_id", table_name="revision_plans")
    op.drop_table("revision_plans")
