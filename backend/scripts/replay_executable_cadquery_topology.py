"""Replay frozen executable-CadQuery topology evidence without provider calls.

The freeze index and its source-wave result identify the authority chain.  A
worker replay is allowed only after that chain is verified; the replay is an
offline measurement refresh and never becomes a replacement for the frozen
worker result.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.topology_evidence import compare_topology_evidence
from app.services.executable_cadquery.repair import (
    build_executable_cadquery_repair_envelope,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPOSITORY_ROOT / "data/debug-sessions/executable-cadquery"
FROZEN_ROOT = DATA_ROOT / "recovery-wave-01/frozen-corpus"
FREEZE_INDEX_PATH = DATA_ROOT / "recovery-wave-01/freeze-index.json"
AUDIT_PATH = REPOSITORY_ROOT / "docs/executable-cadquery-offline-recovery-audit.json"
AUTHORIZED_L2_RESULT_PATH = DATA_ROOT / (
    "topology-evidence-v2/p3-l2-repair.json"
)
PROJECT_IDS = ("project-02", "project-03", "project-04")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


def _source_hash_from_sha_manifest(source_path: Path) -> str | None:
    manifest_path = FROZEN_ROOT / "sha256sums.txt"
    target = _relative(source_path)
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip() == target:
            return parts[0]
    return None


def _worker_candidates(worker_dir: Path, suffix: str) -> list[Path]:
    candidates = set(worker_dir.glob(f"*{suffix}"))
    if suffix == "-job.json":
        candidates.add(worker_dir / "job.json")
    if suffix == "-result.json":
        candidates.add(worker_dir / "result.json")
    return sorted(path for path in candidates if path.is_file())


def _find_worker_artifact(
    worker_dir: Path,
    *,
    job_id: str,
    suffix: str,
    label: str,
) -> Path:
    candidates = []
    for path in _worker_candidates(worker_dir, suffix):
        payload = _read_json(path)
        if payload.get("job_id") == job_id:
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError(
            f"expected exactly one authoritative {label} for job {job_id}; "
            f"found {len(candidates)}"
        )
    return candidates[0]


def _output_ids_from_job(job: Mapping[str, Any]) -> list[str]:
    return sorted(
        str(item["output_id"])
        for item in job.get("requested_outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    )


def _output_ids_from_result(result: Mapping[str, Any]) -> list[str]:
    return sorted(str(item) for item in result.get("requested_output_ids", []) if item)


def validate_authoritative_chain(
    resolved: Mapping[str, Any],
    *,
    result_path: Path | None = None,
) -> dict[str, Any]:
    """Validate identity and content hashes for one selected frozen chain."""

    source_path = Path(str(resolved["source_path"]))
    job_path = Path(str(resolved["job_path"]))
    selected_result_path = result_path or Path(str(resolved["worker_result_path"]))
    output_manifest_path = Path(str(resolved["output_manifest_path"]))
    source = _sha256(source_path)
    job = _read_json(job_path)
    result = _read_json(selected_result_path)
    output_manifest = _read_json(output_manifest_path)
    identity = resolved["identity"]

    if result.get("job_id") != identity["job_id"]:
        raise ValueError(
            f"superseded worker result: {selected_result_path} has job "
            f"{result.get('job_id')!r}, expected {identity['job_id']!r}"
        )
    if job.get("job_id") != identity["job_id"]:
        raise ValueError(
            f"authoritative job identity mismatch: {job.get('job_id')!r}"
        )
    if output_manifest.get("project_id") != identity["database_project_id"]:
        raise ValueError("output manifest project identity does not match authority")
    if output_manifest.get("revision_id") != identity["revision_id"]:
        raise ValueError("output manifest revision identity does not match authority")
    if identity["revision_id"] != identity["job_id"]:
        raise ValueError("authoritative revision and worker job identities diverge")

    output_hashes = sorted(
        str(output.get("source_hash"))
        for output in result.get("outputs", [])
        if isinstance(output, Mapping) and output.get("source_hash")
    )
    diagnostic_hash = (result.get("diagnostics") or {}).get("source_hash")
    checks = {
        "source_file_sha256": source,
        "source_sha256_manifest": _source_hash_from_sha_manifest(source_path),
        "job_source_hash": job.get("source_hash"),
        "worker_diagnostic_source_hash": diagnostic_hash,
        "worker_output_source_hashes": output_hashes,
        "source_matches_sha256_manifest": source == _source_hash_from_sha_manifest(source_path),
        "source_matches_job": source == job.get("source_hash"),
        "source_matches_worker_diagnostics": source == diagnostic_hash,
        "source_matches_worker_outputs": bool(output_hashes) and all(
            item == source for item in output_hashes
        ),
        "job_output_ids_match_result": _output_ids_from_job(job)
        == _output_ids_from_result(result),
    }
    checks["valid"] = all(
        bool(checks[key])
        for key in (
            "source_matches_sha256_manifest",
            "source_matches_job",
            "source_matches_worker_diagnostics",
            "source_matches_worker_outputs",
            "job_output_ids_match_result",
        )
    )
    if not checks["valid"]:
        raise ValueError(
            f"authoritative hash verification failed for {resolved['project_id']}: {checks}"
        )
    return checks


def resolve_authoritative_project(project_id: str) -> dict[str, Any]:
    """Resolve the latest frozen project/workflow/revision/source/job/result chain."""

    if project_id not in PROJECT_IDS:
        raise ValueError(f"unsupported frozen topology project: {project_id}")
    freeze_index = _read_json(FREEZE_INDEX_PATH)
    project_entry = next(
        (
            item
            for item in freeze_index.get("projects", [])
            if isinstance(item, Mapping) and item.get("project_id") == project_id
        ),
        None,
    )
    if not isinstance(project_entry, Mapping):
        raise ValueError(f"project is not in freeze index: {project_id}")

    source_path = FROZEN_ROOT / str(project_entry["latest_source"])[len("frozen-corpus/") :]
    revision_dir = FROZEN_ROOT / str(project_entry["latest_revision"])[len("frozen-corpus/") :]
    worker_dir = FROZEN_ROOT / str(project_entry["worker_evidence"])[len("frozen-corpus/") :]
    source_wave_path = DATA_ROOT / str(project_entry["source_wave"])
    output_manifest_path = revision_dir / "output-manifest.json"
    source_wave = _read_json(source_wave_path)
    revision_id = str(source_wave.get("revision_id") or "")
    job_path = _find_worker_artifact(
        worker_dir,
        job_id=revision_id,
        suffix="-job.json",
        label="worker job",
    )
    result_path = _find_worker_artifact(
        worker_dir,
        job_id=revision_id,
        suffix="-result.json",
        label="worker result",
    )
    job = _read_json(job_path)
    result = _read_json(result_path)
    output_manifest = _read_json(output_manifest_path)
    identity = {
        "project_id": project_id,
        "database_project_id": str(source_wave.get("database_project_id") or ""),
        "workflow_id": str(source_wave.get("workflow_id") or ""),
        "revision_id": revision_id,
        "job_id": str(job.get("job_id") or ""),
    }
    resolved = {
        "project_id": project_id,
        "identity": identity,
        "source_wave_path": str(source_wave_path),
        "source_path": str(source_path),
        "output_manifest_path": str(output_manifest_path),
        "job_path": str(job_path),
        "worker_result_path": str(result_path),
        "source_hash": _sha256(source_path),
        "job_id": job.get("job_id"),
        "result_hash": _sha256(result_path),
    }
    resolved["hash_verification"] = validate_authoritative_chain(resolved)
    resolved["selected_worker_result"] = result
    resolved["selected_job"] = job
    resolved["selected_output_manifest"] = output_manifest
    return resolved


def _historical_attempts(project_id: str, audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    if project_id == "project-03":
        value = audit.get("project_03_offline_recovery", {}).get("attempts", [])
    else:
        value = audit.get("l2_topology_audit", {}).get("projects", {}).get(project_id, {}).get("attempts", [])
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _historical_topology(attempt: Mapping[str, Any], output_ids: list[str]) -> dict[str, dict[str, Any]]:
    topology = attempt.get("topology")
    if isinstance(topology, Mapping) and any(output_id in topology for output_id in output_ids):
        return {
            str(output_id): dict(topology[output_id])
            for output_id in output_ids
            if isinstance(topology.get(output_id), Mapping)
        }
    if isinstance(topology, Mapping) and output_ids:
        return {output_ids[0]: dict(topology)}
    return {}


def _stale_reasons(
    attempt: Mapping[str, Any],
    *,
    authoritative_source_hash: str,
    authoritative_identity: Mapping[str, str],
) -> list[str]:
    reasons = [
        "historical replay has no persisted project/workflow/revision/job identity",
        "historical replay is not the selected latest authoritative worker result",
    ]
    if attempt.get("source_hash") != authoritative_source_hash:
        reasons.append(
            "source hash differs from authoritative frozen source "
            f"({attempt.get('source_hash')} != {authoritative_source_hash})"
        )
    else:
        reasons.append("source hash is not sufficient without a matching persisted identity chain")
    if attempt.get("source_hash"):
        reasons.append(
            "the historical source/result artifact is superseded by revision/job "
            f"{authoritative_identity['revision_id']}"
        )
    return reasons


def _prior_replay_staleness(
    project_id: str,
    resolved: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    identity = resolved["identity"]
    source_hash = str(resolved["source_hash"])
    entries: list[dict[str, Any]] = []
    for attempt in _historical_attempts(project_id, audit):
        entries.append(
            {
                "kind": "historical_repair_replay",
                "ordinal": attempt.get("ordinal"),
                "source_hash": attempt.get("source_hash"),
                "stale": True,
                "superseded_by": dict(identity),
                "reasons": _stale_reasons(
                    attempt,
                    authoritative_source_hash=source_hash,
                    authoritative_identity=identity,
                ),
            }
        )

    worker_dir = Path(str(resolved["worker_result_path"])).parent
    selected_path = Path(str(resolved["worker_result_path"]))
    for path in _worker_candidates(worker_dir, "-result.json"):
        if path == selected_path:
            continue
        result = _read_json(path)
        entries.append(
            {
                "kind": "superseded_persisted_worker_result",
                "path": _relative(path),
                "job_id": result.get("job_id"),
                "source_hashes": sorted(
                    str(output.get("source_hash"))
                    for output in result.get("outputs", [])
                    if isinstance(output, Mapping) and output.get("source_hash")
                ),
                "stale": True,
                "superseded_by": dict(identity),
                "reasons": [
                    "worker result job identity does not match the latest frozen revision/job",
                    "worker result source hash does not match the latest frozen source",
                    "worker result is retained only as historical evidence",
                ],
            }
        )
    return entries


def _latest_historical_attempt(project_id: str, audit: Mapping[str, Any]) -> dict[str, Any]:
    attempts = _historical_attempts(project_id, audit)
    return attempts[-1] if attempts else {}


def _historical_repair_envelope(
    project_id: str,
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    if project_id == "project-03":
        source = audit.get("project_03_offline_recovery", {})
        return {
            "schema_version": "historical-repair-envelope-reconstructed-v1",
            "repair_level": "L1_to_topology_then_L2_eligible",
            "source": _relative(AUDIT_PATH),
            "envelope_persisted": False,
            "attempts": _historical_attempts(project_id, audit),
            "latest_worker_evidence": source.get("latest_worker_evidence"),
            "persistence_gap": "historical L1/topology envelope was recorded in the audit, not as a durable provider envelope",
        }
    audit_project = audit.get("l2_topology_audit", {}).get("projects", {}).get(project_id, {})
    return {
        "schema_version": audit.get("l2_topology_audit", {}).get(
            "envelope_schema", "historical-repair-envelope-reconstructed-v1"
        ),
        "repair_level": "L2",
        "source": _relative(AUDIT_PATH),
        "envelope_persisted": bool(
            audit.get("l2_topology_audit", {}).get(
                "historical_full_envelope_persisted_in_compact_project_records",
                False,
            )
        ),
        "attempts": _historical_attempts(project_id, audit),
        "current_builder_proves_fields": audit.get("l2_topology_audit", {}).get(
            "current_builder_proves_fields", []
        ),
        "terminal_reason": audit_project.get("terminal_reason"),
        "provider_convergence": audit_project.get("provider_convergence"),
    }


def _repair_history_for_envelope(
    project_id: str,
    audit: Mapping[str, Any],
) -> list[dict[str, Any]]:
    repair_level = "L1" if project_id == "project-03" else "L2"
    history = []
    for attempt in _historical_attempts(project_id, audit):
        history.append(
            {
                "repair_level": repair_level,
                "attempt_number": attempt.get("ordinal"),
                "source_hash": attempt.get("source_hash"),
                "result_hash": None,
                "topology_result": attempt.get("topology"),
                "normalized_failure": attempt.get("failure")
                or attempt.get("normalized_failure_in_project_record"),
            }
        )
    return history


def _build_new_repair_envelope(
    project_id: str,
    resolved: Mapping[str, Any],
    audit: Mapping[str, Any],
    current: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    contract = _read_json(
        FROZEN_ROOT / project_id / "prompt-contract.json"
    ).get("contract", {})
    worker_result = dict(resolved["selected_worker_result"])
    latest_historical = _latest_historical_attempt(project_id, audit)
    return build_executable_cadquery_repair_envelope(
        repair_level="L2",
        generation_session_id=f"topology-evidence-v2-{project_id}",
        logical_operation_id=f"{resolved['identity']['workflow_id']}:topology-evidence-v2",
        parent_operation_id=resolved["identity"]["revision_id"],
        repair_ordinal=1,
        previous_source=Path(str(resolved["source_path"])).read_text(encoding="utf-8"),
        previous_source_hash=str(resolved["source_hash"]),
        previous_result_hash=str(resolved["result_hash"]),
        design_contract=contract,
        previous_normalized_error=latest_historical.get("failure")
        or latest_historical.get("normalized_failure_in_project_record"),
        worker_result=worker_result,
        topology_result={"outputs": dict(current)},
        protected_facts=contract.get("protected_facts", []),
        repair_history=_repair_history_for_envelope(project_id, audit),
        requested_delta="Repair the authoritative topology failure while preserving the frozen design contract.",
    )


def _actionable_topology(outputs: Mapping[str, Mapping[str, Any]]) -> bool:
    return any(
        item.get("valid") is False
        and (
            item.get("outcome") not in {None, "valid"}
            or item.get("overall_shape_valid") is False
            or any(
                pair.get("intersects") is True or pair.get("touches") is True
                for pair in item.get("solid_pairs", [])
                if isinstance(pair, Mapping)
            )
        )
        for item in outputs.values()
        if isinstance(item, Mapping)
    )


def build_repair_gate_decision(
    project_id: str,
    *,
    materially_new: bool,
    actionable: bool,
    authoritative: bool,
) -> dict[str, Any]:
    """Apply the user-specified post-evidence L2 gate without provider effects."""

    eligible = bool(materially_new and actionable and authoritative)
    if project_id == "project-03":
        return {
            "project_id": project_id,
            "action": "one_l2_repair" if eligible else "no_provider_call",
            "authorized": eligible,
            "priority": 1 if eligible else None,
        }
    if project_id in {"project-02", "project-04"}:
        return {
            "project_id": project_id,
            "action": "one_l2_repair" if eligible else "no_provider_call",
            "authorized": eligible,
            "priority": 2 if eligible else None,
        }
    return {
        "project_id": project_id,
        "action": "untouched",
        "authorized": False,
        "priority": None,
    }


def _replay(
    project_id: str,
    resolved: Mapping[str, Any],
    audit: Mapping[str, Any],
) -> dict[str, Any]:
    job = dict(resolved["selected_job"])
    persisted = dict(resolved["selected_worker_result"])
    source = Path(str(resolved["source_path"])).read_text(encoding="utf-8")
    runner = CadQueryCliRunner(
        workspace_root=Path(tempfile.mkdtemp(prefix=f"topology-replay-{project_id}-")),
        timeout_seconds=int(job.get("execution_limits", {}).get("timeout_seconds") or 60),
    )
    replayed = asyncio.run(
        runner.compile(
            source,
            job_id=f"{project_id}-topology-evidence-v2",
            parameter_values=job.get("parameter_values") or {},
            requested_outputs=job.get("requested_outputs") or [],
        )
    )
    current = {
        output.output_id: output.topology_metadata
        for output in replayed.outputs
        if output.topology_metadata is not None
    }
    persisted_topology = {
        str(output.get("output_id")): output.get("topology_metadata")
        for output in persisted.get("outputs", [])
        if isinstance(output, Mapping)
        and output.get("output_id")
        and isinstance(output.get("topology_metadata"), Mapping)
    }
    output_ids = sorted(current)
    latest_historical = _latest_historical_attempt(project_id, audit)
    historical = _historical_topology(latest_historical, output_ids)
    comparisons = {
        output_id: compare_topology_evidence(
            historical.get(output_id) or persisted_topology.get(output_id),
            topology,
        )
        for output_id, topology in current.items()
    }
    new_fields = sorted(
        {
            field
            for comparison in comparisons.values()
            for field in comparison["material_new_fields"]
        }
    )
    materially_new = bool(new_fields)
    actionable = _actionable_topology(current)
    new_repair_envelope = _build_new_repair_envelope(
        project_id,
        resolved,
        audit,
        current,
    )
    gate = build_repair_gate_decision(
        project_id,
        materially_new=materially_new,
        actionable=actionable,
        authoritative=bool(resolved["hash_verification"]["valid"]),
    )
    return {
        "project_id": project_id,
        "authority": {
            "identity": resolved["identity"],
            "source_wave_path": _relative(Path(str(resolved["source_wave_path"]))),
            "source_path": _relative(Path(str(resolved["source_path"]))),
            "output_manifest_path": _relative(Path(str(resolved["output_manifest_path"]))),
            "job_path": _relative(Path(str(resolved["job_path"]))),
            "worker_result_path": _relative(Path(str(resolved["worker_result_path"]))),
            "source_hash": resolved["source_hash"],
            "worker_result_sha256": resolved["result_hash"],
            "hash_verification": resolved["hash_verification"],
        },
        "stale_replays_rejected": _prior_replay_staleness(project_id, resolved, audit),
        "authoritative_worker_result": {
            "job_id": persisted.get("job_id"),
            "success": persisted.get("success"),
            "failure_class": persisted.get("failure_class"),
            "output_ids": persisted.get("output_ids"),
            "topology_evidence_version_before_replay": sorted(
                {
                    str(topology.get("schema_version"))
                    for topology in persisted_topology.values()
                    if isinstance(topology, Mapping) and topology.get("schema_version")
                }
            ),
        },
        "topology_evidence_v2": {
            "schema_version": "topology-evidence-v2",
            "source": "authoritative persisted worker result source/job replay",
            "provider_calls": 0,
            "worker_replay_success": replayed.success,
            "worker_replay_error": replayed.error_message,
            "outputs": current,
        },
        "new_repair_envelope": new_repair_envelope,
        "historical_repair_envelope_comparison": {
            "historical_audit_path": _relative(AUDIT_PATH),
            "historical_repair_envelope": _historical_repair_envelope(project_id, audit),
            "historical_attempt_count": len(_historical_attempts(project_id, audit)),
            "historical_latest_attempt": latest_historical,
            "historical_envelope_was_persisted": project_id != "project-03" and bool(
                audit.get("l2_topology_audit", {}).get("durable_envelope_recording")
            ),
            "genuinely_new_actionable_topology_evidence": actionable and materially_new,
            "materially_richer_than_previous_gemini_envelope": materially_new,
            "new_standardized_fields": new_fields,
            "per_output": comparisons,
        },
        "repair_gate": gate,
    }


def build_report() -> dict[str, Any]:
    audit = _read_json(AUDIT_PATH)
    projects = []
    for project_id in PROJECT_IDS:
        resolved = resolve_authoritative_project(project_id)
        projects.append(_replay(project_id, resolved, audit))
    post_evidence_action: dict[str, Any] = {
        "project_id": "project-03",
        "provider_calls_before_action": 0,
        "provider_call_attempted": False,
        "status": "not_started",
        "record_path": _relative(AUTHORIZED_L2_RESULT_PATH),
    }
    if AUTHORIZED_L2_RESULT_PATH.exists():
        result = _read_json(AUTHORIZED_L2_RESULT_PATH)
        post_evidence_action.update(
            {
                "provider_call_attempted": bool(result.get("provider_call_attempted")),
                "provider_calls_made": int(
                    result.get("provider", {}).get(
                        "logical_provider_calls", result.get("provider_call_attempted", 0)
                    )
                ),
                "status": "blocked_before_response" if result.get("error") else "response_received",
                "error_type": (result.get("error") or {}).get("type"),
                "error_message": (result.get("error") or {}).get("message"),
                "worker_success": (result.get("worker_result") or {}).get("success"),
            }
        )
    return {
        "schema_version": "executable-cadquery-topology-replay-v2",
        "offline_only": True,
        "provider_calls": 0,
        "phase_1_started": False,
        "p5_touched": False,
        "post_evidence_action": post_evidence_action,
        "source_of_truth": "freeze index, source-wave result, output manifest, source, job, and persisted worker result",
        "projects": projects,
        "authoritative_state_matrix": [
            {
                "project_id": project["project_id"],
                "identity": project["authority"]["identity"],
                "source_hash": project["authority"]["source_hash"],
                "worker_result_path": project["authority"]["worker_result_path"],
                "v2_outputs": {
                    output_id: {
                        "valid": topology.get("valid"),
                        "outcome": topology.get("outcome"),
                        "detected_solid_count": topology.get("detected_solid_count"),
                        "expected_solid_count": topology.get("expected_solid_count"),
                        "overall_shape_valid": topology.get("overall_shape_valid"),
                        "solid_count": len(topology.get("solids", [])),
                        "pair_count": len(topology.get("solid_pairs", [])),
                    }
                    for output_id, topology in project["topology_evidence_v2"]["outputs"].items()
                },
                "stale_replay_count": len(project["stale_replays_rejected"]),
                "repair_gate": project["repair_gate"],
                "post_evidence_action": post_evidence_action
                if project["project_id"] == "project-03"
                else None,
            }
            for project in projects
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "docs/executable-cadquery-topology-replay-v2.json",
    )
    args = parser.parse_args()
    report = build_report()
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "provider_calls": report["provider_calls"],
                "projects": len(report["projects"]),
                "phase_1_started": report["phase_1_started"],
                "p5_touched": report["p5_touched"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
