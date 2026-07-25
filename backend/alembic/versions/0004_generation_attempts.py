"""generation attempts

Revision ID: 0004_generation_attempts
Revises: 0003_printability_profiles
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_generation_attempts"
down_revision: str | Sequence[str] | None = "0003_printability_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("base_revision_id", sa.String(length=36), nullable=True),
        sa.Column("resulting_revision_id", sa.String(length=36), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("provider_model", sa.String(length=120), nullable=True),
        sa.Column("provider_settings_json", sa.Text(), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=False),
        sa.Column("gemini_ruleset_version", sa.String(length=120), nullable=False),
        sa.Column("request_payload_path", sa.String(length=500), nullable=False),
        sa.Column("prompt_path", sa.String(length=500), nullable=False),
        sa.Column("raw_output_path", sa.String(length=500), nullable=True),
        sa.Column("extracted_source_path", sa.String(length=500), nullable=True),
        sa.Column("intermediate_artifacts_path", sa.String(length=500), nullable=True),
        sa.Column("design_spec_path", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("failure_class", sa.String(length=80), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["base_revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resulting_revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_generation_attempts_project_id"),
        "generation_attempts",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_generation_attempts_project_id"), table_name="generation_attempts")
    op.drop_table("generation_attempts")
