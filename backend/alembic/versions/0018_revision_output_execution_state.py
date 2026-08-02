"""revision output execution state

Revision ID: 0018_revision_output_execution_state
Revises: 0017_generation_attempt_canonical_fields
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0018_revision_output_execution_state"
down_revision: str | None = "0017_generation_attempt_canonical_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.alter_column("output_state", new_column_name="execution_state")


def downgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.alter_column("execution_state", new_column_name="output_state")
