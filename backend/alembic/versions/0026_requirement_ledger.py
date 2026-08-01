"""persist active requirement ledger and physical-test feedback

Revision ID: 0026_requirement_ledger
Revises: 0025_generation_attempt_routing
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0026_requirement_ledger"
down_revision: str | None = "0025_generation_attempt_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "requirement_ledger_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("requirement_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("target_json", sa.Text(), nullable=True),
        sa.Column("requirement_type", sa.String(length=80), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("tolerance_json", sa.Text(), nullable=True),
        sa.Column("explicit", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("originating_message", sa.Text(), nullable=True),
        sa.Column("originating_revision_id", sa.String(length=36), nullable=True),
        sa.Column("supersedes_requirement_id", sa.String(length=160), nullable=True),
        sa.Column("superseded_by", sa.String(length=160), nullable=True),
        sa.Column("verification_evidence_json", sa.Text(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_ledger_entries_project_id", "requirement_ledger_entries", ["project_id"])
    op.create_index("ix_requirement_ledger_entries_revision_id", "requirement_ledger_entries", ["revision_id"])
    op.create_index("ix_requirement_ledger_entries_requirement_id", "requirement_ledger_entries", ["requirement_id"])
    op.create_index("ix_requirement_ledger_entries_status", "requirement_ledger_entries", ["status"])

    op.create_table(
        "requirement_deltas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("project_message_id", sa.String(length=36), nullable=True),
        sa.Column("operation", sa.String(length=24), nullable=False),
        sa.Column("requirement_id", sa.String(length=160), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("originating_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_plan_id"], ["revision_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_message_id"], ["project_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_requirement_deltas_project_id", "requirement_deltas", ["project_id"])
    op.create_index("ix_requirement_deltas_revision_plan_id", "requirement_deltas", ["revision_plan_id"])
    op.create_index("ix_requirement_deltas_revision_id", "requirement_deltas", ["revision_id"])
    op.create_index("ix_requirement_deltas_project_message_id", "requirement_deltas", ["project_message_id"])
    op.create_index("ix_requirement_deltas_requirement_id", "requirement_deltas", ["requirement_id"])

    op.create_table(
        "physical_test_observations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("requirement_delta_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("observation_type", sa.String(length=80), nullable=False),
        sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("interpretation_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_delta_id"], ["requirement_deltas.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_physical_test_observations_project_id", "physical_test_observations", ["project_id"])
    op.create_index("ix_physical_test_observations_revision_id", "physical_test_observations", ["revision_id"])
    op.create_index("ix_physical_test_observations_requirement_delta_id", "physical_test_observations", ["requirement_delta_id"])


def downgrade() -> None:
    op.drop_index("ix_physical_test_observations_requirement_delta_id", table_name="physical_test_observations")
    op.drop_index("ix_physical_test_observations_revision_id", table_name="physical_test_observations")
    op.drop_index("ix_physical_test_observations_project_id", table_name="physical_test_observations")
    op.drop_table("physical_test_observations")
    op.drop_index("ix_requirement_deltas_requirement_id", table_name="requirement_deltas")
    op.drop_index("ix_requirement_deltas_project_message_id", table_name="requirement_deltas")
    op.drop_index("ix_requirement_deltas_revision_id", table_name="requirement_deltas")
    op.drop_index("ix_requirement_deltas_revision_plan_id", table_name="requirement_deltas")
    op.drop_index("ix_requirement_deltas_project_id", table_name="requirement_deltas")
    op.drop_table("requirement_deltas")
    op.drop_index("ix_requirement_ledger_entries_status", table_name="requirement_ledger_entries")
    op.drop_index("ix_requirement_ledger_entries_requirement_id", table_name="requirement_ledger_entries")
    op.drop_index("ix_requirement_ledger_entries_revision_id", table_name="requirement_ledger_entries")
    op.drop_index("ix_requirement_ledger_entries_project_id", table_name="requirement_ledger_entries")
    op.drop_table("requirement_ledger_entries")
