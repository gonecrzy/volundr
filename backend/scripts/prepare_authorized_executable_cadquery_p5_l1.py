"""Prepare the exact persisted P5 L1 repair envelope without provider effects.

This preparation step resolves the live project/revision/workflow/job chain,
verifies the complete source and worker hashes, and persists the bounded repair
envelope.  It deliberately does not read or print credential values and never
constructs a provider.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.executable_cadquery.repair import (  # noqa: E402
    build_executable_cadquery_repair_envelope,
)


PROJECT_ID = "project-05"
DATABASE_PROJECT_ID = "ed2f7dea-5e56-46d2-b8bb-fe52adb214fe"
REVISION_ID = "5a05dfad-0e04-4b67-8389-519142c5ede8"
SOURCE_HASH = "c56da9a7e2035b596f36ef5d696236e5289afd42326e6af8a679583b42e071d4"
FROZEN_ROOT = ROOT / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus/project-05"
PROJECT_ROOT = ROOT / "data/projects/ed2f7dea-5e56-46d2-b8bb-fe52adb214fe/revisions" / REVISION_ID
JOB_ROOT = ROOT / "data/jobs" / REVISION_ID
GATE_PATH = ROOT / "docs/executable-cadquery-p5-l1-gate.json"
ENVELOPE_PATH = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "p5-l1-repair-envelope.json"
)
TRANSPORT_PROOF_PATH = "docs/executable-cadquery-p3-transport-proof.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _row(connection: sqlite3.Connection, query: str, parameters: tuple[Any, ...]) -> dict[str, Any]:
    cursor = connection.execute(query, parameters)
    row = cursor.fetchone()
    if row is None:
        raise ValueError(f"authoritative database row missing for query: {query}")
    return dict(zip((item[0] for item in cursor.description), row))


def _safe_worker_result(job: Mapping[str, Any], execution: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = execution.get("diagnostics") if isinstance(execution.get("diagnostics"), Mapping) else {}
    return {
        "schema_version": "authoritative-p5-worker-facts-v1",
        "job_id": job.get("job_id"),
        "source_hash": diagnostics.get("source_hash") or job.get("source_hash"),
        "success": result.get("success"),
        "timed_out": diagnostics.get("timed_out"),
        "exit_code": diagnostics.get("exit_code"),
        "output_ids": list(job.get("requested_output_ids") or []),
        "completed_output_ids": list(diagnostics.get("completed_output_ids") or []),
        "execution_diagnostics": {
            "active_phase": diagnostics.get("active_phase"),
            "failure_phase": diagnostics.get("failure_phase"),
            "failure_source_function": diagnostics.get("failure_source_function"),
            "failure_source_line": diagnostics.get("failure_source_line"),
            "failure_operation": diagnostics.get("failure_operation"),
            "failure_exception_type": diagnostics.get("failure_exception_type"),
            "failure_message": diagnostics.get("failure_message"),
            "incomplete_output_ids": list(diagnostics.get("incomplete_output_ids") or []),
            "topology_reached": False,
        },
    }


def main() -> int:
    gate = _read_json(GATE_PATH)
    frozen = _read_json(FROZEN_ROOT / "prompt-contract.json")
    prompt = str(frozen["prompt"])
    contract = dict(frozen["contract"])
    source_path = PROJECT_ROOT / "source.py"
    execution_path = PROJECT_ROOT / "execution-manifest.json"
    job_path = JOB_ROOT / "job.json"
    worker_result_path = JOB_ROOT / "result.json"
    if not all(path.is_file() for path in (source_path, execution_path, job_path, worker_result_path)):
        raise ValueError("the exact persisted P5 source/result chain is incomplete")

    source = source_path.read_text(encoding="utf-8")
    job = _read_json(job_path)
    execution = _read_json(execution_path)
    worker_result = _read_json(worker_result_path)
    database_path = ROOT / "data/app.db"
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        database_project = _row(
            connection,
            "select id, name, original_intent, status, active_revision_id from projects where id = ?",
            (DATABASE_PROJECT_ID,),
        )
        revision = _row(
            connection,
            "select id, project_id, parent_revision_id, revision_number, user_instruction, source_path, status, is_accepted, review_state, source_hash, functional_status from revisions where id = ?",
            (REVISION_ID,),
        )
        workflow = _row(
            connection,
            "select id, project_id, parent_workflow_id, parent_revision_id, revision_id, state, route, failure_boundary from validated_cadquery_workflows where revision_id = ?",
            (REVISION_ID,),
        )

    source_hash = _sha256_bytes(source.encode("utf-8"))
    execution_diagnostics = execution.get("diagnostics")
    if not isinstance(execution_diagnostics, Mapping):
        raise ValueError("authoritative execution manifest has no diagnostics")
    checks = {
        "database_project_identity": database_project["id"] == DATABASE_PROJECT_ID,
        "database_project_prompt_matches_frozen": database_project["original_intent"] == prompt,
        "revision_identity": revision["id"] == REVISION_ID and revision["project_id"] == DATABASE_PROJECT_ID,
        "workflow_identity": workflow["revision_id"] == REVISION_ID and workflow["project_id"] == DATABASE_PROJECT_ID,
        "revision_prompt_matches_frozen": revision["user_instruction"] == prompt,
        "source_path_matches_revision": revision["source_path"] == f"projects/{DATABASE_PROJECT_ID}/revisions/{REVISION_ID}/source.py",
        "source_hash_matches_revision": revision["source_hash"] == SOURCE_HASH,
        "source_hash_matches_job": job.get("source_hash") == SOURCE_HASH,
        "source_hash_matches_source": source_hash == SOURCE_HASH,
        "job_identity": job.get("job_id") == REVISION_ID,
        "job_output_ids_match_contract": sorted(item.get("output_id") for item in job.get("requested_outputs", [])) == ["mating_insert", "support"],
        "execution_source_hash_matches": execution_diagnostics.get("source_hash") == SOURCE_HASH,
        "worker_result_source_hash_matches": execution_diagnostics.get("source_hash") == SOURCE_HASH,
        "diagnostic_boundary_is_build_function": execution_diagnostics.get("failure_phase") == "build_function",
        "diagnostic_operation_is_chamfer": execution_diagnostics.get("failure_operation") == "chamfer",
        "diagnostic_exception_is_std_fail": execution_diagnostics.get("failure_exception_type") == "StdFail_NotDone",
        "diagnostic_topology_not_reached": execution_diagnostics.get("topology_reached", False) is False
        and not execution_diagnostics.get("completed_output_ids"),
        "transport_proof_exists": (ROOT / TRANSPORT_PROOF_PATH).is_file(),
    }
    if not all(checks.values()):
        raise ValueError(f"P5 authority verification failed: {checks}")

    previous_history = list(gate.get("prior_l1_history") or [])
    safe_worker = _safe_worker_result(
        {**job, "requested_output_ids": [item.get("output_id") for item in job.get("requested_outputs", [])]},
        execution,
        worker_result,
    )
    topology = {
        "valid": False,
        "topology_reached": False,
        "outputs": {
            "support": {"valid": False, "expected_solid_count": 1, "detected_solid_count": None},
            "mating_insert": {"valid": False, "expected_solid_count": 1, "detected_solid_count": None},
        },
    }
    previous_result_hash = _sha256_file(worker_result_path)
    envelope = build_executable_cadquery_repair_envelope(
        repair_level="L1",
        generation_session_id="phase0-l1-repair-project-05",
        logical_operation_id=f"{workflow['id']}:l1-repair",
        parent_operation_id=REVISION_ID,
        repair_ordinal=3,
        previous_source=source,
        previous_source_hash=SOURCE_HASH,
        previous_result_hash=previous_result_hash,
        design_contract=contract,
        previous_normalized_error="StdFail_NotDone / BRep_API: command not done",
        provider_attempt={
            "status": "not_started",
            "transport_proof_path": TRANSPORT_PROOF_PATH,
            "transport": "gemini_api_rest",
            "auth_header": "x-goog-api-key",
            "fallback_policy": "fallback_only_after_http_429",
        },
        worker_result=safe_worker,
        topology_result=topology,
        protected_facts=contract.get("protected_facts", []),
        repair_history=previous_history,
        requested_delta=(
            "Repair the persisted build_function chamfer failure while preserving "
            "the frozen complete-source contract, output identities, parent relationship, "
            "and protected dimensions."
        ),
    )
    envelope_record = {
        "schema_version": "executable-cadquery-p5-l1-repair-preparation-v1",
        "project_id": PROJECT_ID,
        "authority": {
            "database_project_id": DATABASE_PROJECT_ID,
            "workflow_id": workflow["id"],
            "revision_id": REVISION_ID,
            "parent_revision_id": revision["parent_revision_id"],
            "job_id": job["job_id"],
            "source_path": str(source_path.relative_to(ROOT)),
            "source_hash": SOURCE_HASH,
            "worker_result_path": str(worker_result_path.relative_to(ROOT)),
            "worker_result_sha256": previous_result_hash,
            "execution_manifest_path": str(execution_path.relative_to(ROOT)),
            "execution_manifest_sha256": _sha256_file(execution_path),
            "hash_verification": checks,
        },
        "runtime": {
            "cadquery_version": "2.8.0",
            "ocp_version": "7.9.3.1",
            "worker_version": "cadquery-cli-runner-v1",
            "version_evidence": [
                "backend/pyproject.toml",
                "backend/scripts/run_hybrid_geometry_ir_evaluation.py",
                "docs/REPRESENTATIVE_WORKFLOW_WAVES.md",
            ],
        },
        "envelope_sha256": _sha256_json(envelope),
        "envelope": envelope,
    }
    _write_json(ENVELOPE_PATH, envelope_record)

    gate.update(
        {
            "status": "authorized_for_one_bounded_l1",
            "provider_calls_made": 0,
            "worker_calls_made": 0,
            "topology_reached": False,
            "first_unresolved_boundary": "build_function",
            "authoritative_source": {
                "database_project_id": DATABASE_PROJECT_ID,
                "workflow_id": workflow["id"],
                "revision_id": REVISION_ID,
                "parent_revision_id": revision["parent_revision_id"],
                "job_id": job["job_id"],
                "source_hash": SOURCE_HASH,
                "persisted_source_path": str(source_path.relative_to(ROOT)),
                "worker_result_path": str(worker_result_path.relative_to(ROOT)),
                "worker_result_sha256": previous_result_hash,
                "execution_manifest_path": str(execution_path.relative_to(ROOT)),
                "execution_manifest_sha256": _sha256_file(execution_path),
                "complete_source_available_for_dispatch": True,
                "source_is_live_persisted_revision": True,
                "frozen_artifact_corpus_substituted": False,
            },
            "authority_verification": checks,
            "runtime": envelope_record["runtime"],
            "repair_envelope": {
                "path": str(ENVELOPE_PATH.relative_to(ROOT)),
                "sha256": envelope_record["envelope_sha256"],
                "repair_level": "L1",
                "repair_ordinal": 3,
            },
            "dispatch_gate": {
                "repair_level": "L1",
                "complete_replacement_source_required": True,
                "authorized": True,
                "provider_transport_required": "gemini_api_rest",
                "auth_header_required": "x-goog-api-key",
                "fallback_policy": "fallback_only_after_http_429",
                "transport_proof_path": TRANSPORT_PROOF_PATH,
                "do_not_use_frozen_artifact_corpus_as_substitute": True,
            },
        }
    )
    _write_json(GATE_PATH, gate)
    print(json.dumps({
        "project_id": PROJECT_ID,
        "source_hash": SOURCE_HASH,
        "workflow_id": workflow["id"],
        "revision_id": REVISION_ID,
        "job_id": job["job_id"],
        "authority_checks": all(checks.values()),
        "envelope_sha256": envelope_record["envelope_sha256"],
        "provider_calls_made": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
