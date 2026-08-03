"""add provider and safe resource metadata to benchmark models

Revision ID: 0036_benchmark_model_metadata
Revises: 0035_gemini_consistency_benchmark
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0036_benchmark_model_metadata"
down_revision: str | None = "0035_gemini_consistency_benchmark"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gemini_benchmark_models",
        sa.Column("provider", sa.String(length=80), nullable=False, server_default="gemini_api"),
    )
    op.add_column("gemini_benchmark_models", sa.Column("actual_digest", sa.String(length=200), nullable=True))
    op.add_column(
        "gemini_benchmark_models",
        sa.Column("model_metadata_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "gemini_benchmark_models",
        sa.Column("resource_profile_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("gemini_benchmark_models", "resource_profile_json")
    op.drop_column("gemini_benchmark_models", "model_metadata_json")
    op.drop_column("gemini_benchmark_models", "actual_digest")
    op.drop_column("gemini_benchmark_models", "provider")
