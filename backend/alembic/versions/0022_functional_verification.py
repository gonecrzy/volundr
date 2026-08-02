"""store functional readiness separately from structural review state

Revision ID: 0022_functional_verification
Revises: 0021_workflow_observability
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0022_functional_verification"
down_revision: str | None = "0021_workflow_observability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revisions",
        sa.Column(
            "functional_status",
            sa.String(length=48),
            nullable=False,
            server_default="functionally_unverified",
        ),
    )


def downgrade() -> None:
    op.drop_column("revisions", "functional_status")
