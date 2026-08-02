"""persist chat message idempotency and response metadata

Revision ID: 0024_chat_message_idempotency
Revises: 0023_provider_usage_metadata
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0024_chat_message_idempotency"
down_revision: str | None = "0023_provider_usage_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("project_messages", sa.Column("client_message_id", sa.String(length=120), nullable=True))
    op.add_column("project_messages", sa.Column("chat_response_json", sa.Text(), nullable=True))
    op.create_index(
        "ix_project_messages_project_client_message_id",
        "project_messages",
        ["project_id", "client_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_project_messages_project_client_message_id", table_name="project_messages")
    op.drop_column("project_messages", "chat_response_json")
    op.drop_column("project_messages", "client_message_id")
