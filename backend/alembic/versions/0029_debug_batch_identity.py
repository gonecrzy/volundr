"""record complete build identities for debug batches

Revision ID: 0029_debug_batch_identity
Revises: 0028_debug_batches
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0029_debug_batch_identity"
down_revision: str | None = "0028_debug_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "debug_batches",
        sa.Column("build_identities_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "debug_batches",
        sa.Column("identity_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("debug_batches", "identity_complete")
    op.drop_column("debug_batches", "build_identities_json")
