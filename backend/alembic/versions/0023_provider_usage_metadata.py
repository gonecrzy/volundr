"""persist provider usage metadata for generation attempts

Revision ID: 0023_provider_usage_metadata
Revises: 0022_functional_verification
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0023_provider_usage_metadata"
down_revision: str | None = "0022_functional_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generation_attempts", sa.Column("provider_usage_json", sa.Text(), nullable=True))
    op.add_column("generation_attempts", sa.Column("provider_request_id", sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column("generation_attempts", "provider_request_id")
    op.drop_column("generation_attempts", "provider_usage_json")
