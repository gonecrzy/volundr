"""persist safe provider transport facts for first-blocker forensics

Revision ID: 0040_provider_attempt_transport_facts
Revises: 0039_align_fresh_database_schema
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0040_provider_attempt_transport_facts"
down_revision: str | Sequence[str] | None = "0039_align_fresh_database_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "validated_cadquery_provider_attempts"
    for column in (
        sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_received", sa.Boolean(), nullable=True),
        sa.Column("response_length", sa.Integer(), nullable=True),
        sa.Column("raw_response_hash", sa.String(length=64), nullable=True),
        sa.Column("exception_type", sa.String(length=200), nullable=True),
        sa.Column("normalized_transport_error", sa.String(length=200), nullable=True),
        sa.Column("transport_retry_classification", sa.String(length=64), nullable=True),
        sa.Column("rate_limit_429_classification", sa.String(length=64), nullable=True),
    ):
        op.add_column(table, column)


def downgrade() -> None:
    table = "validated_cadquery_provider_attempts"
    for column_name in (
        "rate_limit_429_classification",
        "transport_retry_classification",
        "normalized_transport_error",
        "exception_type",
        "raw_response_hash",
        "response_length",
        "response_received",
        "request_started_at",
    ):
        op.drop_column(table, column_name)
