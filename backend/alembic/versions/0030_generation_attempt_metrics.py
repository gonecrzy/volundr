"""separate provider and workflow attempt metrics

Revision ID: 0030_generation_attempt_metrics
Revises: 0029_debug_batch_identity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0030_generation_attempt_metrics"
down_revision: str | None = "0029_debug_batch_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("provider_call_count", "provider_retry_count", "content_repair_count"):
        op.add_column(
            "generation_attempts",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for name in ("content_repair_count", "provider_retry_count", "provider_call_count"):
        op.drop_column("generation_attempts", name)
