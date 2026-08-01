"""persist selected revision exports

Revision ID: 0027_export_records
Revises: 0026_requirement_ledger
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0027_export_records"
down_revision: str | None = "0026_requirement_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "export_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("export_type", sa.String(length=40), nullable=False),
        sa.Column("selection_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("filename", sa.String(length=260), nullable=False),
        sa.Column("output_path", sa.String(length=700), nullable=True),
        sa.Column("component_ids_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_export_records_project_id", "export_records", ["project_id"])
    op.create_index("ix_export_records_revision_id", "export_records", ["revision_id"])
    op.create_index("ix_export_records_export_type", "export_records", ["export_type"])
    op.create_index("ix_export_records_selection_hash", "export_records", ["selection_hash"])
    op.create_index("ix_export_records_sha256", "export_records", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_export_records_sha256", table_name="export_records")
    op.drop_index("ix_export_records_selection_hash", table_name="export_records")
    op.drop_index("ix_export_records_export_type", table_name="export_records")
    op.drop_index("ix_export_records_revision_id", table_name="export_records")
    op.drop_index("ix_export_records_project_id", table_name="export_records")
    op.drop_table("export_records")
