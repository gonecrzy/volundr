"""generation attempt canonical fields

Revision ID: 0017_generation_attempt_canonical_fields
Revises: 0016_revision_output_topology_fields
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0017_generation_attempt_canonical_fields"
down_revision: str | None = "0016_revision_output_topology_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("generation_attempts") as batch:
        batch.alter_column("provider", new_column_name="provider_id")
        batch.alter_column("provider_model", new_column_name="model_id")
        batch.alter_column("prompt_template_version", new_column_name="prompt_version")
        batch.alter_column("extracted_source_path", new_column_name="source_path")


def downgrade() -> None:
    with op.batch_alter_table("generation_attempts") as batch:
        batch.alter_column("source_path", new_column_name="extracted_source_path")
        batch.alter_column("prompt_version", new_column_name="prompt_template_version")
        batch.alter_column("model_id", new_column_name="provider_model")
        batch.alter_column("provider_id", new_column_name="provider")
