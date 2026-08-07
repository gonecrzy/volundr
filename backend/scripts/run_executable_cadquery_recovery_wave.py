"""Replay a frozen executable-CadQuery corpus through generic recovery policy.

This harness only consumes frozen evidence.  It never calls Gemini, edits CAD,
or substitutes a fixture-specific repair.  A later orchestrator run may add
durable execution and blind-review records to the same output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.executable_cadquery.package_review import build_neutral_measurement_report
from app.services.executable_cadquery.recovery import (
    FailureObservation,
    RECOVERY_POLICIES,
    RECOVERY_POLICY_VERSION,
    RecoveryRouter,
)
from app.services.executable_cadquery.review import build_blind_review_packet, build_blind_review_record
from app.services.executable_cadquery.semantic import evaluate_executable_cadquery_semantics_for_outputs
from app.services.executable_cadquery.semantic_policy import (
    CANDIDATE_POLICY_VERSION,
    SEMANTIC_POLICY_VERSION,
    derive_candidate_policy,
    evaluate_semantic_policy,
)


def main() -> int:
    args = _parse_args()
    manifest_path = args.manifest.resolve()
    corpus_root = args.corpus_root.resolve()
    output_root = args.output_root.resolve()
    manifest = _read_json(manifest_path)
    manifest_projects = manifest.get("projects")
    if not isinstance(manifest_projects, list) or not manifest_projects:
        raise SystemExit("corpus manifest must contain projects")
    projects = [
        item
        for item in manifest_projects
        if isinstance(item, Mapping) and (corpus_root / str(item.get("project_id"))).is_dir()
    ]
    if not projects:
        raise SystemExit("corpus manifest has no frozen project directories")
    output_root.mkdir(parents=True, exist_ok=True)

    _write_json(
        output_root / "preregistration.json",
        {
            "schema_version": "executable-cadquery-recovery-preregistration-v1",
            "mode": "frozen_evidence_replay",
            "corpus_manifest": str(manifest_path),
            "corpus_schema_version": manifest.get("schema_version"),
            "recovery_policy_version": RECOVERY_POLICY_VERSION,
            "semantic_policy_version": SEMANTIC_POLICY_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "projects": [str(item.get("project_id")) for item in projects if isinstance(item, Mapping)],
            "excluded_manifest_projects": [
                str(item.get("project_id"))
                for item in manifest_projects
                if isinstance(item, Mapping) and item not in projects
            ],
        },
    )
    _write_json(
        output_root / "recovery-policy.json",
        {
            "schema_version": "executable-cadquery-recovery-policy-record-v1",
            "policy_version": RECOVERY_POLICY_VERSION,
            "policies": {
                name: {
                    "owner": policy.owner,
                    "action": policy.action,
                    "maximum_attempts": policy.maximum_attempts,
                    "progress_requirement": policy.progress_requirement,
                    "restart_stage": policy.restart_stage,
                    "invalidates": list(policy.invalidates),
                    "repair_level": policy.repair_level,
                    "recoverability": policy.recoverability,
                }
                for name, policy in sorted(RECOVERY_POLICIES.items())
            },
        },
    )
    _write_json(
        output_root / "semantic-policy.json",
        {
            "schema_version": "executable-cadquery-semantic-policy-record-v1",
            "semantic_policy_version": SEMANTIC_POLICY_VERSION,
            "candidate_policy_version": CANDIDATE_POLICY_VERSION,
            "requirement_policies": ["machine_required", "review_required", "informational"],
            "missing_machine_measurement_result": "unsupported_verifier",
            "candidate_states": [
                "candidate_blocked",
                "candidate_ready_for_review",
                "candidate_fully_verified",
            ],
        },
    )

    project_reports: list[dict[str, Any]] = []
    artifact_results: list[dict[str, Any]] = []
    convergence: list[dict[str, Any]] = []
    for project in projects:
        if not isinstance(project, Mapping):
            continue
        existing_review = _read_optional(output_root / f"{project['project_id']}-independent-review.json")
        report = _replay_project(project, corpus_root, existing_review=existing_review)
        project_id = str(project["project_id"])
        _write_json(output_root / f"{project_id}-recovery.json", report)
        review_file = report["independent_review"] or {
            "schema_version": "executable-cadquery-independent-review-status-v1",
            "project_id": project_id,
            "status": "pending" if report["review_packet"] else "not_run",
            "reason": "fresh blind reviewer required after package eligibility" if report["review_packet"] else report["review_block_reason"],
        }
        _write_json(output_root / f"{project_id}-independent-review.json", review_file)
        project_reports.append(report)
        artifact_results.append(report["artifact_result"])
        convergence.append(report["repair_convergence"])

    _write_json(output_root / "artifact-results.json", {"projects": artifact_results})
    _write_json(output_root / "repair-convergence.json", {"projects": convergence})
    _write_json(
        output_root / "test-summary.json",
        {
            "schema_version": "executable-cadquery-recovery-test-summary-v1",
            "mode": "frozen_evidence_replay",
            "project_count": len(project_reports),
            "candidate_blocked": sum(item["candidate_policy"]["state"] == "candidate_blocked" for item in project_reports),
            "review_pending": sum(bool(item["review_packet"]) and not item["independent_review"] for item in project_reports),
            "provider_calls": 0,
            "worker_calls": 0,
        },
    )
    all_pass = all(
        item.get("independent_review", {}).get("final_verdict") == "PASS"
        for item in project_reports
    )
    _write_json(
        output_root / "final-decision.json",
        {
            "schema_version": "executable-cadquery-recovery-wave-decision-v1",
            "decision": "recovery_wave_existing_corpus_ready" if all_pass else "recovery_wave_existing_corpus_blocked",
            "all_independent_reviews_pass": all_pass,
            "projects": {
                item["project_id"]: {
                    "candidate_state": item["candidate_policy"]["state"],
                    "independent_review": item.get("independent_review", {}).get("final_verdict"),
                    "terminal_reason": item.get("recovery_decision", {}).get("terminal_reason"),
                }
                for item in project_reports
            },
        },
    )
    return 0


def _replay_project(
    project: Mapping[str, Any],
    corpus_root: Path,
    *,
    existing_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    project_id = str(project["project_id"])
    project_root = corpus_root / project_id
    contract = dict(project["contract"])
    output_manifest = _read_optional(project_root / "revision" / "output-manifest.json")
    worker_result = _read_optional(project_root / "worker" / "result.json")
    outputs = _persisted_outputs(contract, output_manifest, worker_result, project_root)
    stl_paths = {
        output["output_id"]: Path(output["stl_path"])
        for output in outputs
        if output.get("stl_path")
    }
    if stl_paths:
        semantic_raw = evaluate_executable_cadquery_semantics_for_outputs(
            stl_paths=stl_paths,
            design_contract=contract,
        )
    else:
        semantic_raw = {
            "status": "unverifiable",
            "passed": [],
            "failed": [],
            "unverifiable": [str(item.get("requirement_id")) for item in contract.get("requirements", [])],
            "findings": [],
            "diagnostic": "required final mesh artifacts are unavailable",
        }
    semantic = evaluate_semantic_policy(semantic_raw, contract)
    package_path = project_root / "package.zip"
    package_available = package_path.is_file()
    package_valid = False
    neutral_report: dict[str, Any] | None = None
    review_packet: dict[str, Any] | None = None
    if package_available:
        try:
            with ZipFile(package_path) as archive:
                package_manifest = json.loads(archive.read("manifest.json"))
            neutral_report = build_neutral_measurement_report(package_path, package_manifest)
            package_valid = True
            review_packet = build_blind_review_packet(
                original_prompt=str(project["prompt"]),
                final_output_identities=neutral_report["output_identities"],
                package_manifest=package_manifest,
                neutral_measurement_report=neutral_report,
                fixed_views=[str(path) for path in sorted((project_root / "rendered").glob("*"))],
                units=str(contract.get("units") or "mm"),
            )
            review_packet["package_path"] = str(package_path)
        except (OSError, BadZipFile, KeyError, json.JSONDecodeError):
            package_valid = False

    candidate = derive_candidate_policy(
        outputs=outputs,
        semantic_verification=semantic,
        artifacts={
            "package_required": True,
            "package_available": package_available,
            "valid": package_valid if package_available else None,
        },
    )
    independent_review: dict[str, Any] = {}
    if existing_review and existing_review.get("final_verdict"):
        independent_review = build_blind_review_record(
            review_cycle=int(existing_review.get("review_cycle") or 1),
            reviewer_result=existing_review,
            candidate_policy=candidate,
        )
        candidate = derive_candidate_policy(
            outputs=outputs,
            semantic_verification=semantic,
            artifacts={
                "package_required": True,
                "package_available": package_available,
                "valid": package_valid if package_available else None,
            },
            independent_review={"verdict": independent_review["final_verdict"]},
        )
    failure_class, evidence, boundary = _first_failure(
        outputs,
        semantic,
        package_available,
        package_valid,
        worker_result=worker_result,
    )
    recovery_decision: dict[str, Any] = {}
    if independent_review.get("final_verdict") == "FAIL":
        failure_class, evidence, boundary = _review_failure(independent_review)
    if failure_class is not None:
        router = RecoveryRouter()
        observation = FailureObservation(
            observed_stage=router.earliest_stage(boundary, failure_class),
            failure_class=failure_class,
            evidence=evidence,
            attempt_ordinal=1,
        )
        recovery_decision = router.route(observation).to_record()

    review_block_reason = None
    if not review_packet:
        review_block_reason = "package is unavailable or invalid"
    return {
        "schema_version": "executable-cadquery-project-recovery-v1",
        "project_id": project_id,
        "title": project.get("title"),
        "mode": "frozen_evidence_replay",
        "frozen_prompt_sha256": project.get("prompt_sha256"),
        "frozen_contract_sha256": project.get("contract_sha256"),
        "outputs": outputs,
        "semantic_verification": semantic,
        "candidate_policy": candidate,
        "package": {
            "path": str(package_path),
            "available": package_available,
            "valid": package_valid,
            "neutral_measurement_report": neutral_report,
        },
        "recovery_decision": recovery_decision,
        "review_packet": review_packet,
        "review_block_reason": review_block_reason,
        "independent_review": independent_review,
        "artifact_result": {
            "project_id": project_id,
            "required_outputs": len(outputs),
            "available_stl_outputs": len(stl_paths),
            "package_available": package_available,
            "package_valid": package_valid,
        },
        "repair_convergence": {
            "project_id": project_id,
            "mode": "frozen_evidence_replay",
            "provider_operations": 0,
            "worker_operations": 0,
            "recovery_action_executed": False,
            "progress": "classification_only",
        },
    }


def _first_failure(
    outputs: list[dict[str, Any]],
    semantic: Mapping[str, Any],
    package_available: bool,
    package_valid: bool,
    *,
    worker_result: Mapping[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any], str]:
    worker = worker_result if isinstance(worker_result, Mapping) else {}
    diagnostics = worker.get("execution_diagnostics") or worker.get("diagnostics") or {}
    if isinstance(diagnostics, Mapping):
        phase = str(
            diagnostics.get("failure_phase")
            or diagnostics.get("active_phase")
            or diagnostics.get("phase")
            or ""
        ).lower()
        message = str(
            diagnostics.get("failure_message")
            or diagnostics.get("message")
            or worker.get("error_message")
            or ""
        )
        exception_type = str(diagnostics.get("failure_exception_type") or "")
        if phase in {"build_function", "module_import", "source_execution", "execution"} and (
            message or exception_type or diagnostics.get("failure_operation")
        ):
            execution_evidence = dict(diagnostics)
            if worker.get("error_message") and "message" not in execution_evidence:
                execution_evidence["message"] = worker["error_message"]
            if exception_type:
                execution_evidence["exception_type"] = exception_type
            if message:
                execution_evidence["message"] = message
            execution_evidence["worker_phase"] = phase
            return (
                RecoveryRouter.classify_failure("execution", execution_evidence),
                execution_evidence,
                "execution",
            )
    for output in outputs:
        if output.get("topology_status") not in {"valid", "passed", "verified", "ok"}:
            return (
                RecoveryRouter.classify_failure(
                    "topology",
                    {
                        "valid": False,
                        "expected_solid_count": output.get("expected_solid_count"),
                        "detected_solid_count": output.get("detected_solid_count"),
                    },
                ),
                {"output_id": output.get("output_id"), "topology": output.get("topology")},
                "topology",
            )
        if output.get("artifact_available") is not True:
            return (
                "stl_export_failure",
                {"output_id": output.get("output_id"), "valid_shape": True},
                "artifact",
            )
    if semantic.get("failed"):
        return "semantic_requirement_failed", {"failed": semantic.get("failed"), "measurement_available": True}, "semantic"
    if semantic.get("unsupported_verifier") or semantic.get("unverifiable"):
        return "semantic_requirement_unverifiable", {"unverifiable": semantic.get("unsupported_verifier") or semantic.get("unverifiable"), "measurement_available": False}, "semantic"
    if not package_available or not package_valid:
        return "package_generation_failure", {"package_available": package_available, "package_valid": package_valid}, "package"
    return None, {}, "candidate_review"


def _review_failure(review: Mapping[str, Any]) -> tuple[str, dict[str, Any], str]:
    violated = [
        item
        for item in review.get("requirements", [])
        if isinstance(item, Mapping) and item.get("verdict") == "violated"
    ]
    measured = [item for item in violated if item.get("evidence_type") == "measured"]
    if measured:
        return (
            "semantic_requirement_failed",
            {
                "failed_requirement_ids": [str(item.get("requirement_id")) for item in measured],
                "measurement_available": True,
                "review_discrepancies": review.get("discrepancies", []),
            },
            "semantic",
        )
    return (
        "artifact_integrity_failure",
        {"review_discrepancies": review.get("discrepancies", [])},
        "package",
    )


def _persisted_outputs(
    contract: Mapping[str, Any],
    output_manifest: Mapping[str, Any],
    worker_result: Mapping[str, Any],
    project_root: Path,
) -> list[dict[str, Any]]:
    manifest_outputs = {
        str(item.get("output_id")): item
        for item in output_manifest.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    }
    worker_outputs = {
        str(item.get("output_id")): item
        for item in worker_result.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    }
    records: list[dict[str, Any]] = []
    for contract_output in contract.get("outputs", []):
        if not isinstance(contract_output, Mapping):
            continue
        output_id = str(contract_output["output_id"])
        manifest_output = manifest_outputs.get(output_id, {})
        worker_output = worker_outputs.get(output_id, {})
        filename = str(manifest_output.get("filename") or f"{output_id}.stl")
        stl_path = project_root / "revision" / "stl" / filename
        step_path = project_root / "revision" / "step" / f"{Path(filename).stem}.step"
        brep_path = project_root / "revision" / "brep" / f"{Path(filename).stem}.brep"
        topology = manifest_output.get("topology") or worker_output.get("topology_metadata") or {}
        state = str(manifest_output.get("state") or ("ready" if worker_output.get("success") else "failed"))
        artifact_paths = (stl_path, step_path, brep_path)
        artifact_available = all(path.is_file() for path in artifact_paths)
        declared_hashes = {
            "stl": manifest_output.get("stl", {}).get("sha256") or manifest_output.get("sha256"),
            "step": manifest_output.get("step", {}).get("sha256"),
            "brep": manifest_output.get("brep", {}).get("sha256"),
        }
        artifact_integrity = artifact_available and all(
            declared_hashes[k] is None or _sha256(path) == declared_hashes[k]
            for k, path in zip(("stl", "step", "brep"), artifact_paths)
        )
        records.append(
            {
                "output_id": output_id,
                "required": bool(contract_output.get("required", True)),
                "state": state,
                "worker_status": "completed"
                if worker_output.get("success") or state in {"ready", "ready_with_warnings", "completed"}
                else "failed",
                "topology_status": "valid" if topology.get("valid") is True else "invalid",
                "topology": topology,
                "expected_solid_count": contract_output.get("expected_solid_count"),
                "detected_solid_count": topology.get("detected_solid_count"),
                "stl_path": str(stl_path) if stl_path.is_file() else None,
                "artifact_available": artifact_available,
                "artifact_integrity": artifact_integrity,
            }
        )
    return records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, Mapping) else {}


def _read_optional(path: Path) -> dict[str, Any]:
    try:
        return _read_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
