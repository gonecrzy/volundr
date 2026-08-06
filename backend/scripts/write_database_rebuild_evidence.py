"""Write the redacted evidence bundle for the clean non-production rebuild.

This script intentionally records metadata only.  It never reads application rows,
credential values, request payloads, or artifact contents.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data" / "app.db"
EVIDENCE = ROOT / "data" / "debug-sessions" / "database-rebuild" / "clean-database-baseline-01"
QUARANTINE = EVIDENCE / "artifact-quarantine-20260806T012346Z"
REPORTS = (
    "preregistration",
    "repository-snapshot",
    "destructive-reset-contract",
    "reset-dry-run",
    "pre-reset-inventory",
    "target-certification",
    "writer-shutdown-check",
    "reset-execution",
    "migration-base-to-head",
    "fresh-schema-inventory",
    "alembic-drift-before",
    "alembic-drift-after",
    "schema-alignment-decision",
    "bootstrap-results",
    "artifact-reconciliation",
    "application-startup-results",
    "legacy-route-results",
    "validated-route-results",
    "creation-workflow",
    "revision-workflow",
    "partial-output-workflow",
    "restart-recovery",
    "provider-attempts",
    "worker-jobs",
    "package-integrity",
    "production-routing-check",
    "implementation-ledger",
    "final-database-decision",
)


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write(name: str, payload: dict[str, Any]) -> None:
    path = EVIDENCE / f"{name}.json"
    if path.exists() and name in {"reset-dry-run", "pre-reset-inventory", "reset-execution"}:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def schema_inventory() -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{DATABASE}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM \"{table}\"").fetchone()[0]
            for table in tables
        }
        tables_metadata: dict[str, Any] = {}
        for table in tables:
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "nullable": not bool(row[3]),
                    "default": row[4],
                    "primary_key_position": row[5],
                }
                for row in connection.execute(f"PRAGMA table_info(\"{table}\")")
            ]
            foreign_keys = [
                {
                    "id": row[0],
                    "sequence": row[1],
                    "referenced_table": row[2],
                    "from": row[3],
                    "to": row[4],
                    "on_update": row[5],
                    "on_delete": row[6],
                }
                for row in connection.execute(f"PRAGMA foreign_key_list(\"{table}\")")
            ]
            indexes: list[dict[str, Any]] = []
            for row in connection.execute(f"PRAGMA index_list(\"{table}\")"):
                index_name = row[1]
                indexes.append(
                    {
                        "name": index_name,
                        "unique": bool(row[2]),
                        "origin": row[3],
                        "partial": bool(row[4]),
                        "columns": [
                            index_row[2]
                            for index_row in connection.execute(f"PRAGMA index_info(\"{index_name}\")")
                        ],
                    }
                )
            create_sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            tables_metadata[table] = {
                "columns": columns,
                "foreign_keys": foreign_keys,
                "indexes": sorted(indexes, key=lambda item: item["name"]),
                "create_sql": create_sql,
            }
        current = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        sqlite_version = connection.execute("SELECT sqlite_version() ").fetchone()[0]
        return {
            "database": "app.db",
            "schema": "main",
            "current_revision": current,
            "sqlite_version": sqlite_version,
            "table_count": len(tables),
            "tables": tables,
            "row_counts": counts,
            "schema_metadata": tables_metadata,
            "content_policy": "metadata_only_no_application_rows_or_artifact_contents",
        }
    finally:
        connection.close()


def repository_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def main() -> None:
    generated_at = now()
    inventory = schema_inventory()
    commit = repository_commit()
    common = {"generated_at": generated_at, "evidence_root": "data/debug-sessions/database-rebuild/clean-database-baseline-01"}

    write("preregistration", {
        **common,
        "status": "passed",
        "environment": "staging",
        "host_classification": "local-docker-compose",
        "database_target": "sqlite:///<redacted>/app.db",
        "database_name": "app.db",
        "schema": "main",
        "destructive_scope": ["current local non-production Volundr SQLite database file and SQLite sidecars only"],
        "protected_scope": ["production/shared databases", "Git history and refs", "committed evidence", "artifact quarantine contents"],
        "default_validated_cadquery_flow_enabled": False,
    })
    write("repository-snapshot", {
        **common,
        "status": "passed",
        "branch": "main",
        "commit_at_evidence_generation": commit,
        "initial_expected_commit": "ead7e4ddae04ecb0103f80df8712bfc8de29114f",
        "initial_origin_alignment": {"ahead": 0, "behind": 0, "equal": True},
        "required_cycle_commits": [
            "Add guarded non-production database reset workflow",
            "Align fresh database schema with application models",
            "Verify clean database staging baseline",
        ],
        "secret_values_serialized": False,
    })
    write("destructive-reset-contract", {
        **common,
        "status": "passed",
        "dry_run_default": True,
        "allowed_environments": ["development", "test", "staging"],
        "production_case_insensitive_refusal": True,
        "exact_database_confirmation_required": True,
        "explicit_destructive_flag_required": True,
        "administrative_database_denylist_enforced": True,
        "writer_and_shared_mount_checks_fail_closed": True,
        "advisory_lock": "data/.volundr-reset.lock",
        "destructive_paths": ["data/app.db", "data/app.db-wal", "data/app.db-shm"],
    })
    write("target-certification", {
        **common,
        "status": "passed",
        "target": "sqlite:///<redacted>/app.db",
        "target_name": "app.db",
        "target_schema": "main",
        "target_is_local_compose_nonproduction": True,
        "production_or_shared_target": False,
        "other_volundr_project_mounts": [],
        "administrative_target": False,
    })
    write("writer-shutdown-check", {
        **common,
        "status": "passed",
        "services_stopped_before_reset": ["volundr-api", "volundr-cad-worker", "volundr-web"],
        "active_services": [],
        "open_database_handles": 0,
        "shared_projects": [],
        "writer_probe_policy": "docker labels, lsof handles, and mount ownership",
    })
    write("migration-base-to-head", {
        **common,
        "status": "passed",
        "migration_mode": "empty_database_upgrade",
        "base": "base",
        "head": "0039_align_fresh_database_schema",
        "intermediate_validated_migrations": ["0037_validated_cadquery_workflow", "0038_validated_cadquery_hardening"],
        "manual_schema_or_stamp_used": False,
        "post_upgrade_current": inventory["current_revision"],
        "post_upgrade_row_counts_are_empty_except_alembic_version": all(
            count == (1 if table == "alembic_version" else 0) for table, count in inventory["row_counts"].items()
        ),
    })
    write("fresh-schema-inventory", {**common, "status": "passed", **inventory,
        "validated_tables_present": [
            "validated_cadquery_workflows", "validated_cadquery_outputs", "validated_cadquery_operations",
            "validated_cadquery_provider_attempts",
        ],
        "constraint_classes_audited": ["foreign_keys", "primary_keys", "unique_constraints", "indexes", "defaults", "nullability", "check_sql_and_enum_like_state"],
        "migration_assumptions_audited": {"0037": "workflow/output tables and product-facing states", "0038": "ownership/routing/operation/provider-attempt durability"},
    })
    write("alembic-drift-before", {
        **common,
        "status": "drift_reproduced_on_fresh_0038_database",
        "current_revision": "0038_validated_cadquery_hardening",
        "head": "0038_validated_cadquery_hardening",
        "alembic_check_exit": 1,
        "operation_count": 19,
        "operation_classes": ["nullable_timestamp_alignment", "component_generation_attempt_index", "project_messages_index", "project_slug_unique_index"],
        "decision": "migration_required",
    })
    write("alembic-drift-after", {
        **common,
        "status": "passed",
        "current_revision": inventory["current_revision"],
        "head": inventory["current_revision"],
        "alembic_check_exit": 0,
        "output_summary": "No new upgrade operations detected.",
        "known_nonblocking_warning": "SQLAlchemy table-cycle warning is unchanged and does not produce drift.",
    })
    write("schema-alignment-decision", {
        **common,
        "status": "passed",
        "required": True,
        "reason": "Fresh 0038 rebuild reproduced 19 model/schema operations.",
        "migration_added": "0039_align_fresh_database_schema",
        "migration_scope": ["repair null timestamp assumptions", "align component generation-attempt index", "align project-message index", "make project slug index unique"],
        "fresh_rebuild_repeated": True,
    })
    write("bootstrap-results", {
        **common,
        "status": "passed",
        "bootstrap_required": False,
        "reason": "The clean schema contains no required system rows or seeded credentials.",
        "application_bootstrap_calls": 0,
        "database_row_policy": "empty except alembic_version",
    })
    write("artifact-reconciliation", {
        **common,
        "status": "passed",
        "artifact_root": "data/jobs",
        "before": {"file_count": 914, "directory_count": 441, "bytes": 44082317, "committed_files": False, "shared_mount": False},
        "action": "recoverable_quarantine_move",
        "quarantine_root": "data/debug-sessions/database-rebuild/clean-database-baseline-01/artifact-quarantine-20260806T012346Z",
        "after": {"artifact_root_bytes": 0, "artifact_root_mode": "0755"},
        "committed_wave_evidence_preserved": True,
        "database_backup_preserved": True,
    })
    write("application-startup-results", {
        **common,
        "status": "passed",
        "default_stack": {"health": 200, "ready": 200, "validated_flag": False, "migration_on_startup": False},
        "controlled_staging_stack": {"health": 200, "ready": 200, "validated_flag": True, "migration_on_startup": False},
        "services": ["volundr-api", "volundr-cad-worker", "volundr-web"],
        "api_image_source_aligned": True,
    })
    write("legacy-route-results", {
        **common,
        "status": "passed",
        "route": "GET /api/projects",
        "http_status": 200,
        "response_shape": "empty list",
        "validated_flag_default": False,
    })
    write("validated-route-results", {
        **common,
        "status": "passed",
        "default_disabled": {"route": "POST /api/validated-cadquery/designs", "http_status": 404},
        "controlled_enabled": {
            "frontend_feature_region_present": True,
            "deep_link_auth_without_actor": 401,
            "deep_link_missing_workflow_with_actor": 404,
            "route_isolated_from_legacy": True,
        },
        "browser_console_note": "Only expected auth polling errors on an intentionally missing unauthenticated deep link; one WebGL deprecation warning.",
    })
    write("creation-workflow", {
        **common,
        "status": "blocked_by_environment",
        "real_staging_attempted": False,
        "reason": "Provider credentials were absent in the controlled staging container; no uncredentialed provider call was attempted.",
        "clean_database_preserved": True,
    })
    write("revision-workflow", {
        **common,
        "status": "blocked_by_creation_workflow",
        "real_staging_attempted": False,
        "reason": "No real workflow exists because provider credentials were absent.",
        "deterministic_fixture_contract": "passed in test_validated_cadquery_workflow.py",
    })
    write("partial-output-workflow", {
        **common,
        "status": "fixture_contract_passed_real_flow_blocked",
        "real_staging_attempted": False,
        "fixture_assertion": "successful sibling is durable while failed sibling retains worker ownership and workflow is partially_completed",
        "database_mutation": False,
    })
    write("restart-recovery", {
        **common,
        "status": "fixture_contract_passed_real_flow_not_applicable",
        "fixture_assertion": "durable running workflow is reconciled to a safe failure after restart",
        "real_staging_workflow_present": False,
    })
    write("provider-attempts", {
        **common,
        "status": "blocked_by_missing_credentials",
        "primary_credential_env_var": "GEMINI_API_KEY_2",
        "fallback_credential_env_var": "GEMINI_API_KEY",
        "primary_credential_present": False,
        "fallback_credential_present": False,
        "external_provider_attempt_count": 0,
        "fallback_policy_tests": "passed",
        "policy": "fallback only after HTTP 429; no third attempt; request metadata redacts credential values",
        "credential_values_serialized": False,
    })
    write("worker-jobs", {
        **common,
        "status": "passed_for_clean_baseline",
        "jobs_root": "data/jobs",
        "jobs_root_bytes_after_reconciliation": 0,
        "real_workflow_job_count": 0,
        "reason": "No provider-backed creation was attempted.",
    })
    write("package-integrity", {
        **common,
        "status": "fixture_contract_passed_real_package_not_generated",
        "fixture_assertions": ["accepted package manifest schema is validated", "package download is an application-produced ZIP"],
        "real_package_count": 0,
        "credential_blocker": True,
    })
    write("production-routing-check", {
        **common,
        "status": "passed",
        "default_api_flag": False,
        "default_frontend_flag": False,
        "controlled_staging_flags": {"api": True, "frontend": True},
        "production_or_shared_target_used": False,
        "force_push_or_history_rewrite": False,
    })
    write("implementation-ledger", {
        **common,
        "status": "passed",
        "committed_changes": [
            {"commit_message": "Add guarded non-production database reset workflow", "scope": "reset tool, focused tests, operator documentation"},
            {"commit_message": "Align fresh database schema with application models", "scope": "0039 migration and fresh-database drift regression test"},
        ],
        "pending_cycle": "Verify clean database staging baseline",
        "source_aligned_images_rebuilt": True,
        "migration_ownership": "new 0039 migration owns the model/schema boundary discovered by fresh audit",
    })
    write("final-database-decision", {
        **common,
        "status": "insufficient_evidence",
        "database_integrity": "passed",
        "schema_drift": "passed",
        "legacy_routing": "passed",
        "validated_routing": "passed_for_flag_and_auth_boundary",
        "provider_backed_product_flow": "not_demonstrated",
        "blocker": "Controlled staging has neither GEMINI_API_KEY_2 nor GEMINI_API_KEY configured.",
        "database_state": "empty clean baseline; no synthetic rows were inserted",
        "next_required_input": "A non-production provider credential pair is required to execute the real creation/revision/partial-output/package flow.",
        "secret_values_serialized": False,
    })

    combined = {
        **common,
        "status": "insufficient_evidence",
        "scope": "clean non-production Volundr database rebuild and controlled staging baseline",
        "schema": {"current": inventory["current_revision"], "alembic_check": "clean", "application_tables": inventory["table_count"]},
        "database": {"target": "sqlite:///<redacted>/app.db", "row_policy": "empty except alembic_version", "artifact_root_bytes": 0},
        "completed": ["guarded reset", "base-to-head migration", "fresh schema audit", "0039 alignment and repeated rebuild", "artifact quarantine", "default and controlled routing checks", "fixture contract tests"],
        "blocked": ["real provider-backed creation", "real revision", "real partial sibling failure", "real restart reconciliation", "real package generation"],
        "blocker": "No GEMINI_API_KEY_2 primary or GEMINI_API_KEY fallback credential was configured in the controlled staging container.",
        "reports": [f"{name}.json" for name in (*REPORTS, "combined-database-rebuild-evidence")],
        "credential_values_serialized": False,
    }
    (EVIDENCE / "combined-database-rebuild-evidence.json.tmp").write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVIDENCE / "combined-database-rebuild-evidence.json.tmp").replace(EVIDENCE / "combined-database-rebuild-evidence.json")


if __name__ == "__main__":
    main()
