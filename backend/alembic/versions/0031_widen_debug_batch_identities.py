"""Widen serialized debug batch build identities."""

from alembic import op
import sqlalchemy as sa


revision = "0031_widen_debug_batch_identities"
down_revision = "0030_generation_attempt_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("debug_batches") as batch:
        for column in ("frontend_build_identity", "backend_build_identity", "worker_build_identity"):
            batch.alter_column(
                column,
                existing_type=sa.String(length=160),
                type_=sa.String(length=512),
                existing_nullable=False,
            )


def downgrade() -> None:
    with op.batch_alter_table("debug_batches") as batch:
        for column in ("frontend_build_identity", "backend_build_identity", "worker_build_identity"):
            batch.alter_column(
                column,
                existing_type=sa.String(length=512),
                type_=sa.String(length=160),
                existing_nullable=False,
            )
