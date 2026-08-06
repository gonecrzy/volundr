"""add ownership, routing state, and durable operation identity

Revision ID: 0038_validated_cadquery_hardening
Revises: 0037_validated_cadquery_workflow
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0038_validated_cadquery_hardening"
down_revision: str | None = "0037_validated_cadquery_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "validated_cadquery_workflows",
        sa.Column("owner_id", sa.String(length=160), nullable=False, server_default="anonymous"),
    )
    op.add_column(
        "validated_cadquery_workflows",
        sa.Column("routing_state", sa.String(length=48), nullable=False, server_default="selected"),
    )
    op.add_column("validated_cadquery_workflows", sa.Column("failure_boundary", sa.String(length=80), nullable=True))
    op.add_column(
        "validated_cadquery_workflows",
        sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_validated_cadquery_workflows_owner_id",
        "validated_cadquery_workflows",
        ["owner_id"],
    )
    op.create_index(
        "ix_validated_cadquery_workflows_routing_state",
        "validated_cadquery_workflows",
        ["routing_state"],
    )

    op.create_table(
        "validated_cadquery_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=240), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="started"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["validated_cadquery_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "operation_type",
            "idempotency_key",
            name="uq_validated_cadquery_operation_identity",
        ),
    )
    op.create_index("ix_validated_cadquery_operations_owner_id", "validated_cadquery_operations", ["owner_id"])
    op.create_index("ix_validated_cadquery_operations_project_id", "validated_cadquery_operations", ["project_id"])
    op.create_index("ix_validated_cadquery_operations_workflow_id", "validated_cadquery_operations", ["workflow_id"])

    op.create_table(
        "validated_cadquery_provider_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("workflow_id", sa.String(length=36), nullable=True),
        sa.Column("logical_operation_id", sa.String(length=80), nullable=False),
        sa.Column("attempt_id", sa.String(length=80), nullable=False),
        sa.Column("credential_slot", sa.String(length=24), nullable=False),
        sa.Column("credential_env_var", sa.String(length=80), nullable=False),
        sa.Column("credential_present", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("failure_class", sa.String(length=64), nullable=True),
        sa.Column("retry_delay_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["validated_cadquery_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id"),
    )
    op.create_index("ix_validated_cadquery_provider_attempts_project_id", "validated_cadquery_provider_attempts", ["project_id"])
    op.create_index("ix_validated_cadquery_provider_attempts_workflow_id", "validated_cadquery_provider_attempts", ["workflow_id"])
    op.create_index("ix_validated_cadquery_provider_attempts_logical_operation_id", "validated_cadquery_provider_attempts", ["logical_operation_id"])


def downgrade() -> None:
    op.drop_index("ix_validated_cadquery_provider_attempts_logical_operation_id", table_name="validated_cadquery_provider_attempts")
    op.drop_index("ix_validated_cadquery_provider_attempts_workflow_id", table_name="validated_cadquery_provider_attempts")
    op.drop_index("ix_validated_cadquery_provider_attempts_project_id", table_name="validated_cadquery_provider_attempts")
    op.drop_table("validated_cadquery_provider_attempts")
    op.drop_index("ix_validated_cadquery_operations_workflow_id", table_name="validated_cadquery_operations")
    op.drop_index("ix_validated_cadquery_operations_project_id", table_name="validated_cadquery_operations")
    op.drop_index("ix_validated_cadquery_operations_owner_id", table_name="validated_cadquery_operations")
    op.drop_table("validated_cadquery_operations")
    op.drop_index("ix_validated_cadquery_workflows_routing_state", table_name="validated_cadquery_workflows")
    op.drop_index("ix_validated_cadquery_workflows_owner_id", table_name="validated_cadquery_workflows")
    op.drop_column("validated_cadquery_workflows", "state_version")
    op.drop_column("validated_cadquery_workflows", "failure_boundary")
    op.drop_column("validated_cadquery_workflows", "routing_state")
    op.drop_column("validated_cadquery_workflows", "owner_id")
