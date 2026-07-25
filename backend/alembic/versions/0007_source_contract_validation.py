"""source contract validation

Revision ID: 0007_source_contract_validation
Revises: 0006_design_specifications
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_source_contract_validation"
down_revision: str | Sequence[str] | None = "0006_design_specifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_validation_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=False),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("contract_version", sa.String(length=80), nullable=False),
        sa.Column("ruleset_version", sa.String(length=120), nullable=False),
        sa.Column("validator_version", sa.String(length=120), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("result_path", sa.String(length=500), nullable=False),
        sa.Column("passed_hard_checks", sa.Boolean(), nullable=False),
        sa.Column("validation_ms", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_validation_results_design_specification_id"),
        "source_validation_results",
        ["design_specification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_validation_results_generation_attempt_id"),
        "source_validation_results",
        ["generation_attempt_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_validation_results_project_id"),
        "source_validation_results",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_validation_results_revision_id"),
        "source_validation_results",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_validation_results_source_hash"),
        "source_validation_results",
        ["source_hash"],
        unique=False,
    )

    with op.batch_alter_table("validation_findings") as batch_op:
        batch_op.alter_column("revision_id", existing_type=sa.String(length=36), nullable=True)
        batch_op.add_column(sa.Column("generation_attempt_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("design_specification_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_validation_result_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("source_line_start", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source_line_end", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_validation_findings_generation_attempt_id",
            "generation_attempts",
            ["generation_attempt_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_validation_findings_design_specification_id",
            "design_specifications",
            ["design_specification_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_validation_findings_source_validation_result_id",
            "source_validation_results",
            ["source_validation_result_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            batch_op.f("ix_validation_findings_generation_attempt_id"),
            ["generation_attempt_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_validation_findings_design_specification_id"),
            ["design_specification_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_validation_findings_source_validation_result_id"),
            ["source_validation_result_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("validation_findings") as batch_op:
        batch_op.drop_index(batch_op.f("ix_validation_findings_source_validation_result_id"))
        batch_op.drop_index(batch_op.f("ix_validation_findings_design_specification_id"))
        batch_op.drop_index(batch_op.f("ix_validation_findings_generation_attempt_id"))
        batch_op.drop_constraint(
            "fk_validation_findings_source_validation_result_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint("fk_validation_findings_design_specification_id", type_="foreignkey")
        batch_op.drop_constraint("fk_validation_findings_generation_attempt_id", type_="foreignkey")
        batch_op.drop_column("source_line_end")
        batch_op.drop_column("source_line_start")
        batch_op.drop_column("source_validation_result_id")
        batch_op.drop_column("design_specification_id")
        batch_op.drop_column("generation_attempt_id")
        batch_op.alter_column("revision_id", existing_type=sa.String(length=36), nullable=False)

    op.drop_index(op.f("ix_source_validation_results_source_hash"), table_name="source_validation_results")
    op.drop_index(op.f("ix_source_validation_results_revision_id"), table_name="source_validation_results")
    op.drop_index(op.f("ix_source_validation_results_project_id"), table_name="source_validation_results")
    op.drop_index(
        op.f("ix_source_validation_results_generation_attempt_id"),
        table_name="source_validation_results",
    )
    op.drop_index(
        op.f("ix_source_validation_results_design_specification_id"),
        table_name="source_validation_results",
    )
    op.drop_table("source_validation_results")
