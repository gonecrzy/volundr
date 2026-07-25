"""configuration changes

Revision ID: 0012_configuration_changes
Revises: 0011_structured_revision_plans
Create Date: 2026-07-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_configuration_changes"
down_revision: str | None = "0011_structured_revision_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "configuration_changes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("base_revision_id", sa.String(length=36), nullable=False),
        sa.Column("generated_revision_id", sa.String(length=36), nullable=True),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("design_plan_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=False),
        sa.Column("selected_preset_id", sa.String(length=120), nullable=True),
        sa.Column("validation_state", sa.String(length=60), nullable=False),
        sa.Column("base_source_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_changes_json", sa.Text(), nullable=False),
        sa.Column("preset_values_json", sa.Text(), nullable=False),
        sa.Column("user_overrides_json", sa.Text(), nullable=False),
        sa.Column("resolved_parameters_json", sa.Text(), nullable=False),
        sa.Column("affected_parameters_json", sa.Text(), nullable=False),
        sa.Column("affected_components_json", sa.Text(), nullable=False),
        sa.Column("affected_outputs_json", sa.Text(), nullable=False),
        sa.Column("validation_errors_json", sa.Text(), nullable=False),
        sa.Column("override_manifest_path", sa.String(length=500), nullable=True),
        sa.Column("configuration_path", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["base_revision_id"], ["revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["design_specification_id"], ["design_specifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_revision_id"], ["revisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_configuration_changes_base_revision_id"), "configuration_changes", ["base_revision_id"], unique=False)
    op.create_index(op.f("ix_configuration_changes_design_plan_id"), "configuration_changes", ["design_plan_id"], unique=False)
    op.create_index(op.f("ix_configuration_changes_design_specification_id"), "configuration_changes", ["design_specification_id"], unique=False)
    op.create_index(op.f("ix_configuration_changes_generated_revision_id"), "configuration_changes", ["generated_revision_id"], unique=False)
    op.create_index(op.f("ix_configuration_changes_project_id"), "configuration_changes", ["project_id"], unique=False)

    op.create_table(
        "configuration_presets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("design_plan_id", sa.String(length=36), nullable=False),
        sa.Column("preset_id", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("parameter_values_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["design_plan_id"], ["design_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_configuration_presets_design_plan_id"), "configuration_presets", ["design_plan_id"], unique=False)
    op.create_index(op.f("ix_configuration_presets_preset_id"), "configuration_presets", ["preset_id"], unique=False)
    op.create_index(op.f("ix_configuration_presets_project_id"), "configuration_presets", ["project_id"], unique=False)

    with op.batch_alter_table("revisions") as batch_op:
        batch_op.add_column(sa.Column("configuration_change_id", sa.String(length=36), nullable=True))
        batch_op.create_index(op.f("ix_revisions_configuration_change_id"), ["configuration_change_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_revisions_configuration_change_id_configuration_changes",
            "configuration_changes",
            ["configuration_change_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("revisions") as batch_op:
        batch_op.drop_constraint("fk_revisions_configuration_change_id_configuration_changes", type_="foreignkey")
        batch_op.drop_index(op.f("ix_revisions_configuration_change_id"))
        batch_op.drop_column("configuration_change_id")
    op.drop_index(op.f("ix_configuration_presets_project_id"), table_name="configuration_presets")
    op.drop_index(op.f("ix_configuration_presets_preset_id"), table_name="configuration_presets")
    op.drop_index(op.f("ix_configuration_presets_design_plan_id"), table_name="configuration_presets")
    op.drop_table("configuration_presets")
    op.drop_index(op.f("ix_configuration_changes_project_id"), table_name="configuration_changes")
    op.drop_index(op.f("ix_configuration_changes_generated_revision_id"), table_name="configuration_changes")
    op.drop_index(op.f("ix_configuration_changes_design_specification_id"), table_name="configuration_changes")
    op.drop_index(op.f("ix_configuration_changes_design_plan_id"), table_name="configuration_changes")
    op.drop_index(op.f("ix_configuration_changes_base_revision_id"), table_name="configuration_changes")
    op.drop_table("configuration_changes")
