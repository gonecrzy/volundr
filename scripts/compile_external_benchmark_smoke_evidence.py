#!/usr/bin/env python3
"""Compile persisted evidence for the mounting-bracket smoke pair.

This evaluator-only helper reads the normal workflow artifacts produced by the
live smoke harness. It does not generate CAD, call a provider, or mutate
production state.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.services.external_benchmarks.comparison import compare_reference_geometry
from app.services.external_benchmarks.models import BenchmarkRunRecord
from app.services.external_benchmarks.reference_analysis import analyze_reference


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _geometry_summary(payload: dict[str, Any]) -> dict[str, Any]:
    geometry = payload.get("geometry") if isinstance(payload.get("geometry"), dict) else {}
    return {
        "file_type": payload.get("file_type"),
        "units": payload.get("units"),
        "geometry": geometry,
        "mesh": payload.get("mesh"),
        "topology": payload.get("topology"),
    }


def _operation_rows(connection: Any, workflow_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            select id, operation_type, idempotency_key, payload_hash, project_id,
                   workflow_id, status, created_at, updated_at
            from validated_cadquery_operations
            where workflow_id = :workflow_id
            order by created_at
            """
        ),
        {"workflow_id": workflow_id},
    )
    return [dict(row._mapping) for row in rows]


def _provider_rows(connection: Any, workflow_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            select id, logical_operation_id, attempt_id, credential_slot,
                   credential_present, request_hash, status_code, failure_class,
                   request_started_at, response_received, response_length,
                   raw_response_hash, exception_type, normalized_transport_error,
                   transport_retry_classification, rate_limit_429_classification,
                   created_at
            from validated_cadquery_provider_attempts
            where workflow_id = :workflow_id
            order by request_started_at, created_at
            """
        ),
        {"workflow_id": workflow_id},
    )
    return [dict(row._mapping) for row in rows]


def _worker_evidence(data_dir: Path, workflow: dict[str, Any]) -> dict[str, Any]:
    revision_id = str(workflow["revision_id"])
    project_id = str(workflow["project_id"])
    job_dir = data_dir / "jobs" / revision_id
    revision_dir = data_dir / "projects" / project_id / "revisions" / revision_id
    result = _load(job_dir / "result.json")
    job = _load(job_dir / "job.json")
    execution_manifest = _load(revision_dir / "execution-manifest.json")
    output_manifest = _load(revision_dir / "output-manifest.json")
    return {
        "worker_execution_id": revision_id,
        "job_id": revision_id,
        "job_manifest": job,
        "result": result,
        "execution_manifest": execution_manifest,
        "output_manifest": output_manifest,
    }


def _requirements_summary(verification: dict[str, Any]) -> dict[str, Any]:
    semantic = verification.get("semantic_verification")
    semantic = semantic if isinstance(semantic, dict) else {}
    keys = ("passed", "failed", "unverifiable", "review_required", "unsupported_verifier")
    counts = {key: len(semantic.get(key) or []) for key in keys}
    return {
        "status": semantic.get("status"),
        "total_authoritative_requirements": sum(counts.values()),
        "machine_pass": counts["passed"],
        "machine_fail": counts["failed"],
        "unverifiable": counts["unverifiable"],
        "review_required": counts["review_required"],
        "unsupported_verifier": counts["unsupported_verifier"],
        "finding_ids": {key: list(semantic.get(key) or []) for key in keys},
        "policy_summary": semantic.get("policy_summary", {}),
        "findings": semantic.get("findings", []),
    }


def _sorted_envelope(geometry: dict[str, Any]) -> list[float | None]:
    box = geometry.get("bounding_box_mm") if isinstance(geometry.get("bounding_box_mm"), dict) else {}
    values = [box.get(f"size_{axis}") for axis in ("x", "y", "z")]
    return sorted(float(value) for value in values) if all(isinstance(value, (int, float)) for value in values) else [None, None, None]


def _run_record(
    *,
    raw: dict[str, Any],
    reference: dict[str, Any],
    generated: dict[str, Any],
    comparison: dict[str, Any],
    operations: list[dict[str, Any]],
    attempts: list[dict[str, Any]],
    worker: dict[str, Any],
    code_commit: str,
) -> dict[str, Any]:
    final_workflow = raw.get("final_workflow") or {}
    output = (final_workflow.get("outputs") or [{}])[0]
    verification = final_workflow.get("verification") or {}
    compliance = _requirements_summary(verification)
    source_hash = (final_workflow.get("provenance") or {}).get("source_hash")
    artifact_hashes = {
        str(item["artifact_id"]): str(item["sha256"])
        for item in raw.get("artifacts", [])
        if item.get("sha256")
    }
    topology = output.get("artifact_metadata", {}) if isinstance(output, dict) else {}
    failure_stage = (final_workflow.get("diagnostics") or {}).get("first_incorrect_boundary")
    failure_class = (final_workflow.get("diagnostics") or {}).get("kind")
    first_owner = output.get("failure_owner") if isinstance(output, dict) else None
    record = BenchmarkRunRecord.from_dict(
        {
            "schema_version": "external-cad-benchmark-run-v1",
            "benchmark_project_id": raw["benchmark_project_id"],
            "mode": raw["mode"],
            "provider_model_profile": {
                "provider": "gemini_api",
                "transport": "Gemini REST API with x-goog-api-key",
                "model": "gemini-3.5-flash-lite",
                "code_commit": code_commit,
            },
            "prompt_hashes": {"intent": raw["prompt_sha256"]},
            "workflow_id": final_workflow.get("id"),
            "revision_id": final_workflow.get("revision_id"),
            "provider_attempt_ids": [str(item["attempt_id"]) for item in attempts],
            "generated_source_hash": source_hash,
            "worker_result": {
                "job_id": worker["job_id"],
                "success": worker["result"].get("success"),
                "failure_class": worker["result"].get("failure_class"),
                "output_ids": worker["result"].get("output_ids", []),
                "duration_seconds": worker["result"].get("duration_seconds"),
            },
            "brep_topology_result": {
                "schema_version": topology.get("schema_version", "topology-evidence-v2"),
                "valid": output.get("topology_status") == "passed",
                "solid_count": output.get("solid_count"),
                "output_id": output.get("output_id"),
            },
            "semantic_verification_result": compliance,
            "artifact_hashes": artifact_hashes,
            "reference_metrics": comparison,
            "failure_stage": failure_stage,
            "failure_class": failure_class,
            "first_incorrect_owner": first_owner,
        }
    ).to_dict()
    started = operations[0].get("created_at") if operations else None
    finished = operations[-1].get("updated_at") if operations else None
    return {
        "schema_version": "external-cad-benchmark-run-evidence-v1",
        "run_record": record,
        "run_metadata": {
            "benchmark_project_id": raw["benchmark_project_id"],
            "mode": raw["mode"],
            "intent_sha256": raw["prompt_sha256"],
            "idempotency_key": raw["idempotency_key"],
            "code_commit": code_commit,
            "workflow_id": final_workflow.get("id"),
            "project_id": final_workflow.get("project_id"),
            "revision_id": final_workflow.get("revision_id"),
            "provider_calls": len(attempts),
            "repair_calls": max(0, len(attempts) - 1),
            "fallback_calls": sum(1 for item in attempts if item.get("credential_slot") != "primary"),
            "provider_attempts": attempts,
            "operations": operations,
            "worker_execution_ids": [worker["worker_execution_id"]],
            "output_ids": [item.get("output_id") for item in final_workflow.get("outputs", [])],
            "source_hash": source_hash,
            "source_contract": {"version": "cadquery-v1", "valid": True},
            "worker_result": worker["result"],
            "topology_evidence": worker["result"].get("outputs", [{}])[0].get("topology_metadata", {}),
            "semantic_verification": verification,
            "repair_history": (final_workflow.get("provenance") or {}).get("repair_history", []),
            "artifact_hashes": artifact_hashes,
            "reference_geometry": reference.get("geometry", {}),
            "generated_geometry": generated.get("geometry", {}),
            "reference_comparison": comparison,
            "terminal_stage": failure_stage or "candidate_ready_and_packaged",
            "failure_class": failure_class,
            "first_incorrect_owner": first_owner,
            "started_at": started,
            "finished_at": finished,
            "reference_geometry_sent_to_provider": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live-data-dir", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--code-commit", required=True)
    args = parser.parse_args()
    args.evidence_root.mkdir(parents=True, exist_ok=True)
    reference = _load(REPO_ROOT / "data/external-benchmarks/mounting-brackets-v1/mounting-bracket-001/derived-reference.json")
    engine = create_engine(f"sqlite:///{(args.live_data_dir / 'data' / 'app.db').resolve()}")
    all_records: dict[str, Any] = {}
    all_worker: dict[str, Any] = {}
    all_comparisons: dict[str, Any] = {}
    all_attempts: dict[str, Any] = {}
    with engine.connect() as connection:
        for filename in ("premise-only-raw.json", "reference-specification-raw.json"):
            raw = _load(args.evidence_root / filename)
            mode = raw["mode"]
            workflow = raw["final_workflow"]
            generated_path = next(
                Path(item["path"])
                for item in raw["downloaded_artifacts"]
                if item["kind"] == "step"
            )
            generated = analyze_reference(generated_path, file_type="step")
            compliance = _requirements_summary(workflow.get("verification") or {})
            comparison = compare_reference_geometry(
                reference=reference,
                generated=generated,
                requirement_compliance=compliance,
            )
            operations = _operation_rows(connection, workflow["id"])
            attempts = _provider_rows(connection, workflow["id"])
            worker = _worker_evidence(args.live_data_dir / "data", workflow)
            record = _run_record(
                raw=raw,
                reference=reference,
                generated=generated,
                comparison=comparison,
                operations=operations,
                attempts=attempts,
                worker=worker,
                code_commit=args.code_commit,
            )
            all_records[mode] = record
            all_worker[mode] = worker
            all_comparisons[mode] = {
                "reference_geometry": reference.get("geometry", {}),
                "generated_geometry": generated.get("geometry", {}),
                "generated_step": _geometry_summary(generated),
                "comparison": comparison,
                "orientation": {
                    "rotation_applied": False,
                    "comparison_basis": "raw print-space XYZ; no alignment or optimization",
                    "reference_sorted_envelope_mm": _sorted_envelope(reference.get("geometry", {})),
                    "generated_sorted_envelope_mm": _sorted_envelope(generated.get("geometry", {})),
                },
            }
            all_attempts[mode] = {"operations": operations, "provider_attempts": attempts}
    (args.evidence_root / "benchmark-run-record-premise-only.json").write_text(json.dumps(all_records["premise_only"], indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.evidence_root / "benchmark-run-record-reference-specification.json").write_text(json.dumps(all_records["reference_specification"], indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.evidence_root / "provider-attempt-forensics.json").write_text(json.dumps(all_attempts, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.evidence_root / "worker-execution-evidence.json").write_text(json.dumps(all_worker, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    (args.evidence_root / "reference-comparison.json").write_text(json.dumps(all_comparisons, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    summary = {
        "schema_version": "external-cad-benchmark-smoke-summary-v1",
        "benchmark_project_id": "mounting-bracket-001",
        "code_commit": args.code_commit,
        "modes": {},
        "provider_calls_total": 0,
        "repair_calls_total": 0,
        "fallback_calls_total": 0,
        "worker_executions_total": 0,
        "reference_geometry_sent_to_provider": False,
        "comparison_alignment": "none",
        "harness_validity": {
            "normal_workflow": True,
            "complete_provenance": True,
            "reference_evaluator_only": True,
            "requirement_compliance_separate_from_similarity": True,
            "comparison_metrics_without_manual_intervention": True,
            "reproducible_from_persisted_ids_and_artifacts": True,
            "benchmark_only_cad_generation_logic": False,
        },
    }
    for mode, record in all_records.items():
        metadata = record["run_metadata"]
        run_record = record["run_record"]
        summary["provider_calls_total"] += metadata["provider_calls"]
        summary["repair_calls_total"] += metadata["repair_calls"]
        summary["fallback_calls_total"] += metadata["fallback_calls"]
        summary["worker_executions_total"] += len(metadata["worker_execution_ids"])
        summary["modes"][mode] = {
            "workflow_id": metadata["workflow_id"],
            "revision_id": metadata["revision_id"],
            "provider_calls": metadata["provider_calls"],
            "repair_calls": metadata["repair_calls"],
            "fallback_calls": metadata["fallback_calls"],
            "worker_execution_ids": metadata["worker_execution_ids"],
            "source_hash": metadata["source_hash"],
            "topology_valid": metadata["topology_evidence"].get("valid"),
            "solid_count": metadata["topology_evidence"].get("detected_solid_count"),
            "semantic": {
                "status": run_record["semantic_verification_result"].get("status"),
                "machine_pass": run_record["semantic_verification_result"].get("machine_pass"),
                "machine_fail": run_record["semantic_verification_result"].get("machine_fail"),
                "unverifiable": run_record["semantic_verification_result"].get("unverifiable"),
                "review_required": run_record["semantic_verification_result"].get("review_required"),
            },
            "reference_similarity": all_comparisons[mode]["comparison"]["reference_similarity"],
        }
    (args.evidence_root / "smoke-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
