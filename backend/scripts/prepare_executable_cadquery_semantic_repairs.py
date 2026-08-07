"""Persist exact L3 semantic repair envelopes for the current frozen P2/P4 state.

This command is preparation-only.  It never invokes a provider or worker.  It
uses the already hash-verified authoritative source/result chain and the
fresh offline semantic report, then delegates envelope shape to the generic
repair-envelope builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.executable_cadquery.repair import (
    build_executable_cadquery_repair_envelope,
)


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs/executable-cadquery-topology-replay-v2.json"
DOWNSTREAM_ROOT = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "current-authoritative-downstream"
)
OUTPUT_ROOT = ROOT / (
    "data/debug-sessions/executable-cadquery/recovery-wave-01/"
    "semantic-repair-envelopes"
)


def main() -> int:
    args = _parse_args()
    report = _read_json(args.report)
    projects = {
        str(item["project_id"]): item
        for item in report.get("projects", [])
        if isinstance(item, Mapping) and item.get("project_id")
    }
    records: dict[str, dict[str, Any]] = {}
    for project_id in ("project-02", "project-04"):
        record = _prepare_project(projects[project_id], args.output_root)
        records[project_id] = record
        _write_json(
            args.output_root / f"{project_id}-l3-semantic-repair-envelope.json",
            record,
        )
    _write_json(
        args.output_root / "authorization-summary.json",
        {
            "schema_version": "executable-cadquery-semantic-repair-authorization-v1",
            "provider_calls_made": 0,
            "worker_calls_made": 0,
            "projects": {
                project_id: {
                    "repair_level": record["envelope"]["repair_level"],
                    "failed_machine_requirements": record["envelope"]["failed_machine_requirements"],
                    "passed_machine_requirements": record["envelope"]["passed_machine_requirements"],
                    "source_hash": record["envelope"]["previous_source_hash"],
                    "envelope_sha256": _sha256_json(record["envelope"]),
                }
                for project_id, record in records.items()
            },
        },
    )
    print(
        json.dumps(
            {
                "output_root": str(args.output_root.relative_to(ROOT)),
                "provider_calls_made": 0,
                "projects": {
                    project_id: record["envelope"]["failed_machine_requirements"]
                    for project_id, record in records.items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


def _prepare_project(project: Mapping[str, Any], output_root: Path) -> dict[str, Any]:
    project_id = str(project["project_id"])
    authority = project["authority"]
    identity = authority["identity"]
    project_root = ROOT / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus" / project_id
    contract_file = _read_json(project_root / "prompt-contract.json")
    contract = contract_file["contract"]
    source_path = ROOT / authority["source_path"]
    worker_result_path = ROOT / authority["worker_result_path"]
    worker_result = _read_json(worker_result_path)
    downstream = _read_json(DOWNSTREAM_ROOT / f"{project_id}-downstream.json")
    if downstream["authority"]["hash_verification"]["valid"] is not True:
        raise ValueError(f"{project_id} authority is not hash-verified")
    semantic = downstream["semantic_verification"]
    failed = list(semantic.get("failed") or [])
    if not failed:
        raise ValueError(f"{project_id} has no measured semantic failure to repair")
    if downstream["semantic_repair_gate"] != "L3_repair_required":
        raise ValueError(f"{project_id} is not at the L3 semantic gate")
    worker_outputs = {
        str(item["output_id"]): item
        for item in worker_result.get("outputs", [])
        if isinstance(item, Mapping) and item.get("output_id")
    }
    topology = {
        "valid": True,
        "outputs": {
            output_id: dict(worker_outputs[output_id].get("topology_metadata") or {})
            for output_id in sorted(worker_outputs)
        },
    }
    historical = project.get("new_repair_envelope", {})
    repair_history = historical.get("repair_history", []) if isinstance(historical, Mapping) else []
    envelope = build_executable_cadquery_repair_envelope(
        repair_level="L3",
        generation_session_id=f"phase0-semantic-repair-{project_id}",
        logical_operation_id=f"{identity['workflow_id']}:semantic-repair-l3",
        parent_operation_id=str(identity["revision_id"]),
        repair_ordinal=1,
        previous_source=source_path.read_text(encoding="utf-8"),
        previous_source_hash=str(authority["source_hash"]),
        previous_result_hash=str(downstream["authority"]["worker_result_sha256"]),
        design_contract=contract,
        previous_normalized_error="measured semantic failure: " + ", ".join(str(item) for item in failed),
        provider_attempt={
            "status": "not_started",
            "transport_proof_path": "docs/executable-cadquery-p3-transport-proof.json",
        },
        worker_result=worker_result,
        topology_result=topology,
        semantic_result=semantic,
        protected_facts=contract.get("protected_facts", []),
        repair_history=repair_history,
        requested_delta=(
            "Correct the measured machine-required semantic requirement(s): "
            + ", ".join(str(item) for item in failed)
            + "; preserve every passed requirement, protected fact, canonical output identity, and complete-source contract."
        ),
    )
    return {
        "schema_version": "executable-cadquery-semantic-repair-preparation-v1",
        "project_id": project_id,
        "authority": {
            "identity": identity,
            "source_hash": authority["source_hash"],
            "worker_result_path": authority["worker_result_path"],
            "worker_result_sha256": downstream["authority"]["worker_result_sha256"],
        },
        "semantic_gate": {
            "failed_machine_requirements": envelope["failed_machine_requirements"],
            "passed_machine_requirements": envelope["passed_machine_requirements"],
            "facts": envelope["semantic_repair_facts"],
            "status": semantic.get("status"),
        },
        "provider_calls_made": 0,
        "worker_calls_made": 0,
        "envelope": envelope,
    }


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"expected JSON object: {path}")
    return dict(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
