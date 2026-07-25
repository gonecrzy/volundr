"""candidate revisions

Revision ID: 0005_candidate_revisions
Revises: 0004_generation_attempts
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_candidate_revisions"
down_revision: str | Sequence[str] | None = "0004_generation_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("revisions", sa.Column("review_state", sa.String(length=40), nullable=True))
    op.add_column("revisions", sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("revisions", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        """
        UPDATE revisions
        SET review_state = 'accepted',
            accepted_at = created_at
        WHERE status = 'succeeded'
          AND is_accepted = 1
        """
    )
    op.create_table(
        "validation_findings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("revision_id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("suggested_correction", sa.Text(), nullable=False),
        sa.Column("detected_value", sa.String(length=120), nullable=True),
        sa.Column("unit", sa.String(length=40), nullable=True),
        sa.Column("threshold_value", sa.String(length=120), nullable=True),
        sa.Column("orientation_dependent", sa.Boolean(), nullable=False),
        sa.Column("affected_geometry_summary", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("finding_state", sa.String(length=40), nullable=False),
        sa.Column("dismissal_reason", sa.Text(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_validation_findings_revision_id"),
        "validation_findings",
        ["revision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_validation_findings_rule_id"),
        "validation_findings",
        ["rule_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_validation_findings_rule_id"), table_name="validation_findings")
    op.drop_index(op.f("ix_validation_findings_revision_id"), table_name="validation_findings")
    op.drop_table("validation_findings")
    op.drop_column("revisions", "rejected_at")
    op.drop_column("revisions", "accepted_at")
    op.drop_column("revisions", "review_state")
