"""Reconcile survey evidence from a preserved runtime database.

This is an offline evidence repair tool.  It never constructs a provider or
worker and never changes the persisted workflow outcomes.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.revision import Revision
from app.models.validated_cadquery_workflow import ValidatedCadQueryWorkflow
from app.services.external_benchmarks.survey import load_frozen_development_projects


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--runtime-data-dir", type=Path, required=True)
    parser.add_argument(
        "--v11-manifest",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1.1/manifest.json",
    )
    parser.add_argument(
        "--v1-manifest",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1/manifest.json",
    )
    parser.add_argument(
        "--development-specs",
        type=Path,
        default=ROOT / "benchmarks/external/cad-50-v1.1/comparison-specifications-development.json",
    )
    return parser.parse_args()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _run_files(root: Path) -> list[Path]:
    return sorted(
        [*root.glob("premise-only/*/run.json"), *root.glob("comparison-specification/*/run.json")]
    )


def _worker_ids(record: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for item in (record.get("cad_calls") or {}).get("repair_history", []):
        if not isinstance(item, Mapping):
            continue
        worker = item.get("worker_result")
        worker = worker if isinstance(worker, Mapping) else {}
        if worker.get("job_id"):
            result.add(str(worker["job_id"]))
        elif worker.get("phase") or worker.get("output_ids"):
            result.add(f"{item.get('operation_id')}:worker")
    return result


def _parse_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _reconcile_rate_limit(records: list[dict[str, Any]]) -> dict[str, Any]:
    attempts = [
        item
        for record in records
        for item in record.get("provider_attempt_forensics", [])
        if isinstance(item, Mapping)
    ]
    starts = sorted(
        timestamp
        for item in attempts
        for timestamp in [_parse_timestamp(item.get("request_started_at"))]
        if timestamp is not None
    )
    gaps = [right - left for left, right in zip(starts, starts[1:])]
    by_slot: dict[str, list[float]] = {}
    for item in attempts:
        timestamp = _parse_timestamp(item.get("request_started_at"))
        slot = str(item.get("credential_slot") or "unknown")
        if timestamp is not None:
            by_slot.setdefault(slot, []).append(timestamp)
    same_slot_gaps = [
        right - left
        for slot_starts in by_slot.values()
        for left, right in zip(sorted(slot_starts), sorted(slot_starts)[1:])
    ]
    fallback_attempts = [item for item in attempts if item.get("credential_slot") == "fallback"]
    fallback_allowed = 0
    for fallback in fallback_attempts:
        logical_id = fallback.get("logical_operation_id")
        preceding = [
            item
            for item in attempts
            if item.get("logical_operation_id") == logical_id
            and item.get("credential_slot") == "primary"
            and item.get("status_code") == 429
        ]
        if preceding:
            fallback_allowed += 1
    rolling_max = max(
        (sum(1 for candidate in starts if start - 60.0 < candidate <= start) for start in starts),
        default=0,
    )
    return {
        "schema_version": "external-cad-development-first-pass-v1-rate-limit-audit",
        "reconciled_offline": True,
        "concurrency": 1,
        "minimum_start_gap_seconds": min(gaps) if gaps else None,
        "minimum_same_slot_start_gap_seconds": min(same_slot_gaps) if same_slot_gaps else None,
        "rolling_window_maximum": rolling_max,
        "same_slot_rolling_window_maximum": max(
            (
                sum(1 for candidate in slot_starts if start - 60.0 < candidate <= start)
                for slot_starts in by_slot.values()
                for start in slot_starts
            ),
            default=0,
        ),
        "policy_unchanged": True,
        "fallback_policy": "fallback only after HTTP 429",
        "transport_attempt_count": len(attempts),
        "fallback_attempt_count": len(fallback_attempts),
        "fallback_after_primary_429_count": fallback_allowed,
        "fallback_policy_observed": fallback_allowed == len(fallback_attempts),
        "429_attempt_count": sum(item.get("status_code") == 429 for item in attempts),
        "request_start_timestamps": [item.get("request_started_at") for item in attempts],
    }


def main() -> None:
    args = _parse_args()
    projects = load_frozen_development_projects(args.v11_manifest, args.v1_manifest, args.development_specs)
    run_files = _run_files(args.evidence_root)
    records: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for path in run_files:
            record = json.loads(path.read_text(encoding="utf-8"))
            workflow_id = record.get("workflow_id")
            workflow = db.get(ValidatedCadQueryWorkflow, workflow_id) if workflow_id else None
            revision = db.get(Revision, workflow.revision_id) if workflow and workflow.revision_id else None
            ids = _worker_ids(record)
            worker = dict(record.get("worker") or {})
            worker.update(
                {
                    "execution_count": len(ids),
                    "job_ids": sorted(ids),
                    "revision_execution_manifest_path": revision.execution_manifest_path if revision else None,
                    "reconciled_from_runtime_db": True,
                }
            )
            record["worker"] = worker
            record["worker_executions_reconciled"] = True
            _write_json(path, record)
            records.append(record)

    matrix = {
        "schema_version": "external-cad-development-first-pass-v1-first-blocker-matrix",
        "reconciled_offline": True,
        "cells": [
            {
                key: record.get(key)
                for key in (
                    "benchmark_project_id",
                    "category",
                    "mode",
                    "state",
                    "terminal_stage",
                    "first_blocker_stage",
                    "failure_class",
                    "first_incorrect_owner",
                    "normal_recovery_resolved",
                )
            }
            for record in records
        ],
    }
    _write_json(args.evidence_root / "first-blocker-matrix.json", matrix)
    _write_json(args.evidence_root / "rate-limit-audit.json", _reconcile_rate_limit(records))
    _write_json(
        args.evidence_root / "reconciliation.json",
        {
            "schema_version": "external-cad-development-first-pass-v1-evidence-reconciliation",
            "reconciled_offline": True,
            "source_runtime_data_dir": str(args.runtime_data_dir),
            "cell_count": len(records),
            "provider_calls": 0,
            "worker_executions_during_reconciliation": 0,
            "reason": "worker execution identities and ISO request timestamps were not fully carried into the initial compact evidence serializer",
            "workflow_outcomes_unchanged": True,
        },
    )
    summary = json.loads((args.evidence_root / "survey-summary.json").read_text(encoding="utf-8"))
    summary["worker_executions"] = sum(int((record.get("worker") or {}).get("execution_count") or 0) for record in records)
    for mode in ("premise_only", "comparison_specification"):
        summary.setdefault("by_mode", {}).setdefault(mode, {})["worker_executions"] = sum(
            int((record.get("worker") or {}).get("execution_count") or 0)
            for record in records
            if record.get("mode") == mode
        )
    summary["evidence_reconciled_offline"] = True
    _write_json(args.evidence_root / "survey-summary.json", summary)


if __name__ == "__main__":
    main()
