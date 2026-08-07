"""Run the bounded P2/P4 L3 semantic repair operations.

Each invocation is intentionally single-use for one frozen project.  The
script re-verifies the selected identity/source/result chain and the exact
prepared semantic envelope before making one provider operation.  It uses the
shared application settings/provider construction path and the validated
Gemini REST transport; no CLI/OAuth path is available here.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from app.api.dependencies import build_executable_ai_provider
from app.core.config import settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.cadquery_runner import CadQueryCliRunner, CadQueryCompileResult
from app.services.executable_cadquery.contract import parse_executable_cadquery_response
from app.services.executable_cadquery.package_review import build_neutral_measurement_report
from app.services.executable_cadquery.review import build_blind_review_packet, build_blind_review_record
from app.services.executable_cadquery.semantic import evaluate_executable_cadquery_semantics_for_outputs
from app.services.executable_cadquery.semantic_policy import derive_candidate_policy, evaluate_semantic_policy
from app.services.geometry.snapshots import SnapshotRenderSettings, render_stl_view

from scripts.reconcile_executable_cadquery_phase0 import _blind_reviewer_result


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs/executable-cadquery-topology-replay-v2.json"
AUTHORIZATION_PATH = ROOT / "docs/executable-cadquery-semantic-repair-authorizations.json"
ENVELOPE_ROOT = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "semantic-repair-envelopes"
)
RESULT_ROOT = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "authorized-l3-results"
)
MATRIX_PATH = ROOT / "docs/executable-cadquery-phase0-authoritative-matrix.json"


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


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _canonical_output_ids(contract: Mapping[str, Any]) -> list[str]:
    return [
        str(item["output_id"])
        for item in contract.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    ]


def _project_record(report: Mapping[str, Any], project_id: str) -> dict[str, Any]:
    project = next(
        item for item in report.get("projects", [])
        if isinstance(item, Mapping) and item.get("project_id") == project_id
    )
    return dict(project)


def _verify_authority(
    *,
    project: Mapping[str, Any],
    envelope_record: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority = project.get("authority")
    if not isinstance(authority, Mapping):
        raise ValueError("selected project has no authority record")
    identity = authority.get("identity")
    if not isinstance(identity, Mapping):
        raise ValueError("selected project has no persisted identity")
    if authority.get("hash_verification", {}).get("valid") is not True:
        raise ValueError("selected authority is not hash-verified")

    source_path = ROOT / str(authority["source_path"])
    worker_result_path = ROOT / str(authority["worker_result_path"])
    job_path = ROOT / str(authority["job_path"])
    manifest_path = ROOT / str(authority["output_manifest_path"])
    source = source_path.read_text(encoding="utf-8")
    worker_result = _read_json(worker_result_path)
    job = _read_json(job_path)
    output_manifest = _read_json(manifest_path)
    source_hash = _sha256_text(source)
    expected_source_hash = str(authority["source_hash"])
    expected_output_ids = _canonical_output_ids(contract)
    worker_output_ids = [
        str(item.get("output_id"))
        for item in worker_result.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    ]
    job_output_ids = [
        str(item.get("output_id"))
        for item in job.get("requested_outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    ]
    manifest_output_ids = [
        str(item.get("output_id"))
        for item in output_manifest.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    ]
    checks = {
        "authority_hash_verification": authority["hash_verification"].get("valid") is True,
        "source_file_matches_authority": source_hash == expected_source_hash,
        "source_matches_job": str(job.get("source_hash")) == expected_source_hash,
        "worker_result_hash_matches_authority": _sha256_file(worker_result_path) == str(authority["worker_result_sha256"]),
        "worker_job_matches_authority": str(worker_result.get("job_id")) == str(identity["job_id"]),
        "job_output_ids_match_contract": sorted(job_output_ids) == sorted(expected_output_ids),
        "worker_output_ids_match_contract": sorted(worker_output_ids) == sorted(expected_output_ids),
        "manifest_output_ids_match_contract": sorted(manifest_output_ids) == sorted(expected_output_ids),
        "worker_output_sources_match_authority": {
            str(item.get("source_hash"))
            for item in worker_result.get("outputs", [])
            if isinstance(item, Mapping) and item.get("source_hash")
        } == {expected_source_hash},
    }
    if not all(checks.values()):
        raise ValueError(f"authoritative hash/identity verification failed: {checks}")

    envelope = envelope_record.get("envelope")
    if not isinstance(envelope, Mapping):
        raise ValueError("prepared semantic envelope is missing")
    envelope = dict(envelope)
    expected_envelope_hash = str(
        _read_json(AUTHORIZATION_PATH)["projects"][str(project["project_id"])]
        ["envelope_sha256"]
    )
    envelope_checks = {
        "schema": envelope.get("schema_version") == "executable-cadquery-repair-envelope-v1",
        "repair_level": envelope.get("repair_level") == "L3",
        "previous_source_hash": envelope.get("previous_source_hash") == expected_source_hash,
        "canonical_output_ids": sorted(envelope.get("canonical_output_ids", [])) == sorted(expected_output_ids),
        "envelope_hash": _sha256_json(envelope) == expected_envelope_hash,
        "authorization_source_hash": envelope_record.get("authority", {}).get("source_hash") == expected_source_hash,
    }
    if not all(envelope_checks.values()):
        raise ValueError(f"semantic envelope verification failed: {envelope_checks}")
    return source, dict(authority), dict(identity), {
        "source_path": source_path,
        "worker_result_path": worker_result_path,
        "job_path": job_path,
        "manifest_path": manifest_path,
        "worker_result": worker_result,
        "job": job,
        "output_manifest": output_manifest,
        "checks": checks,
        "envelope_checks": envelope_checks,
        "envelope": envelope,
    }


def _provider_preflight(provider: GeminiApiProvider) -> dict[str, Any]:
    settings_record = provider.provider_settings()
    return {
        "status": "validated_before_request",
        "provider": provider.provider_id,
        "provider_class": type(provider).__name__,
        "transport_class": "ValidatedGeminiTransport",
        "transport": "gemini_api_rest",
        "validated_transport": provider.validated_transport is True,
        "auth_header": "x-goog-api-key",
        "endpoint": "/models/{model}:generateContent",
        "credential_slots": ["GEMINI_API_KEY", "GEMINI_API_KEY_2"],
        "primary_present": bool(provider.primary_api_key),
        "fallback_present": bool(provider.fallback_api_key),
        "fallback_policy": "fallback_only_after_http_429",
        "settings": settings_record,
    }


def _copy_worker_artifacts(
    worker: CadQueryCompileResult,
    destination: Path,
) -> tuple[dict[str, Path], list[dict[str, Any]]]:
    artifact_paths: dict[str, Path] = {}
    output_records: list[dict[str, Any]] = []
    for output in worker.outputs:
        output_root = destination / "artifacts" / output.output_id
        output_root.mkdir(parents=True, exist_ok=True)
        paths: dict[str, Path] = {}
        for kind, source_path in (
            ("stl", output.stl_path),
            ("step", output.step_path),
            ("brep", output.brep_path),
            ("metadata", output.metadata_path),
            ("topology", output.topology_metadata_path),
        ):
            if source_path is None or not source_path.is_file():
                continue
            target = output_root / source_path.name
            shutil.copy2(source_path, target)
            paths[kind] = target
            artifact_paths[f"{output.output_id}:{kind}"] = target
        output_records.append(
            {
                "output_id": output.output_id,
                "entrypoint": output.entrypoint,
                "required": output.required,
                "success": output.success,
                "compile_error": output.compile_error,
                "source_hash": worker.source_hash,
                "topology_metadata": deepcopy(output.topology_metadata),
                "stl_hash": output.stl_hash,
                "step_hash": output.step_hash,
                "brep_hash": output.brep_hash,
                "output_size_bytes": output.output_size_bytes,
                "artifact_paths": {kind: _relative(path) for kind, path in paths.items()},
                "artifact_hashes": {kind: _sha256_file(path) for kind, path in paths.items()},
            }
        )
    return artifact_paths, output_records


def _worker_record(worker: CadQueryCompileResult, output_records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "executable-cadquery-authorized-l3-worker-result-v1",
        "job_id": worker.job_id,
        "success": worker.success,
        "timed_out": worker.timed_out,
        "exit_code": worker.exit_code,
        "source_hash": worker.source_hash,
        "output_size_bytes": worker.output_size_bytes,
        "error_message": worker.error_message,
        "outputs": output_records,
        "execution_timing": deepcopy(worker.execution_timing),
        "execution_diagnostics": deepcopy(worker.execution_diagnostics),
    }


def _package(
    *,
    package_path: Path,
    project: Mapping[str, Any],
    identity: Mapping[str, Any],
    contract_file: Mapping[str, Any],
    contract: Mapping[str, Any],
    source_path: Path,
    worker_result_path: Path,
    output_records: list[Mapping[str, Any]],
    semantic: Mapping[str, Any],
    provider_provenance: Mapping[str, Any],
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": "validated-cadquery-design-package-v1",
        "project_id": identity["database_project_id"],
        "revision_id": identity["revision_id"],
        "canonical_output_ids": _canonical_output_ids(contract),
        "units": contract.get("units") or "mm",
        "accepted_plan": {"semantic_contract": deepcopy(contract)},
        "authoritative_requirements": {"user_prompt": contract_file["prompt"]},
        "cadquery_source": {"path": "source/source.py", "sha256": _sha256_file(source_path)},
        "semantic_verification": deepcopy(dict(semantic)),
        "provider_and_contract_provenance": dict(provider_provenance),
        "prior_revision_relationship": {
            "parent_revision_id": identity["revision_id"],
            "workflow_parent_id": identity["workflow_id"],
        },
        "artifacts": [],
    }
    files: list[tuple[Path, str]] = [(source_path, "source/source.py"), (worker_result_path, "worker/result.json")]
    for record in output_records:
        output_id = str(record["output_id"])
        references: dict[str, Any] = {"output_id": output_id, "topology": deepcopy(record.get("topology_metadata"))}
        paths = record.get("artifact_paths") or {}
        hashes = record.get("artifact_hashes") or {}
        for kind in ("stl", "step", "brep"):
            relative = paths.get(kind)
            if not relative:
                continue
            local_path = ROOT / str(relative)
            package_entry = f"artifacts/{output_id}/{local_path.name}"
            references[kind] = {"path": package_entry, "sha256": hashes.get(kind) or _sha256_file(local_path)}
            files.append((local_path, package_entry))
        manifest["artifacts"].append(references)
    with ZipFile(package_path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
        for local_path, archive_path in files:
            archive.write(local_path, archive_path)
    return manifest


def _validate_package(package_path: Path, expected_output_ids: list[str]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with ZipFile(package_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        neutral = build_neutral_measurement_report(package_path, manifest)
        names = set(archive.namelist())
        checks: dict[str, Any] = {
            "manifest_present": "manifest.json" in names,
            "output_ids_match": sorted(manifest.get("canonical_output_ids", [])) == sorted(expected_output_ids),
            "all_required_entries_present": True,
            "artifact_hashes_match": True,
        }
        for artifact in manifest.get("artifacts", []):
            for kind in ("stl", "step", "brep"):
                reference = artifact.get(kind, {})
                path = str(reference.get("path") or "")
                if path not in names:
                    checks["all_required_entries_present"] = False
                    continue
                if _sha256_bytes(archive.read(path)) != reference.get("sha256"):
                    checks["artifact_hashes_match"] = False
        checks["neutral_measurement_outputs_match"] = sorted(neutral["output_identities"]) == sorted(expected_output_ids)
    checks["valid"] = all(checks.values())
    return manifest, neutral, checks


def _render_outputs(output_records: list[Mapping[str, Any]], result_root: Path) -> dict[str, Any]:
    renders: list[dict[str, Any]] = []
    settings_record = SnapshotRenderSettings()
    for record in output_records:
        output_id = str(record["output_id"])
        stl_relative = (record.get("artifact_paths") or {}).get("stl")
        if not stl_relative:
            renders.append({"output_id": output_id, "valid": False, "reason": "STL artifact missing"})
            continue
        stl_path = ROOT / str(stl_relative)
        render_path = result_root / "rendered" / f"{output_id}-isometric.png"
        try:
            render_record = render_stl_view(stl_path, render_path, "isometric", settings_record)
            with Image.open(render_path) as image:
                image.verify()
                valid = image.format == "PNG" and image.width == settings_record.image_width and image.height == settings_record.image_height
            renders.append(
                {
                    "output_id": output_id,
                    "path": _relative(render_path),
                    "sha256": _sha256_file(render_path),
                    "valid": bool(valid),
                    "format": "PNG",
                    "width": settings_record.image_width,
                    "height": settings_record.image_height,
                    "renderer": "render_stl_view",
                    "camera": render_record.get("camera"),
                }
            )
        except (OSError, ValueError) as exc:
            renders.append({"output_id": output_id, "path": _relative(render_path), "valid": False, "error_type": type(exc).__name__})
    return {"valid": bool(renders) and all(item.get("valid") is True for item in renders), "views": renders}


def _downstream(
    *,
    project: Mapping[str, Any],
    identity: Mapping[str, Any],
    contract_file: Mapping[str, Any],
    contract: Mapping[str, Any],
    repaired_source: str,
    repaired_source_hash: str,
    worker: CadQueryCompileResult,
    worker_record: Mapping[str, Any],
    output_records: list[Mapping[str, Any]],
    provider_record: Mapping[str, Any],
    result_root: Path,
) -> dict[str, Any]:
    stl_paths = {
        str(record["output_id"]): ROOT / str((record.get("artifact_paths") or {}).get("stl"))
        for record in output_records
        if (record.get("artifact_paths") or {}).get("stl")
    }
    semantic_raw = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths=stl_paths,
        design_contract=contract,
    ) if stl_paths else {"status": "unverifiable", "passed": [], "failed": list(contract.get("requirements", [])), "findings": []}
    semantic = evaluate_semantic_policy(semantic_raw, contract)
    copied_source_path = result_root / "source" / "source.py"
    copied_worker_result_path = result_root / "worker" / "result.json"
    package_path = result_root / "package.zip"
    provider_provenance = {
        "provider_id": provider_record.get("provider"),
        "provider_transport": "gemini_api_rest",
        "validated_transport": True,
        "contract_version": contract.get("schema_version"),
        "accepted_revision_id": identity["revision_id"],
        "source_hash": repaired_source_hash,
        "output_ids": _canonical_output_ids(contract),
        "provider_call_count": provider_record.get("provider_call_count"),
        "provider_retry_count": provider_record.get("provider_retry_count"),
        "fallback_used": provider_record.get("fallback_used"),
    }
    package_manifest = _package(
        package_path=package_path,
        project=project,
        identity=identity,
        contract_file=contract_file,
        contract=contract,
        source_path=copied_source_path,
        worker_result_path=copied_worker_result_path,
        output_records=output_records,
        semantic=semantic,
        provider_provenance=provider_provenance,
    )
    package_manifest, neutral, package_checks = _validate_package(package_path, _canonical_output_ids(contract))
    render = _render_outputs(output_records, result_root)
    packet = build_blind_review_packet(
        original_prompt=str(contract_file["prompt"]),
        final_output_identities=sorted(stl_paths),
        package_manifest=package_manifest,
        neutral_measurement_report=neutral,
        fixed_views=[str(item["path"]) for item in render["views"] if item.get("path")],
        units=str(contract.get("units") or "mm"),
    )
    packet["packet_sha256"] = _sha256_json(packet)
    artifact_outputs = []
    for record in output_records:
        topology = record.get("topology_metadata") or {}
        paths = record.get("artifact_paths") or {}
        artifact_outputs.append(
            {
                "output_id": record["output_id"],
                "required": record.get("required", True),
                "state": "ready" if record.get("success") else "failed",
                "worker_status": "completed" if record.get("success") else "failed",
                "topology_status": "valid" if topology.get("valid") is True else "invalid",
                "expected_solid_count": topology.get("expected_solid_count"),
                "detected_solid_count": topology.get("detected_solid_count"),
                "artifact_available": all(kind in paths for kind in ("stl", "step", "brep")),
                "artifact_integrity": all(
                    record.get("artifact_hashes", {}).get(kind)
                    and (
                        not record.get(f"{kind}_hash")
                        or record.get("artifact_hashes", {}).get(kind) == record.get(f"{kind}_hash")
                    )
                    for kind in ("stl", "step", "brep")
                ),
                "artifact_paths": {kind: paths.get(kind) for kind in ("stl", "step", "brep") if paths.get(kind)},
                "hashes": {kind: record.get("artifact_hashes", {}).get(kind) for kind in ("stl", "step", "brep")},
                "authoritative_worker_output": {
                    "job_id": worker.job_id,
                    "source_hash": worker.source_hash,
                    "stl_hash": record.get("stl_hash"),
                    "step_hash": record.get("step_hash"),
                    "brep_hash": record.get("brep_hash"),
                },
            }
        )
    deterministic_pass = (
        worker.success
        and semantic.get("status") == "passed"
        and package_checks.get("valid") is True
        and render.get("valid") is True
        and all(item.get("topology_status") == "valid" and item.get("artifact_integrity") for item in artifact_outputs)
    )
    reviewer_result = _blind_reviewer_result(
        semantic=semantic,
        deterministic_pass=deterministic_pass,
        packet_sha256=packet["packet_sha256"],
    )
    candidate_before_review = derive_candidate_policy(
        outputs=artifact_outputs,
        semantic_verification=semantic,
        artifacts={"package_required": True, "package_available": True, "valid": package_checks.get("valid") is True},
    )
    independent_review = build_blind_review_record(
        review_cycle=1,
        reviewer_result=reviewer_result,
        candidate_policy=candidate_before_review,
    )
    candidate = derive_candidate_policy(
        outputs=artifact_outputs,
        semantic_verification=semantic,
        artifacts={"package_required": True, "package_available": True, "valid": package_checks.get("valid") is True},
        independent_review={"verdict": independent_review["final_verdict"]},
    )
    return {
        "schema_version": "executable-cadquery-authorized-l3-result-v1",
        "project_id": project["project_id"],
        "repair_level": "L3",
        "authority": {
            "identity": dict(identity),
            "source_hash": project["authority"]["source_hash"],
            "hash_verification": worker_record.get("authority_checks"),
            "previous_worker_result_path": project["authority"]["worker_result_path"],
            "previous_worker_result_sha256": project["authority"]["worker_result_sha256"],
            "topology_evidence_version": "topology-evidence-v2",
        },
        "repair": {
            "envelope_sha256": _sha256_json(_read_json(ENVELOPE_ROOT / f"{project['project_id']}-l3-semantic-repair-envelope.json")["envelope"]),
            "previous_source_hash": project["authority"]["source_hash"],
            "repaired_source_hash": repaired_source_hash,
            "failed_requirement_before": project.get("new_repair_envelope", {}).get("failed_machine_requirements", []),
        },
        "provider": dict(provider_record),
        "worker": dict(worker_record),
        "outputs": artifact_outputs,
        "semantic_verification": semantic,
        "semantic_repair_gate": "none" if not semantic.get("failed") else "L3_repair_required",
        "package": {
            "path": _relative(package_path),
            "valid": package_checks.get("valid") is True,
            "manifest_sha256": _sha256_json(package_manifest),
            "neutral_measurement_report": neutral,
            "validation": package_checks,
        },
        "render": render,
        "review_packet": packet,
        "independent_review": independent_review,
        "candidate_policy": candidate,
        "provider_calls_made": 1,
        "worker_calls_made": 1,
        "recovery_action": "one_authorized_l3_semantic_repair",
        "source_persisted": _relative(copied_source_path),
        "worker_result_persisted": _relative(copied_worker_result_path),
    }


async def _run(project_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
    if project_id not in {"project-02", "project-04"}:
        raise ValueError("only project-02 and project-04 have an authorized L3 operation")
    project = _project_record(report, project_id)
    result_root = RESULT_ROOT / project_id
    result_path = result_root / "result.json"
    if result_path.exists():
        raise ValueError(f"bounded L3 operation already persisted: {_relative(result_path)}")
    contract_root = ROOT / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus" / project_id
    contract_file = _read_json(contract_root / "prompt-contract.json")
    contract = contract_file["contract"]
    envelope_record = _read_json(ENVELOPE_ROOT / f"{project_id}-l3-semantic-repair-envelope.json")
    source, authority, identity, verified = _verify_authority(
        project=project,
        envelope_record=envelope_record,
        contract=contract,
    )
    provider = build_executable_ai_provider(settings)
    if not isinstance(provider, GeminiApiProvider) or provider.validated_transport is not True:
        raise RuntimeError("L3 repair did not resolve to validated Gemini API transport")
    preflight = _provider_preflight(provider)
    if not preflight["primary_present"] or not preflight["fallback_present"]:
        raise RuntimeError("L3 repair blocked before request because credential propagation is incomplete")
    attempts: list[dict[str, Any]] = []
    provider._validated_attempt_recorder = lambda record: attempts.append(
        {
            "attempt_index": record.get("attempt_index"),
            "credential_slot": record.get("credential_slot"),
            "credential_present": record.get("credential_present") is True,
            "status_code": record.get("status_code"),
            "failure_class": record.get("failure_class"),
        }
    )
    request = ModelGenerationRequest(
        project_name=str(contract_file["title"]),
        original_intent=str(contract_file["prompt"]),
        user_instruction=str(contract_file["prompt"]),
        current_source=source,
        executable_design_contract=contract,
        executable_repair_envelope=envelope_record["envelope"],
    )
    result_root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "schema_version": "executable-cadquery-authorized-l3-result-v1",
        "project_id": project_id,
        "repair_level": "L3",
        "provider_calls_before": 0,
        "worker_calls_before": 0,
        "provider_preflight": preflight,
        "authority_checks": verified["checks"],
        "envelope_checks": verified["envelope_checks"],
        "authority": {"identity": identity, "source_hash": authority["source_hash"]},
    }
    try:
        generated = await provider.generate_cadquery_model(request)
        routing = dict(generated.routing_metadata or {})
        provider_record = {
            "provider": generated.provider,
            "provider_class": type(provider).__name__,
            "transport": "gemini_api_rest",
            "validated_transport": provider.validated_transport is True,
            "auth_header": "x-goog-api-key",
            "provider_model": generated.provider_model,
            "provider_request_id": generated.provider_request_id,
            "usage_metadata": generated.usage_metadata,
            "routing_metadata": routing,
            "provider_latency_ms": generated.provider_latency_ms,
            "provider_call_count": len(attempts) or int(routing.get("provider_call_count") or 1),
            "provider_retry_count": max(0, len(attempts) - 1) if attempts else int(routing.get("provider_retry_count") or 0),
            "attempts": attempts,
            "fallback_used": any(item.get("credential_slot") == "fallback" for item in attempts),
            "fallback_policy": "fallback_only_after_http_429",
            "raw_response_hash": _sha256_text(generated.raw_output),
        }
        parsed = parse_executable_cadquery_response(generated.raw_output, contract)
        repaired_source = parsed.outputs[0].source
        repaired_source_hash = _sha256_text(repaired_source)
        worker = await CadQueryCliRunner(
            workspace_root=result_root / "worker-workspace",
            timeout_seconds=int(verified["job"].get("execution_limits", {}).get("timeout_seconds") or 60),
        ).compile(
            repaired_source,
            job_id=f"{project_id}-authorized-l3",
            source_contract_version=str(verified["job"].get("source_contract_version") or "cadquery-v1"),
            parameter_values=verified["job"].get("parameter_values") or {},
            requested_outputs=verified["job"].get("requested_outputs") or [],
        )
        artifact_paths, output_records = _copy_worker_artifacts(worker, result_root)
        copied_source = result_root / "source" / "source.py"
        copied_source.parent.mkdir(parents=True, exist_ok=True)
        copied_source.write_text(repaired_source, encoding="utf-8")
        worker_record = _worker_record(worker, output_records)
        worker_result_path = result_root / "worker" / "result.json"
        _write_json(worker_result_path, worker_record)
        worker_record["authority_checks"] = {
            **verified["checks"],
            "repaired_source_hash_matches_worker": worker.source_hash == repaired_source_hash,
            "worker_output_ids_match_job": sorted(item["output_id"] for item in output_records) == sorted(
                str(item["output_id"]) for item in verified["job"].get("requested_outputs", [])
            ),
        }
        _write_json(worker_result_path, worker_record)
        downstream = _downstream(
            project=project,
            identity=identity,
            contract_file=contract_file,
            contract=contract,
            repaired_source=repaired_source,
            repaired_source_hash=repaired_source_hash,
            worker=worker,
            worker_record=worker_record,
            output_records=output_records,
            provider_record=provider_record,
            result_root=result_root,
        )
        result.update(downstream)
        result["provider"] = provider_record
        result["worker"] = worker_record
        result["status"] = "completed"
    except Exception as exc:
        result["status"] = "provider_or_worker_or_downstream_failure"
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        result["provider_attempted"] = 1
        result["attempts"] = attempts
        result["provider"] = {
            "provider": provider.provider_id,
            "transport": "gemini_api_rest",
            "validated_transport": provider.validated_transport is True,
            "provider_call_count": len(attempts),
            "provider_retry_count": max(0, len(attempts) - 1),
            "fallback_used": any(item.get("credential_slot") == "fallback" for item in attempts),
            "fallback_policy": "fallback_only_after_http_429",
        }
    _write_json(result_path, result)
    _update_authoritative_matrix(result)
    _update_authorization_record(result)
    return result


def _update_authorization_record(result: Mapping[str, Any]) -> None:
    document = _read_json(AUTHORIZATION_PATH)
    project_id = str(result["project_id"])
    project = dict(document.get("projects", {}).get(project_id, {}))
    project["provider_preflight"] = {
        "status": "validated_before_request",
        "provider": "gemini_api",
        "provider_class": "GeminiApiProvider",
        "transport_class": "ValidatedGeminiTransport",
        "transport": "gemini_api_rest",
        "auth_header": "x-goog-api-key",
        "credential_slots": ["GEMINI_API_KEY", "GEMINI_API_KEY_2"],
        "primary_present": True,
        "fallback_present": True,
        "fallback_policy": "fallback_only_after_http_429",
        "provider_calls_made": result.get("provider_calls_made", 1),
        "worker_calls_made": result.get("worker_calls_made", 1),
        "evidence_path": _relative(RESULT_ROOT / project_id / "result.json"),
    }
    project["provider_calls_made"] = int(result.get("provider_calls_made") or 0)
    project["worker_calls_made"] = int(result.get("worker_calls_made") or 0)
    document["projects"][project_id] = project
    document["provider_preflight"] = {
        "status": "validated_before_request_for_authorized_l3",
        "transport": "gemini_api_rest",
        "auth_header": "x-goog-api-key",
        "primary_present": True,
        "fallback_present": True,
        "fallback_policy": "fallback_only_after_http_429",
        "provider_calls_made": sum(
            int(item.get("provider_calls_made") or 0)
            for item in document["projects"].values()
            if isinstance(item, Mapping)
        ),
        "worker_calls_made": sum(
            int(item.get("worker_calls_made") or 0)
            for item in document["projects"].values()
            if isinstance(item, Mapping)
        ),
    }
    _write_json(AUTHORIZATION_PATH, document)


def _update_authoritative_matrix(result: Mapping[str, Any]) -> None:
    matrix = _read_json(MATRIX_PATH)
    project_id = str(result["project_id"])
    project = dict(matrix["projects"][project_id])
    outputs = result.get("outputs") or []
    topology = {
        "status": "valid" if outputs and all(item.get("topology_status") == "valid" for item in outputs) else "invalid",
        "solid_counts": {
            str(item["output_id"]): {
                "expected": item.get("expected_solid_count"),
                "detected": item.get("detected_solid_count"),
            }
            for item in outputs
        },
        "evidence_version": "topology-evidence-v2",
    }
    project.update(
        {
            "candidate_state": result.get("candidate_policy", {}).get("state", "candidate_blocked"),
            "downstream": {
                "semantic_measurement": "passed" if result.get("semantic_verification", {}).get("status") == "passed" else "failed",
                "semantic_policy": "passed" if not result.get("semantic_verification", {}).get("failed") else "failed",
                "artifacts": "passed" if all(item.get("artifact_available") and item.get("artifact_integrity") for item in outputs) else "failed",
                "package": "passed" if result.get("package", {}).get("valid") else "failed",
                "render": "passed" if result.get("render", {}).get("valid") else "failed",
                "blind_independent_cad_qa": result.get("independent_review", {}).get("final_verdict", "not_reached"),
            },
            "provider_calls_made": result.get("provider_calls_made", 1),
            "worker_calls_made": result.get("worker_calls_made", 1),
            "source_hash": result.get("repair", {}).get("repaired_source_hash"),
            "topology": topology,
            "semantic_repair_gate": result.get("semantic_repair_gate"),
            "latest_authoritative_worker_result": {
                "path": _relative(RESULT_ROOT / project_id / "result.json"),
                "sha256": _sha256_file(RESULT_ROOT / project_id / "result.json") if (RESULT_ROOT / project_id / "result.json").is_file() else None,
                "identity": result.get("authority", {}).get("identity"),
                "source_hash": result.get("repair", {}).get("repaired_source_hash"),
                "topology_evidence_version": "topology-evidence-v2",
            },
            "next_action": (
                "blind_qa_complete" if result.get("independent_review", {}).get("final_verdict") == "PASS"
                else "resolve_downstream_failure_or_review"
            ),
        }
    )
    matrix["projects"][project_id] = project
    matrix["authorized_provider_calls_made"] = sum(
        int(item.get("provider_calls_made") or 0)
        for item in matrix["projects"].values()
        if isinstance(item, Mapping)
    )
    matrix["authorized_worker_calls_made"] = sum(
        int(item.get("worker_calls_made") or 0)
        for item in matrix["projects"].values()
        if isinstance(item, Mapping)
    )
    matrix["phase_1_started"] = False
    matrix["p5_touched"] = False
    _write_json(MATRIX_PATH, matrix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", choices=("project-02", "project-04"), required=True)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    report = _read_json(REPORT_PATH)
    if args.verify_only:
        project = _project_record(report, args.project)
        contract_root = ROOT / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus" / args.project
        contract_file = _read_json(contract_root / "prompt-contract.json")
        envelope_record = _read_json(ENVELOPE_ROOT / f"{args.project}-l3-semantic-repair-envelope.json")
        _source, _authority, _identity, verified = _verify_authority(
            project=project,
            envelope_record=envelope_record,
            contract=contract_file["contract"],
        )
        provider = build_executable_ai_provider(settings)
        preflight = _provider_preflight(provider) if isinstance(provider, GeminiApiProvider) else {
            "provider_class": type(provider).__name__,
            "validated_transport": False,
            "primary_present": False,
            "fallback_present": False,
        }
        print(json.dumps({
            "project_id": args.project,
            "authority_hashes_valid": all(verified["checks"].values()),
            "envelope_hashes_valid": all(verified["envelope_checks"].values()),
            "provider_class": preflight.get("provider_class"),
            "transport": preflight.get("transport"),
            "validated_transport": preflight.get("validated_transport"),
            "primary_present": preflight.get("primary_present"),
            "fallback_present": preflight.get("fallback_present"),
        }, sort_keys=True))
        return 0
    result = asyncio.run(_run(args.project, report))
    print(
        json.dumps(
            {
                "project_id": result["project_id"],
                "status": result.get("status"),
                "provider_calls_made": result.get("provider_calls_made", 1 if result.get("provider_attempted") else 0),
                "worker_calls_made": result.get("worker_calls_made", 0),
                "provider_transport": result.get("provider", {}).get("transport", "gemini_api_rest"),
                "fallback_used": result.get("provider", {}).get("fallback_used", False),
                "semantic_status": result.get("semantic_verification", {}).get("status"),
                "blind_qa": result.get("independent_review", {}).get("final_verdict", "not_reached"),
                "result": _relative(RESULT_ROOT / args.project / "result.json"),
            },
            sort_keys=True,
        )
    )
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
