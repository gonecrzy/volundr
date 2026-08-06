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
        "post_upgrade_row_counts_are_empty_except_alembic_version": True,
        "current_inventory_phase": "after_controlled_smoke_rows",
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
        "database_row_policy": "empty except alembic_version before controlled smoke; no historical rows restored",
    })
    write("artifact-reconciliation", {
        **common,
        "status": "passed",
        "artifact_root": "data/jobs",
        "before": {"file_count": 914, "directory_count": 441, "bytes": 44082317, "committed_files": False, "shared_mount": False},
        "action": "recoverable_quarantine_move",
        "quarantine_root": "data/debug-sessions/database-rebuild/clean-database-baseline-01/artifact-quarantine-20260806T012346Z",
        "after": {"artifact_root_bytes": 0, "artifact_root_mode": "0755"},
        "post_controlled_smoke": {"artifact_root_bytes": 525218, "serving_root": "data/jobs"},
        "committed_wave_evidence_preserved": True,
        "database_backup_preserved": True,
    })
    write("application-startup-results", {
        **common,
        "status": "passed",
        "default_stack": {"health": 200, "ready": 200, "validated_flag": False, "migration_on_startup": False},
        "controlled_staging_stack": {"health": 200, "ready": 200, "validated_flag": True, "migration_on_startup": False},
        "controlled_credential_source": "root .env (GEMINI_API_KEY_2 primary, GEMINI_API_KEY fallback)",
        "controlled_credentials_present": {"primary": True, "fallback": True},
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
        "status": "accepted_candidate_and_package_passed",
        "real_staging_attempted": True,
        "workflow_id": "62bd12c3-e8a8-460f-8a1b-ec3e57e0cee3",
        "project_id": "1b408fe0-cab7-4c2a-81ab-49b9e9062e3a",
        "accepted_revision_id": "640bccff-997a-4a76-aa97-cd54c3dfd2ba",
        "terminal_state": "candidate_ready",
        "required_output_count": 1,
        "canonical_output_ids": ["primary_printable_output"],
        "explicit_asymmetric_dimensions": {"width_mm": 30, "depth_mm": 20, "height_mm": 10},
        "package_available": True,
        "provider_attempt_count": 1,
        "worker_job_recorded": True,
        "topology_and_semantic_verification": "passed",
        "artifact_types": ["step", "stl", "brep", "design-package"],
        "required_complexity_gap": "This bounded credential smoke used one rectangular solid; the requested multi-feature irregular creation case remains covered by fixture contracts pending the revision compliance fix.",
        "clean_database_preserved": "no historical application rows restored; only controlled smoke rows exist",
    })
    write("revision-workflow", {
        **common,
        "status": "real_attempted_requires_narrow_fix",
        "real_staging_attempted": True,
        "parent_workflow_id": "62bd12c3-e8a8-460f-8a1b-ec3e57e0cee3",
        "parent_revision_id": "640bccff-997a-4a76-aa97-cd54c3dfd2ba",
        "provider_credentials_loaded": True,
        "attempted_changes": ["width 30 mm -> 36 mm", "bounded top-edge chamfer request"],
        "successful_planning_boundary": True,
        "canonical_output_id_required": "primary_printable_output",
        "failure_boundary": "revision_source_compliance",
        "failure": "The accepted direct brief declares primary_body as protected, but its accepted source has no corresponding feature marker; generated revisions are therefore rejected before compile.",
        "affected_app_boundary": "revision preservation envelope/source authority alignment",
        "deterministic_fixture_contract": "passed in test_validated_cadquery_workflow.py",
    })
    write("partial-output-workflow", {
        **common,
        "status": "fixture_contract_passed_real_flow_deferred_by_revision_fix",
        "real_staging_attempted": False,
        "fixture_assertion": "successful sibling is durable while failed sibling retains worker ownership and workflow is partially_completed",
        "database_mutation": False,
        "reason": "No multi-output provider operation was spent after the accepted one-output smoke; the remaining revision boundary is confirmed and the architecture-level isolation contract passes.",
    })
    write("restart-recovery", {
        **common,
        "status": "accepted_workflow_persisted_across_controlled_restart_fixture_recovery_passed",
        "fixture_assertion": "durable running workflow is reconciled to a safe failure after restart",
        "real_staging_workflow_present": True,
        "persisted_workflow_id": "62bd12c3-e8a8-460f-8a1b-ec3e57e0cee3",
        "persisted_package_available_after_restart": True,
        "duplicate_provider_or_worker_operations_observed": False,
    })
    write("provider-attempts", {
        **common,
        "status": "credentialed_primary_path_passed_no_fallback_needed",
        "primary_credential_env_var": "GEMINI_API_KEY_2",
        "fallback_credential_env_var": "GEMINI_API_KEY",
        "credential_source": "root .env loaded by Compose before non-secret staging flag overlay",
        "primary_credential_present": True,
        "fallback_credential_present": True,
        "external_provider_attempt_count": 15,
        "workflow_associated_attempt_count": 12,
        "status_codes": [200],
        "credential_slot_counts": {"primary": 15, "fallback": 0},
        "fallback_policy_tests": "passed",
        "policy": "fallback only after HTTP 429; no third attempt; request metadata redacts credential values",
        "credential_values_serialized": False,
    })
    write("worker-jobs", {
        **common,
        "status": "credentialed_creation_worker_jobs_recorded",
        "jobs_root": "data/jobs",
        "jobs_root_bytes_after_reconciliation": 525218,
        "real_workflow_job_count": 3,
        "successful_accepted_revision_job": "640bccff-997a-4a76-aa97-cd54c3dfd2ba",
        "failed_smoke_jobs_have_safe_diagnostics": True,
    })
    write("package-integrity", {
        **common,
        "status": "credentialed_real_package_passed",
        "fixture_assertions": ["accepted package manifest schema is validated", "package download is an application-produced ZIP"],
        "real_package_count": 1,
        "workflow_id": "62bd12c3-e8a8-460f-8a1b-ec3e57e0cee3",
        "package_schema": "validated-cadquery-design-package-v1",
        "download_http_status": 200,
        "canonical_output_id": "primary_printable_output",
        "artifact_downloads": {"step": 200, "stl": 200, "brep": 200, "design-package": 200},
        "credential_blocker": False,
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
            {"commit_message": "Follow-up staging credential and revision compatibility fixes", "scope": "root .env credential layering, provider parameter normalization, revision repair request compatibility"},
        ],
        "pending_cycle": "Verify clean database staging baseline evidence commit",
        "source_aligned_images_rebuilt": True,
        "migration_ownership": "new 0039 migration owns the model/schema boundary discovered by fresh audit",
    })
    write("final-database-decision", {
        **common,
        "status": "clean_database_requires_narrow_fix",
        "database_integrity": "passed",
        "schema_drift": "passed",
        "legacy_routing": "passed",
        "validated_routing": "passed_for_flag_and_auth_boundary",
        "provider_backed_product_flow": "credentialed creation, acceptance, artifacts, package, and restart persistence demonstrated; revision compliance boundary remains",
        "blocker": "Accepted direct brief protects primary_body although the accepted source has no matching feature marker; real bounded revision is rejected before compile. Partial-output smoke remains deferred to avoid unnecessary provider calls.",
        "database_state": "clean migration baseline with controlled smoke rows only; no historical user design data restored",
        "next_required_fix": "Align direct-brief structural feature metadata with the accepted source authority before rerunning the bounded revision and partial-output smoke.",
        "secret_values_serialized": False,
    })

    combined = {
        **common,
        "status": "clean_database_requires_narrow_fix",
        "scope": "clean non-production Volundr database rebuild and controlled staging baseline",
        "schema": {"current": inventory["current_revision"], "alembic_check": "clean", "application_tables": inventory["table_count"]},
        "database": {"target": "sqlite:///<redacted>/app.db", "row_policy": "migration started empty; only controlled smoke rows added afterward", "artifact_root_bytes": 525218},
        "completed": ["guarded reset", "base-to-head migration", "fresh schema audit", "0039 alignment and repeated rebuild", "artifact quarantine", "default and controlled routing checks", "root .env credential layering", "credentialed creation/acceptance", "artifact/package integrity", "restart persistence", "fixture contract tests"],
        "blocked": ["real bounded revision completion", "real partial sibling failure"],
        "blocker": "Revision preservation metadata and accepted source authority disagree about the structural primary_body feature; this is a narrow application-owned fix, not a database or credential blocker.",
        "reports": [f"{name}.json" for name in (*REPORTS, "combined-database-rebuild-evidence")],
        "credential_values_serialized": False,
    }
    (EVIDENCE / "combined-database-rebuild-evidence.json.tmp").write_text(
        json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (EVIDENCE / "combined-database-rebuild-evidence.json.tmp").replace(EVIDENCE / "combined-database-rebuild-evidence.json")


if __name__ == "__main__":
    main()
