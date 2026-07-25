"""printability profiles

Revision ID: 0003_printability_profiles
Revises: 0002_project_messages
Create Date: 2026-07-25
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_printability_profiles"
down_revision: str | Sequence[str] | None = "0002_project_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "printability_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("profile_version", sa.String(length=80), nullable=False),
        sa.Column("printer_name", sa.String(length=120), nullable=False),
        sa.Column("process", sa.String(length=40), nullable=False),
        sa.Column("material_behavior", sa.String(length=80), nullable=False),
        sa.Column("build_volume_x_mm", sa.Float(), nullable=False),
        sa.Column("build_volume_y_mm", sa.Float(), nullable=False),
        sa.Column("build_volume_z_mm", sa.Float(), nullable=False),
        sa.Column("nozzle_diameter_mm", sa.Float(), nullable=False),
        sa.Column("default_layer_height_mm", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_printability_profiles_printer_name"),
        "printability_profiles",
        ["printer_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_printability_profiles_printer_name"),
        table_name="printability_profiles",
    )
    op.drop_table("printability_profiles")
