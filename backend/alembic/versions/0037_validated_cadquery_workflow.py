"""persist product-facing validated CadQuery workflow state

Revision ID: 0037_validated_cadquery_workflow
Revises: 0036_benchmark_model_metadata
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0037_validated_cadquery_workflow"
down_revision: str | None = "0036_benchmark_model_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validated_cadquery_workflows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("parent_workflow_id", sa.String(length=36), nullable=True),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=48), nullable=False, server_default="requirements_ready"),
        sa.Column("route", sa.String(length=120), nullable=False, server_default="validated-cadquery-v1"),
        sa.Column("user_instruction", sa.Text(), nullable=False),
        sa.Column("requirements_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("plan_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("provenance_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("verification_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("diagnostics_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("package_path", sa.String(length=700), nullable=True),
        sa.Column("package_manifest_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_workflow_id"], ["validated_cadquery_workflows.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validated_cadquery_workflows_project_id", "validated_cadquery_workflows", ["project_id"])
    op.create_index("ix_validated_cadquery_workflows_parent_revision_id", "validated_cadquery_workflows", ["parent_revision_id"])
    op.create_index("ix_validated_cadquery_workflows_revision_id", "validated_cadquery_workflows", ["revision_id"])
    op.create_index("ix_validated_cadquery_workflows_design_specification_id", "validated_cadquery_workflows", ["design_specification_id"])
    op.create_index("ix_validated_cadquery_workflows_design_plan_id", "validated_cadquery_workflows", ["design_plan_id"])
    op.create_index("ix_validated_cadquery_workflows_state", "validated_cadquery_workflows", ["state"])

    op.create_table(
        "validated_cadquery_outputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_id", sa.String(length=36), nullable=False),
        sa.Column("output_id", sa.String(length=120), nullable=False),
        sa.Column("revision_output_id", sa.String(length=36), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("generation_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("worker_status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("state", sa.String(length=56), nullable=False, server_default="pending"),
        sa.Column("solid_count", sa.Integer(), nullable=True),
        sa.Column("topology_status", sa.String(length=40), nullable=True),
        sa.Column("semantic_verification", sa.String(length=56), nullable=True),
        sa.Column("artifact_available", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("failure_owner", sa.String(length=56), nullable=True),
        sa.Column("safe_diagnostic", sa.Text(), nullable=True),
        sa.Column("artifact_metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["validated_cadquery_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "output_id", name="uq_validated_cadquery_output"),
    )
    op.create_index("ix_validated_cadquery_outputs_workflow_id", "validated_cadquery_outputs", ["workflow_id"])
    op.create_index("ix_validated_cadquery_outputs_output_id", "validated_cadquery_outputs", ["output_id"])
    op.create_index("ix_validated_cadquery_outputs_revision_output_id", "validated_cadquery_outputs", ["revision_output_id"])
    op.create_index("ix_validated_cadquery_outputs_state", "validated_cadquery_outputs", ["state"])


def downgrade() -> None:
    op.drop_index("ix_validated_cadquery_outputs_state", table_name="validated_cadquery_outputs")
    op.drop_index("ix_validated_cadquery_outputs_revision_output_id", table_name="validated_cadquery_outputs")
    op.drop_index("ix_validated_cadquery_outputs_output_id", table_name="validated_cadquery_outputs")
    op.drop_index("ix_validated_cadquery_outputs_workflow_id", table_name="validated_cadquery_outputs")
    op.drop_table("validated_cadquery_outputs")
    op.drop_index("ix_validated_cadquery_workflows_state", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_revision_id", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_design_specification_id", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_design_plan_id", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_parent_revision_id", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_project_id", table_name="validated_cadquery_workflows")
    op.drop_table("validated_cadquery_workflows")
