"""project messages

Revision ID: 0002_project_messages
Revises: 0001_project_revision_base
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_project_messages"
down_revision: str | Sequence[str] | None = "0001_project_revision_base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_project_messages_project_id"),
        "project_messages",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_messages_project_id"), table_name="project_messages")
    op.drop_table("project_messages")
