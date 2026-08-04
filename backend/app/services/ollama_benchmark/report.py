"""Combine bounded calibration runs into one admission report."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Iterable

from app.services.ollama_benchmark.calibration import EXPECTED_MODEL_IDENTITIES, admission_gate


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def combine_calibration_runs(*, run_roots: Iterable[Path], output_root: Path) -> dict[str, Any]:
    records_by_id: dict[str, dict[str, Any]] = {}
    queues: list[dict[str, Any]] = []
    sources: list[str] = []
    source_experiments: list[dict[str, Any]] = []
    for root in run_roots:
        sources.append(str(root))
        experiment_path = root / "experiment.json"
        if experiment_path.exists():
            source_experiments.append(json.loads(experiment_path.read_text(encoding="utf-8")))
        models_path = root / "models.json"
        if models_path.exists():
            payload = json.loads(models_path.read_text(encoding="utf-8"))
            for record in payload if isinstance(payload, list) else []:
                records_by_id[str(record.get("model_id"))] = record
        queue_path = root / "resolution-queue.json"
        if queue_path.exists():
            payload = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                for issue in payload:
                    if not isinstance(issue, dict):
                        continue
                    copied = dict(issue)
                    copied["source_run"] = str(root)
                    copied["issue_id"] = hashlib.sha256(
                        f"{root}:{issue.get('issue_id')}:{issue.get('model')}:{issue.get('stage')}:{issue.get('evidence_path')}".encode("utf-8")
                    ).hexdigest()[:16]
                    queues.append(copied)
    records = [records_by_id[item.model_id] for item in EXPECTED_MODEL_IDENTITIES if item.model_id in records_by_id]
    admission = admission_gate(records, intended_model_ids=[item.model_id for item in EXPECTED_MODEL_IDENTITIES])
    admission_payload = {
        **{
            "formal_benchmark_authorized": admission.formal_benchmark_authorized,
            "specialist_count": admission.specialist_count,
            "generic_baseline_count": admission.generic_baseline_count,
            "blocking_model_ids": list(admission.blocking_model_ids),
            "reason": admission.reason,
        },
        "formal_benchmark_started": False,
        "gemini_called": False,
        "source_runs": sources,
    }
    experiment = {
        "schema_version": "ollama-admission-report-v1",
        "source_runs": sources,
        "source_experiments": source_experiments,
        "formal_benchmark_started": False,
        "gemini_called": False,
        "one_active_model_at_a_time": True,
        "intended_models": [item.model_id for item in EXPECTED_MODEL_IDENTITIES],
    }
    starting_root = output_root.parent / "calibration-live-all-remaining"
    starting_experiment_path = starting_root / "experiment.json"
    if starting_experiment_path.exists():
        starting = json.loads(starting_experiment_path.read_text(encoding="utf-8"))
        experiment["starting_base_commit"] = starting.get("base_commit")
        experiment["starting_origin_main_commit"] = starting.get("origin_main_commit")
        experiment["starting_origin_divergence"] = starting.get("origin_divergence")
    _write(output_root / "experiment.json", experiment)
    _write(output_root / "models.json", records)
    admission_payload["starting_base_commit"] = experiment.get("starting_base_commit")
    admission_payload["starting_origin_main_commit"] = experiment.get("starting_origin_main_commit")
    admission_payload["starting_origin_divergence"] = experiment.get("starting_origin_divergence")
    _write(output_root / "admission.json", admission_payload)
    _write(output_root / "resolution-queue.json", queues)
    return {"models": records, "admission": admission_payload, "queue": queues}
