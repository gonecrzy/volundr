"""cadquery native persistence fields

Revision ID: 0015_cadquery_native_persistence
Revises: 0014_design_plan_clarifications
Create Date: 2026-07-30

This is a development-transition migration. Existing development databases may be
recreated instead of preserving old OpenSCAD artifacts.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0015_cadquery_native_persistence"
down_revision: str | None = "0014_design_plan_clarifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("design_specifications") as batch:
        batch.alter_column("gemini_ruleset_version", new_column_name="ruleset_version")

    with op.batch_alter_table("design_plans") as batch:
        batch.alter_column("gemini_ruleset_version", new_column_name="ruleset_version")

    with op.batch_alter_table("revision_plans") as batch:
        batch.alter_column("gemini_ruleset_version", new_column_name="ruleset_version")

    with op.batch_alter_table("generation_attempts") as batch:
        batch.alter_column("gemini_ruleset_version", new_column_name="ruleset_version")
        batch.add_column(
            sa.Column(
                "cad_backend",
                sa.String(length=40),
                nullable=False,
                server_default="cadquery",
            )
        )
        batch.add_column(
            sa.Column(
                "source_language",
                sa.String(length=40),
                nullable=False,
                server_default="python",
            )
        )
        batch.add_column(sa.Column("source_contract_version", sa.String(length=80), nullable=True))

    with op.batch_alter_table("generation_attempts") as batch:
        batch.alter_column("cad_backend", server_default=None)
        batch.alter_column("source_language", server_default=None)

    with op.batch_alter_table("revisions") as batch:
        batch.alter_column("scad_source_path", new_column_name="source_path")
        batch.add_column(
            sa.Column(
                "cad_backend",
                sa.String(length=40),
                nullable=False,
                server_default="cadquery",
            )
        )
        batch.add_column(
            sa.Column(
                "source_language",
                sa.String(length=40),
                nullable=False,
                server_default="python",
            )
        )
        batch.add_column(sa.Column("source_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("source_contract_version", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("execution_manifest_path", sa.String(length=500), nullable=True))

    op.create_index(op.f("ix_revisions_source_hash"), "revisions", ["source_hash"], unique=False)
    with op.batch_alter_table("revisions") as batch:
        batch.alter_column("cad_backend", server_default=None)
        batch.alter_column("source_language", server_default=None)

    with op.batch_alter_table("revision_outputs") as batch:
        batch.add_column(
            sa.Column("entrypoint", sa.String(length=120), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("step_path", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("step_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("brep_path", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("brep_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("topology_metadata_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("mesh_metadata_json", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("execution_command_json", sa.Text(), nullable=False, server_default="[]")
        )

    op.execute("UPDATE revision_outputs SET entrypoint = module_name")
    op.execute("UPDATE revision_outputs SET execution_command_json = compile_command_json")
    op.execute("UPDATE revision_outputs SET mesh_metadata_json = metadata_json")

    with op.batch_alter_table("revision_outputs") as batch:
        batch.drop_column("module_name")
        batch.drop_column("compile_command_json")
        batch.alter_column("entrypoint", server_default=None)
        batch.alter_column("execution_command_json", server_default=None)

    op.create_index(op.f("ix_revision_outputs_step_hash"), "revision_outputs", ["step_hash"], unique=False)
    op.create_index(op.f("ix_revision_outputs_brep_hash"), "revision_outputs", ["brep_hash"], unique=False)

    with op.batch_alter_table("source_validation_results") as batch:
        batch.add_column(
            sa.Column(
                "validator_id",
                sa.String(length=120),
                nullable=False,
                server_default="cadquery-static-validator",
            )
        )
        batch.add_column(
            sa.Column(
                "cad_backend",
                sa.String(length=40),
                nullable=False,
                server_default="cadquery",
            )
        )
        batch.add_column(
            sa.Column(
                "source_language",
                sa.String(length=40),
                nullable=False,
                server_default="python",
            )
        )

    with op.batch_alter_table("source_validation_results") as batch:
        batch.alter_column("validator_id", server_default=None)
        batch.alter_column("cad_backend", server_default=None)
        batch.alter_column("source_language", server_default=None)

    with op.batch_alter_table("geometric_analysis_results") as batch:
        batch.add_column(
            sa.Column("analysis_kind", sa.String(length=40), nullable=False, server_default="mesh")
        )

    with op.batch_alter_table("geometric_analysis_results") as batch:
        batch.alter_column("analysis_kind", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("geometric_analysis_results") as batch:
        batch.drop_column("analysis_kind")

    with op.batch_alter_table("source_validation_results") as batch:
        batch.drop_column("source_language")
        batch.drop_column("cad_backend")
        batch.drop_column("validator_id")

    op.drop_index(op.f("ix_revision_outputs_brep_hash"), table_name="revision_outputs")
    op.drop_index(op.f("ix_revision_outputs_step_hash"), table_name="revision_outputs")
    with op.batch_alter_table("revision_outputs") as batch:
        batch.add_column(
            sa.Column("compile_command_json", sa.Text(), nullable=False, server_default="[]")
        )
        batch.add_column(
            sa.Column("module_name", sa.String(length=120), nullable=False, server_default="")
        )

    op.execute("UPDATE revision_outputs SET module_name = entrypoint")
    op.execute("UPDATE revision_outputs SET compile_command_json = execution_command_json")

    with op.batch_alter_table("revision_outputs") as batch:
        batch.drop_column("execution_command_json")
        batch.drop_column("mesh_metadata_json")
        batch.drop_column("topology_metadata_json")
        batch.drop_column("brep_hash")
        batch.drop_column("brep_path")
        batch.drop_column("step_hash")
        batch.drop_column("step_path")
        batch.drop_column("entrypoint")
        batch.alter_column("module_name", server_default=None)
        batch.alter_column("compile_command_json", server_default=None)

    op.drop_index(op.f("ix_revisions_source_hash"), table_name="revisions")
    with op.batch_alter_table("revisions") as batch:
        batch.drop_column("execution_manifest_path")
        batch.drop_column("source_contract_version")
        batch.drop_column("source_hash")
        batch.drop_column("source_language")
        batch.drop_column("cad_backend")
        batch.alter_column("source_path", new_column_name="scad_source_path")

    with op.batch_alter_table("generation_attempts") as batch:
        batch.drop_column("source_contract_version")
        batch.drop_column("source_language")
        batch.drop_column("cad_backend")
        batch.alter_column("ruleset_version", new_column_name="gemini_ruleset_version")

    with op.batch_alter_table("revision_plans") as batch:
        batch.alter_column("ruleset_version", new_column_name="gemini_ruleset_version")

    with op.batch_alter_table("design_plans") as batch:
        batch.alter_column("ruleset_version", new_column_name="gemini_ruleset_version")

    with op.batch_alter_table("design_specifications") as batch:
        batch.alter_column("ruleset_version", new_column_name="gemini_ruleset_version")
