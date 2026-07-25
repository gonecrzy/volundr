"""project and revision base tables

Revision ID: 0001_project_revision_base
Revises:
Create Date: 2026-07-24
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_project_revision_base"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=220), nullable=False),
        sa.Column("original_intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("active_revision_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["active_revision_id"],
            ["revisions.id"],
            name="fk_projects_active_revision_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_projects_slug"), "projects", ["slug"], unique=False)

    op.create_table(
        "revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("parent_revision_id", sa.String(length=36), nullable=True),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("user_instruction", sa.Text(), nullable=True),
        sa.Column("scad_source_path", sa.String(length=500), nullable=False),
        sa.Column("stl_path", sa.String(length=500), nullable=True),
        sa.Column("compile_log_path", sa.String(length=500), nullable=True),
        sa.Column("ai_output_path", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("is_accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_revision_id"], ["revisions.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_revisions_project_id"), "revisions", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_revisions_project_id"), table_name="revisions")
    op.drop_table("revisions")
    op.drop_index(op.f("ix_projects_slug"), table_name="projects")
    op.drop_table("projects")
