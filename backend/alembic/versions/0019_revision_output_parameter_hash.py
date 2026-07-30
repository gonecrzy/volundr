"""revision output parameter hash

Revision ID: 0019_revision_output_parameter_hash
Revises: 0018_revision_output_execution_state
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0019_revision_output_parameter_hash"
down_revision: str | None = "0018_revision_output_execution_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.add_column(sa.Column("parameter_hash", sa.String(length=64), nullable=True))
        batch.create_index("ix_revision_outputs_parameter_hash", ["parameter_hash"])


def downgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.drop_index("ix_revision_outputs_parameter_hash")
        batch.drop_column("parameter_hash")
