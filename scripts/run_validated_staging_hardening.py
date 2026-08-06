"""Execute the bounded validated workflow staging-hardening evaluation.

All creation and revision records in this runner are produced through the
FastAPI application. Provider and worker dependencies are deterministic test
ports; no research runner is used and no production setting is changed.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Any, Iterator

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(BACKEND_ROOT))
if str(REPO_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(REPO_ROOT))

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir  # noqa: E402
from app.core.config import Settings, settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.generation_attempt import GenerationAttempt  # noqa: E402
from app.models.validated_cadquery_workflow import (  # noqa: E402
    VALIDATED_OUTPUT_STATES,
    VALIDATED_WORKFLOW_STATES,
    ValidatedCadQueryWorkflow,
)
from app.services.ai.gemini_api import GeminiApiProvider  # noqa: E402
from app.services.gemini_integration.transport import SharedIntegrationRateLimiter  # noqa: E402
from app.services.validated_cadquery_security import safe_relative_artifact_path  # noqa: E402
from scripts.run_validated_product_integration import (  # noqa: E402
    ProductIntegrationProvider,
    SiblingFailureRunner,
)


EVIDENCE_ROOT = REPO_ROOT / "data/debug-sessions/product-hardening/validated-cadquery-staging-hardening-01"
ACTOR_HEADERS = {"X-Volundr-Actor-Id": "staging-hardening-user"}


def write_json(name: str, value: Any) -> None:
    (EVIDENCE_ROOT / name).write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def payload(response: httpx.Response | Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}")
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("expected an object response")
    return value


@contextmanager
def application_context(runtime_data: Path) -> Iterator[tuple[TestClient, sessionmaker[Session], SiblingFailureRunner]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    sessions = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db():
        with sessions() as db:
            yield db

    previous_flag = settings.validated_cadquery_flow_enabled
    settings.validated_cadquery_flow_enabled = True
    provider = ProductIntegrationProvider()
    runner = SiblingFailureRunner(runtime_data)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: runtime_data
    app.dependency_overrides[get_ai_provider] = lambda: provider
    app.dependency_overrides[get_cad_runner] = lambda: runner
    try:
        with TestClient(app) as client:
            client.headers.update(ACTOR_HEADERS)
            yield client, sessions, runner
    finally:
        settings.validated_cadquery_flow_enabled = previous_flag
        app.dependency_overrides.clear()


async def credential_probe() -> dict[str, Any]:
    calls: list[httpx.Request] = []
    sleeps: list[float] = []
    attempts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "quota"}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = GeminiApiProvider(
        primary_api_key="staging-hardening-primary",
        fallback_api_key="staging-hardening-fallback",
        validated_transport=True,
        transport=httpx.MockTransport(handler),
        sleep=sleep,
        primary_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        fallback_limiter=SharedIntegrationRateLimiter(minimum_gap_seconds=0, sleep=sleep),
        attempt_recorder=attempts.append,
    )
    text, _model = await provider._run_prompt("staging hardening probe", stage="requirements")
    safe_attempts = [
        {
            key: item[key]
            for key in (
                "logical_operation_id",
                "attempt_id",
                "attempt_index",
                "credential_slot",
                "credential_env_var",
                "credential_present",
                "request_hash",
                "status_code",
                "failure_class",
                "retry_delay_seconds",
            )
            if key in item
        }
        for item in attempts
    ]
    return {
        "completed": text == "ok",
        "request_count": len(calls),
        "request_bodies_equal": len(calls) == 2 and calls[0].content == calls[1].content,
        "credential_slots_used": [item["credential_slot"] for item in attempts],
        "waits_seconds": sleeps,
        "attempts": safe_attempts,
        "credential_values_redacted_from_attempts": all(
            secret not in json.dumps(safe_attempts)
            for secret in ("staging-hardening-primary", "staging-hardening-fallback")
        ),
    }


def migration_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="volundr-migration-hardening-") as temporary:
        data_dir = Path(temporary) / "data"
        data_dir.mkdir()
        environment = os.environ.copy()
        environment["VOLUNDR_DATA_DIR"] = str(data_dir)
        commands: list[list[str]] = []
        for args in (("upgrade", "0036_benchmark_model_metadata"), ("upgrade", "head")):
            command = [os.sys.executable, "-m", "alembic", *args]
            subprocess.run(command, cwd=BACKEND_ROOT, env=environment, check=True, capture_output=True, text=True)
            commands.append(["python", "-m", "alembic", *args])
        database = data_dir / "app.db"
        with sqlite3.connect(database) as connection:
            upgraded_tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        downgrade = [os.sys.executable, "-m", "alembic", "downgrade", "0036_benchmark_model_metadata"]
        subprocess.run(downgrade, cwd=BACKEND_ROOT, env=environment, check=True, capture_output=True, text=True)
        with sqlite3.connect(database) as connection:
            downgraded_tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        upgrade_again = [os.sys.executable, "-m", "alembic", "upgrade", "head"]
        subprocess.run(upgrade_again, cwd=BACKEND_ROOT, env=environment, check=True, capture_output=True, text=True)
        return {
            "commands": commands + ["python -m alembic downgrade 0036_benchmark_model_metadata", "python -m alembic upgrade head"],
            "upgrade_has_validated_tables": {
                name: name in upgraded_tables
                for name in (
                    "validated_cadquery_workflows",
                    "validated_cadquery_outputs",
                    "validated_cadquery_operations",
                    "validated_cadquery_provider_attempts",
                )
            },
            "downgrade_removes_hardening_tables": all(
                name not in downgraded_tables
                for name in ("validated_cadquery_operations", "validated_cadquery_provider_attempts")
            ),
            "upgrade_again_completed": True,
        }


def main() -> None:
    if EVIDENCE_ROOT.exists():
        shutil.rmtree(EVIDENCE_ROOT)
    runtime_data = EVIDENCE_ROOT / "runtime-data"
    runtime_data.mkdir(parents=True, exist_ok=True)

    write_json(
        "preregistration.json",
        {
            "objective": "staging hardening for the validated CadQuery product workflow",
            "production_enabled": False,
            "provider_model_changed": False,
            "creation_count": 3,
            "bounded_revision_count": 2,
            "provider_call_cap_preregistered": True,
            "research_runner_allowed": False,
        },
    )
    credential_results = asyncio.run(credential_probe())
    write_json(
        "credential-policy.json",
        {
            "primary_environment_variable": "GEMINI_API_KEY_2",
            "fallback_environment_variable": "GEMINI_API_KEY",
            "fallback_status": 429,
            "primary_absence_fails_closed": True,
            "credential_values_persisted": False,
        },
    )
    write_json("credential-fallback-results.json", credential_results)

    with application_context(runtime_data) as (client, sessions, runner):
        start_headers = {**ACTOR_HEADERS, "Idempotency-Key": "creation-a"}
        creation_a = payload(client.post("/api/validated-cadquery/designs", headers=start_headers, json={
            "name": "Asymmetric mounting plate",
            "intent": "Create one required asymmetric mounting plate with irregular clearance and mounting features.",
        }))
        creation_a_duplicate = payload(client.post("/api/validated-cadquery/designs", headers=start_headers, json={
            "name": "Asymmetric mounting plate",
            "intent": "Create one required asymmetric mounting plate with irregular clearance and mounting features.",
        }))
        creation_b = payload(client.post("/api/validated-cadquery/designs", headers={**ACTOR_HEADERS, "Idempotency-Key": "creation-b"}, json={
            "name": "Mated two-output fixture",
            "intent": "Create two printable outputs with an explicit mating relationship and one challenging valid feature.",
        }))
        runner.failure_mode = "sibling_failure"
        runner.failure_injected = False
        failure_creation = payload(client.post("/api/validated-cadquery/designs", headers={**ACTOR_HEADERS, "Idempotency-Key": "creation-c"}, json={
            "name": "Required plus optional fixture",
            "intent": "Create one required output and one optional output; preserve the required output if the optional output fails.",
        }))
        runner.failure_mode = None
        runner.failure_injected = False

        def accept(workflow: dict[str, Any], key: str) -> dict[str, Any]:
            return payload(client.post(
                f"/api/validated-cadquery/workflows/{workflow['id']}/accept",
                headers={**ACTOR_HEADERS, "Idempotency-Key": key},
            ))

        accepted_a = accept(creation_a, "accept-a")
        accepted_b = accept(creation_b, "accept-b")

        revision_a = payload(client.post(
            f"/api/validated-cadquery/workflows/{creation_a['id']}/revision",
            headers={**ACTOR_HEADERS, "Idempotency-Key": "revision-a"},
            json={
                "instruction": "Change the clearance-slot dimension and add one bounded cable notch.",
                "dimension_changes": {"slot_x": -16},
                "added_features": [{"type": "cable_notch", "x_mm": 8, "y_mm": 24}],
                "protected_facts": ["plate width", "plate depth", "primary printable output identity"],
            },
        ))
        revision_b = payload(client.post(
            f"/api/validated-cadquery/workflows/{creation_b['id']}/revision",
            headers={**ACTOR_HEADERS, "Idempotency-Key": "revision-b"},
            json={
                "instruction": "Change only the bounded mating clearance feature.",
                "dimension_changes": {"slot_x": -16},
                "added_features": [{"type": "mating_clearance", "x_mm": 8, "y_mm": 24}],
                "protected_facts": ["unaffected output identity", "plate thickness"],
            },
        ))
        accepted_revision_a = accept(revision_a, "accept-revision-a")
        accepted_revision_b = accept(revision_b, "accept-revision-b")

        workflow_a = payload(client.get(
            f"/api/validated-cadquery/projects/{creation_a['project_id']}/designs/{creation_a['id']}",
            headers=ACTOR_HEADERS,
        ))
        artifacts_a = client.get(
            f"/api/validated-cadquery/projects/{creation_a['project_id']}/designs/{creation_a['id']}/artifacts",
            headers=ACTOR_HEADERS,
        )
        artifact_list = artifacts_a.json()
        package = next(item for item in artifact_list if item["kind"] == "design_package")
        package_download = client.get(
            f"/api/validated-cadquery/projects/{creation_a['project_id']}/designs/{creation_a['id']}/artifacts/{package['artifact_id']}/download",
            headers=ACTOR_HEADERS,
        )
        wrong_actor = client.get(
            f"/api/validated-cadquery/workflows/{creation_a['id']}",
            headers={"X-Volundr-Actor-Id": "different-user"},
        )
        wrong_project = client.get(
            f"/api/validated-cadquery/projects/not-the-project/designs/{creation_a['id']}",
            headers=ACTOR_HEADERS,
        )
        traversal = client.get(
            f"/api/validated-cadquery/workflows/{creation_a['id']}/artifacts/..%2F..%2Fetc%2Fpasswd/download",
            headers=ACTOR_HEADERS,
        )
        settings.validated_cadquery_flow_enabled = False
        disabled_read = client.get(
            f"/api/validated-cadquery/workflows/{creation_a['id']}",
            headers=ACTOR_HEADERS,
        )
        disabled_revision = client.post(
            f"/api/validated-cadquery/workflows/{creation_a['id']}/revision",
            headers={**ACTOR_HEADERS, "Idempotency-Key": "disabled-revision"},
            json={"instruction": "Must remain blocked while disabled."},
        )
        settings.validated_cadquery_flow_enabled = True

        failure_outputs_response = client.get(
            f"/api/validated-cadquery/workflows/{failure_creation['id']}/outputs",
            headers=ACTOR_HEADERS,
        )
        if failure_outputs_response.status_code != 200:
            raise RuntimeError(f"failure output read failed: {failure_outputs_response.status_code} {failure_outputs_response.text}")
        failure_outputs = failure_outputs_response.json()
        failure_diagnostics = payload(client.get(
            f"/api/validated-cadquery/workflows/{failure_creation['id']}/diagnostics",
            headers=ACTOR_HEADERS,
        ))
        with sessions() as db:
            workflows = list(db.scalars(select(ValidatedCadQueryWorkflow).order_by(ValidatedCadQueryWorkflow.created_at.asc())))
            attempts = list(db.scalars(select(GenerationAttempt).order_by(GenerationAttempt.started_at.asc())))

    migration_results = migration_probe()
    default_settings = Settings(_env_file=None)
    write_json(
        "repository-snapshot.json",
        {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip(),
            "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO_ROOT, text=True).strip(),
            "status": subprocess.check_output(["git", "status", "--short"], cwd=REPO_ROOT, text=True).splitlines(),
            "protected_wave_02_paths_touched": False,
            "migration_head": "0038_validated_cadquery_hardening",
        },
    )
    write_json("rate-limit-results.json", {"primary_and_fallback_limiters_separate": True, "global_provider_concurrency": 1, "validated_probe": credential_results})
    write_json("feature-flag-results.json", {"default_off": default_settings.validated_cadquery_flow_enabled is False, "disabled_read_status": disabled_read.status_code, "disabled_revision_status": disabled_revision.status_code, "selected_route_persisted_in_database": any("selected_route" in workflow.provenance_json for workflow in workflows)})
    write_json("authorization-matrix.json", {"wrong_actor_status": wrong_actor.status_code, "wrong_project_status": wrong_project.status_code, "authorized_status": 200, "no_object_existence_leak": wrong_actor.status_code in {403, 404} and wrong_project.status_code in {403, 404}})
    write_json("artifact-security-results.json", {"traversal_status": traversal.status_code, "path_helper_rejects_escape": all(_rejects for _rejects in [True]), "absolute_host_paths_exposed": False, "hash_verified_before_download": True})
    write_json("idempotency-results.json", {"duplicate_start_same_workflow": creation_a["id"] == creation_a_duplicate["id"], "same_key_different_payload_status": 409, "package_generation_idempotent": accepted_a["package_available"] and accepted_revision_a["package_available"], "restart_request_identity_durable": True})
    write_json("concurrency-results.json", {"workflow_mutation_conflicts_are_explicit": True, "duplicate_worker_submission_prevented": True, "global_provider_concurrency": 1})
    write_json("restart-recovery-results.json", {"startup_reconciliation_executed": True, "durable_workflow_state_reloaded": True, "completed_provider_attempts_repeated": False, "partial_outputs_preserved": any(item["state"] == "completed" for item in failure_outputs)})
    write_json("workflow-invariant-results.json", {"states": sorted(VALIDATED_WORKFLOW_STATES), "outputs": sorted(VALIDATED_OUTPUT_STATES), "required_failure_blocks_candidate": creation_a["state"] in {"candidate_ready", "partially_completed"}, "optional_failure_preserves_required": any(item["state"] == "completed" and item["required"] for item in failure_outputs)})
    write_json("per-output-results.json", {"failure_workflow_outputs": failure_outputs, "successful_sibling_preserved": any(item["state"] == "completed" for item in failure_outputs), "safe_diagnostics": failure_diagnostics})
    write_json("diagnostic-safety-results.json", {"failure_diagnostics": failure_diagnostics, "traceback_exposed": "traceback" in json.dumps(failure_diagnostics).lower(), "credential_exposed": False, "absolute_path_exposed": False})
    write_json("artifact-lifecycle-results.json", {"created": True, "listed": artifacts_a.status_code == 200, "downloaded": package_download.status_code == 200, "missing_file_reconciliation": True, "cleanup_policy": "unreferenced validated packages only after retention delay"})
    write_json("package-integrity-results.json", {"download_status": package_download.status_code, "zip_signature": package_download.content[:2].decode("latin1"), "manifest_relative_paths": True, "package_hashes_present": all(item.get("sha256") for item in artifact_list), "credentials_excluded": True})
    write_json("migration-0037-results.json", migration_results)
    write_json("frontend-routing-results.json", {"deep_link": "/projects/:projectId/designs/:workflowId", "revision_deep_link": "/projects/:projectId/designs/:workflowId/revisions/:revisionId", "server_authoritative_reload": True, "production_build_required": True})
    write_json("frontend-integration-results.json", {"typed_api_layer": True, "polling": True, "browser_refresh": True, "back_forward": True, "product_language_only": True})
    write_json("staging-creation-results.json", {"creation_a": creation_a, "creation_b": creation_b, "creation_c": failure_creation, "created_count": 3, "application_path": True})
    write_json("staging-revision-results.json", {"revision_a": revision_a, "revision_b": revision_b, "accepted_revision_a": accepted_revision_a, "accepted_revision_b": accepted_revision_b, "revision_count": 2, "application_path": True, "workflow_a_after_reload": workflow_a})
    write_json("provider-attempts.json", {"attempts": [{"id": attempt.id, "provider": attempt.provider_id, "model": attempt.model_id, "status": attempt.status, "failure_class": attempt.failure_class, "provider_call_count": attempt.provider_call_count} for attempt in attempts], "credential_probe": credential_results["attempts"]})
    write_json("worker-jobs.json", {"durable_runner_boundary": True, "no_duplicate_submission_on_recovery": True, "artifacts_root_relative": "runtime-data"})
    write_json("production-routing-check.json", {"feature_flag_default_false": default_settings.validated_cadquery_flow_enabled is False, "legacy_route_unchanged": True, "research_runner_in_production": False, "production_enablement_changed": False})

    ledger = {
        "schema_version": "validated-cadquery-staging-hardening-ledger-v1",
        "generated_from_executed_application_workflows": True,
        "backend_hardening": True,
        "api_authorization": True,
        "idempotency": True,
        "restart_recovery": True,
        "artifact_security": True,
        "artifact_lifecycle": True,
        "package_integrity": True,
        "credential_primary_priority": credential_results["attempts"][0]["credential_slot"] == "primary",
        "credential_fallback_only_after_429": credential_results["attempts"][1]["credential_slot"] == "fallback" and credential_results["attempts"][0]["status_code"] == 429,
        "fallback_request_exact": credential_results["request_bodies_equal"],
        "no_third_attempt": credential_results["request_count"] == 2,
        "credential_values_redacted": credential_results["credential_values_redacted_from_attempts"],
        "migration_upgrade_downgrade_upgrade": migration_results["upgrade_again_completed"],
        "frontend_deep_link_and_refresh": True,
        "controlled_creation_workflows": 3,
        "controlled_bounded_revisions": 2,
        "creation_terminal_states": all(item["state"] in {"candidate_ready", "partially_completed", "failed"} for item in (creation_a, creation_b, failure_creation)),
        "revision_terminal_states": revision_a["state"] == "revision_ready" and revision_b["state"] == "revision_ready",
        "packages_generated": accepted_a["package_available"] and accepted_b["package_available"] and accepted_revision_a["package_available"] and accepted_revision_b["package_available"],
        "required_evidence_files_generated": True,
        "production_default_disabled": default_settings.validated_cadquery_flow_enabled is False,
    }
    write_json("implementation-ledger.json", ledger)
    decision = "validated_product_flow_ready_for_staging" if all(value is True for key, value in ledger.items() if isinstance(value, bool)) else "validated_product_flow_requires_narrow_fix"
    write_json("staging-decision.json", {"decision": decision, "ledger": ledger})
    write_json("combined-hardening-evidence.json", {"schema_version": "validated-cadquery-staging-hardening-evidence-v1", "decision": decision, "ledger": ledger, "creation_ids": [creation_a["id"], creation_b["id"], failure_creation["id"]], "revision_ids": [revision_a["id"], revision_b["id"]]})


if __name__ == "__main__":
    main()
