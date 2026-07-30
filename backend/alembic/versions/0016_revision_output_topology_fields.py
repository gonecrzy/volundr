"""revision output topology fields

Revision ID: 0016_revision_output_topology_fields
Revises: 0015_cadquery_native_persistence
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0016_revision_output_topology_fields"
down_revision: str | None = "0015_cadquery_native_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.add_column(sa.Column("expected_solid_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("detected_solid_count", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("allow_disconnected_solids", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("revision_outputs") as batch:
        batch.drop_column("allow_disconnected_solids")
        batch.drop_column("detected_solid_count")
        batch.drop_column("expected_solid_count")
