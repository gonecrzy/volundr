"""align fresh database nullability and indexes with ORM metadata

Revision ID: 0039_align_fresh_database_schema
Revises: 0038_validated_cadquery_hardening
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0039_align_fresh_database_schema"
down_revision: str | Sequence[str] | None = "0038_validated_cadquery_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NOT_NULL_COLUMNS = (
    ("component_revision_summaries", "created_at"),
    ("configuration_changes", "created_at"),
    ("configuration_presets", "created_at"),
    ("design_artifact_consistency_results", "created_at"),
    ("design_plan_clarification_answers", "created_at"),
    ("design_plan_clarification_questions", "created_at"),
    ("export_records", "created_at"),
    ("frontend_workflow_events", "recorded_at"),
    ("physical_test_observations", "created_at"),
    ("requirement_deltas", "created_at"),
    ("requirement_ledger_entries", "created_at"),
    ("requirement_ledger_entries", "updated_at"),
    ("workflow_artifacts", "created_at"),
    ("workflow_diagnoses", "created_at"),
    ("workflow_runs", "started_at"),
    ("workflow_runs", "updated_at"),
)


def _alter_nullability(table_name: str, column_name: str, *, nullable: bool) -> None:
    if not nullable:
        op.execute(
            sa.text(
                f'UPDATE "{table_name}" SET "{column_name}" = CURRENT_TIMESTAMP '
                f'WHERE "{column_name}" IS NULL'
            )
        )
    with op.batch_alter_table(table_name, recreate="always") as batch:
        batch.alter_column(
            column_name,
            existing_type=sa.DateTime(),
            nullable=nullable,
        )


def upgrade() -> None:
    for table_name, column_name in _NOT_NULL_COLUMNS:
        _alter_nullability(table_name, column_name, nullable=False)

    op.create_index(
        "ix_component_revision_summaries_generation_attempt_id",
        "component_revision_summaries",
        ["generation_attempt_id"],
        unique=False,
    )
    op.drop_index(
        "ix_project_messages_project_client_message_id",
        table_name="project_messages",
    )
    op.create_index(
        "ix_project_messages_client_message_id",
        "project_messages",
        ["client_message_id"],
        unique=False,
    )
    op.drop_index("ix_projects_slug", table_name="projects")
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_projects_slug", table_name="projects")
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=False)
    op.drop_index("ix_project_messages_client_message_id", table_name="project_messages")
    op.create_index(
        "ix_project_messages_project_client_message_id",
        "project_messages",
        ["project_id", "client_message_id"],
        unique=True,
    )
    op.drop_index(
        "ix_component_revision_summaries_generation_attempt_id",
        table_name="component_revision_summaries",
    )
    for table_name, column_name in reversed(_NOT_NULL_COLUMNS):
        _alter_nullability(table_name, column_name, nullable=True)
