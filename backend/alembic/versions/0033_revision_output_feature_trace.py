"""persist compact CadQuery source-to-result feature traces

Revision ID: 0033_revision_output_feature_trace
Revises: 0032_provider_response_lifecycle
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0033_revision_output_feature_trace"
down_revision: str | None = "0032_provider_response_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "revision_outputs",
        sa.Column("feature_trace_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("revision_outputs", "feature_trace_json")
