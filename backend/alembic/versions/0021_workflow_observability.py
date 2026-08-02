"""workflow observability

Revision ID: 0021_workflow_observability
Revises: 0020_design_artifact_consistency
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0021_workflow_observability"
down_revision: str | None = "0020_design_artifact_consistency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_type", sa.String(length=80), nullable=False),
        sa.Column("parent_workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("root_workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("logging_mode", sa.String(length=40), nullable=False),
        sa.Column("event_schema_version", sa.String(length=80), nullable=False),
        sa.Column("diagnosis_version", sa.String(length=80), nullable=False),
        sa.Column("redaction_version", sa.String(length=80), nullable=False),
        sa.Column("application_commit", sa.String(length=80), nullable=True),
        sa.Column("worker_version", sa.String(length=120), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_versions_json", sa.Text(), nullable=False),
        sa.Column("workflow_metadata_json", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_workflow_run_id"], ["workflow_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "workflow_type", "parent_workflow_run_id", "root_workflow_run_id", "correlation_id", "status"):
        op.create_index(f"ix_workflow_runs_{column}", "workflow_runs", [column])

    op.create_table(
        "workflow_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("root_workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("generation_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("design_specification_id", sa.String(length=36), nullable=True),
        sa.Column("design_plan_id", sa.String(length=36), nullable=True),
        sa.Column("revision_id", sa.String(length=36), nullable=True),
        sa.Column("revision_output_id", sa.String(length=36), nullable=True),
        sa.Column("revision_plan_id", sa.String(length=36), nullable=True),
        sa.Column("configuration_change_id", sa.String(length=36), nullable=True),
        sa.Column("worker_job_id", sa.String(length=160), nullable=True),
        sa.Column("provider_request_id", sa.String(length=160), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("blocking", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("rule_id", sa.String(length=160), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=160), nullable=True),
        sa.Column("expected_json", sa.Text(), nullable=True),
        sa.Column("detected_json", sa.Text(), nullable=True),
        sa.Column("source_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("caused_by_event_id", sa.String(length=36), nullable=True),
        sa.Column("is_root_failure", sa.Boolean(), nullable=False),
        sa.Column("is_downstream_symptom", sa.Boolean(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=300), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_run_id", "deduplication_key", name="uq_workflow_events_run_deduplication_key"),
        sa.UniqueConstraint("workflow_run_id", "sequence_number", name="uq_workflow_events_run_sequence"),
    )
    for column in (
        "workflow_run_id",
        "root_workflow_run_id",
        "correlation_id",
        "project_id",
        "generation_attempt_id",
        "design_specification_id",
        "design_plan_id",
        "revision_id",
        "revision_output_id",
        "revision_plan_id",
        "configuration_change_id",
        "worker_job_id",
        "stage",
        "event_type",
        "rule_id",
        "entity_id",
        "source_artifact_id",
        "caused_by_event_id",
    ):
        op.create_index(f"ix_workflow_events_{column}", "workflow_events", [column])

    op.create_table(
        "workflow_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("root_workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("artifact_type", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=False),
        sa.Column("path", sa.String(length=700), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("redaction_status", sa.String(length=40), nullable=False),
        sa.Column("supersedes_artifact_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_metadata_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("workflow_run_id", "root_workflow_run_id", "correlation_id", "project_id", "stage", "artifact_type", "sha256", "supersedes_artifact_id"):
        op.create_index(f"ix_workflow_artifacts_{column}", "workflow_artifacts", [column])

    op.create_table(
        "workflow_diagnoses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("root_cause_json", sa.Text(), nullable=False),
        sa.Column("repairs_json", sa.Text(), nullable=False),
        sa.Column("downstream_effects_json", sa.Text(), nullable=False),
        sa.Column("final_outcome", sa.String(length=80), nullable=False),
        sa.Column("basis_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_diagnoses_workflow_run_id", "workflow_diagnoses", ["workflow_run_id"])

    op.create_table(
        "frontend_workflow_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=False),
        sa.Column("correlation_id", sa.String(length=36), nullable=False),
        sa.Column("frontend_session_id", sa.String(length=120), nullable=False),
        sa.Column("route", sa.String(length=240), nullable=False),
        sa.Column("action_name", sa.String(length=120), nullable=False),
        sa.Column("user_visible_state", sa.String(length=120), nullable=False),
        sa.Column("backend_request_id", sa.String(length=120), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("project_id", "workflow_run_id", "correlation_id", "frontend_session_id", "action_name"):
        op.create_index(f"ix_frontend_workflow_events_{column}", "frontend_workflow_events", [column])


def downgrade() -> None:
    for column in ("project_id", "workflow_run_id", "correlation_id", "frontend_session_id", "action_name"):
        op.drop_index(f"ix_frontend_workflow_events_{column}", table_name="frontend_workflow_events")
    op.drop_table("frontend_workflow_events")
    op.drop_index("ix_workflow_diagnoses_workflow_run_id", table_name="workflow_diagnoses")
    op.drop_table("workflow_diagnoses")
    for column in ("workflow_run_id", "root_workflow_run_id", "correlation_id", "project_id", "stage", "artifact_type", "sha256", "supersedes_artifact_id"):
        op.drop_index(f"ix_workflow_artifacts_{column}", table_name="workflow_artifacts")
    op.drop_table("workflow_artifacts")
    for column in (
        "workflow_run_id",
        "root_workflow_run_id",
        "correlation_id",
        "project_id",
        "generation_attempt_id",
        "design_specification_id",
        "design_plan_id",
        "revision_id",
        "revision_output_id",
        "revision_plan_id",
        "configuration_change_id",
        "worker_job_id",
        "stage",
        "event_type",
        "rule_id",
        "entity_id",
        "source_artifact_id",
        "caused_by_event_id",
    ):
        op.drop_index(f"ix_workflow_events_{column}", table_name="workflow_events")
    op.drop_table("workflow_events")
    for column in ("project_id", "workflow_type", "parent_workflow_run_id", "root_workflow_run_id", "correlation_id", "status"):
        op.drop_index(f"ix_workflow_runs_{column}", table_name="workflow_runs")
    op.drop_table("workflow_runs")
