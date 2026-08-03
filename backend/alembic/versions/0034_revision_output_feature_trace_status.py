"""persist whether the worker supports source-to-result feature tracing

Revision ID: 0034_revision_output_feature_trace_status
Revises: 0033_revision_output_feature_trace
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0034_revision_output_feature_trace_status"
down_revision: str | None = "0033_revision_output_feature_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revision_outputs",
        sa.Column(
            "feature_trace_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Keep the SQLite-compatible default so existing rows and future legacy
    # writers remain explicit about trace support being unavailable.


def downgrade() -> None:
    op.drop_column("revision_outputs", "feature_trace_available")
