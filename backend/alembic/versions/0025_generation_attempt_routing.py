"""persist prompt-stage model routing evidence

Revision ID: 0025_generation_attempt_routing
Revises: 0024_chat_message_idempotency
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0025_generation_attempt_routing"
down_revision: str | None = "0024_chat_message_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_attempts",
        sa.Column("routing_metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "generation_attempts",
        sa.Column("provider_latency_ms", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_attempts", "provider_latency_ms")
    op.drop_column("generation_attempts", "routing_metadata_json")
