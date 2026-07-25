"""multi output artifacts

Revision ID: 0010_multi_output_artifacts
Revises: 0009_design_plans
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_multi_output_artifacts"
down_revision: str | Sequence[str] | None = "0009_design_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("revisions") as batch_op:
        batch_op.add_column(sa.Column("design_plan_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("output_manifest_path", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("expected_output_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("required_output_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("successful_output_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("blocked_output_count", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("failed_output_count", sa.Integer(), nullable=True))
        batch_op.create_index(op.f("ix_revisions_design_plan_id"), ["design_plan_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_revisions_design_plan_id",
            "design_plans",
            ["design_plan_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "revision_outputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("output_id", sa.String(length=120), nullable=False),
        sa.Column("component_id", sa.String(length=120), nullable=True),
        sa.Column("component_ids_json", sa.Text(), nullable=False),
        sa.Column("output_state", sa.String(length=40), nullable=False),
        sa.Column("output_type", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("module_name", sa.String(length=120), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("stl_path", sa.String(length=500), nullable=True),
        sa.Column("stl_hash", sa.String(length=64), nullable=True),
        sa.Column("compile_log_path", sa.String(length=500), nullable=True),
        sa.Column("compile_ms", sa.Float(), nullable=True),
        sa.Column("compile_error", sa.Text(), nullable=True),
        sa.Column("compile_command_json", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("validation_summary_json", sa.Text(), nullable=False),
        sa.Column("preferred_orientation_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["design_specification_id"],
            ["design_specifications.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_revision_outputs_design_plan_id"), "revision_outputs", ["design_plan_id"], unique=False)
    op.create_index(
        op.f("ix_revision_outputs_design_specification_id"),
        "revision_outputs",
        ["design_specification_id"],
        unique=False,
    )
    op.create_index(op.f("ix_revision_outputs_output_id"), "revision_outputs", ["output_id"], unique=False)
    op.create_index(op.f("ix_revision_outputs_revision_id"), "revision_outputs", ["revision_id"], unique=False)
    op.create_index(op.f("ix_revision_outputs_source_hash"), "revision_outputs", ["source_hash"], unique=False)
    op.create_index(op.f("ix_revision_outputs_stl_hash"), "revision_outputs", ["stl_hash"], unique=False)

    with op.batch_alter_table("validation_findings") as batch_op:
        batch_op.add_column(sa.Column("revision_output_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            op.f("ix_validation_findings_revision_output_id"),
            ["revision_output_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_validation_findings_revision_output_id",
            "revision_outputs",
            ["revision_output_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("geometric_analysis_results") as batch_op:
        batch_op.add_column(sa.Column("revision_output_id", sa.String(length=36), nullable=True))
        batch_op.create_index(
            op.f("ix_geometric_analysis_results_revision_output_id"),
            ["revision_output_id"],
            unique=False,
        )
        batch_op.create_foreign_key(
            "fk_geometric_analysis_results_revision_output_id",
            "revision_outputs",
            ["revision_output_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("geometric_analysis_results") as batch_op:
        batch_op.drop_constraint("fk_geometric_analysis_results_revision_output_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_geometric_analysis_results_revision_output_id"))
        batch_op.drop_column("revision_output_id")

    with op.batch_alter_table("validation_findings") as batch_op:
        batch_op.drop_constraint("fk_validation_findings_revision_output_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_validation_findings_revision_output_id"))
        batch_op.drop_column("revision_output_id")

    op.drop_index(op.f("ix_revision_outputs_stl_hash"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_source_hash"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_revision_id"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_output_id"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_design_specification_id"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_design_plan_id"), table_name="revision_outputs")
    op.drop_table("revision_outputs")

    with op.batch_alter_table("revisions") as batch_op:
        batch_op.drop_constraint("fk_revisions_design_plan_id", type_="foreignkey")
        batch_op.drop_index(op.f("ix_revisions_design_plan_id"))
        batch_op.drop_column("failed_output_count")
        batch_op.drop_column("blocked_output_count")
        batch_op.drop_column("successful_output_count")
        batch_op.drop_column("required_output_count")
        batch_op.drop_column("expected_output_count")
        batch_op.drop_column("output_manifest_path")
        batch_op.drop_column("design_plan_id")
