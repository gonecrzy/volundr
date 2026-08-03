"""persist provider-response lifecycle evidence

Revision ID: 0032_provider_response_lifecycle
Revises: 0031_widen_debug_batch_identities
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0032_provider_response_lifecycle"
down_revision: str | None = "0031_widen_debug_batch_identities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = [
        sa.Column("provider_response_stage", sa.String(length=80), nullable=True),
        sa.Column("provider_response_classification", sa.String(length=80), nullable=True),
        sa.Column("provider_response_original_path", sa.String(length=500), nullable=True),
        sa.Column("provider_response_parsed_path", sa.String(length=500), nullable=True),
        sa.Column("provider_response_normalized_path", sa.String(length=500), nullable=True),
        sa.Column("provider_response_repaired_path", sa.String(length=500), nullable=True),
        sa.Column("provider_response_final_path", sa.String(length=500), nullable=True),
        sa.Column("provider_response_original_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_response_parsed_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_response_normalized_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_response_repaired_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_response_final_hash", sa.String(length=64), nullable=True),
        sa.Column("provider_response_findings_before_json", sa.Text(), nullable=True),
        sa.Column("provider_response_findings_after_normalization_json", sa.Text(), nullable=True),
        sa.Column("provider_response_findings_after_repair_json", sa.Text(), nullable=True),
        sa.Column("provider_response_manifest_json", sa.Text(), nullable=True),
        sa.Column("provider_response_final_stage", sa.String(length=80), nullable=True),
    ]
    for column in columns:
        op.add_column("generation_attempts", column)


def downgrade() -> None:
    columns = [
        "provider_response_final_stage",
        "provider_response_manifest_json",
        "provider_response_findings_after_repair_json",
        "provider_response_findings_after_normalization_json",
        "provider_response_findings_before_json",
        "provider_response_final_hash",
        "provider_response_repaired_hash",
        "provider_response_normalized_hash",
        "provider_response_parsed_hash",
        "provider_response_original_hash",
        "provider_response_final_path",
        "provider_response_repaired_path",
        "provider_response_normalized_path",
        "provider_response_parsed_path",
        "provider_response_original_path",
        "provider_response_classification",
        "provider_response_stage",
    ]
    for column in columns:
        op.drop_column("generation_attempts", column)

