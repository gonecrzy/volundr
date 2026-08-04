"""Deterministic resolution of previously recorded calibration observations."""

from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from app.services.ollama_benchmark.calibration import (
    CalibrationIssue,
    EXPECTED_MODEL_IDENTITIES,
    build_resolution_aggregates,
    build_resolution_queue,
    classify_calibration_failure,
    inspect_native_response,
    inspect_structured_response,
    load_calibration_profile,
    normalize_native_source,
    normalize_structured_response,
    wrap_native_source_for_worker,
)
from app.services.ollama_benchmark.runner import (
    CALIBRATION_SCHEMA_VERSION,
    CalibrationRunnerConfig,
    OllamaCalibrationRunner,
    SLOT_IDS,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_path(evidence_root: Path, evidence_path: str) -> Path:
    evidence = evidence_root / evidence_path
    candidate = evidence.parent / "raw-response.txt"
    if candidate.exists():
        return candidate
    if evidence.parent.name == "worker":
        return evidence.parent.parent / "raw-response.txt"
    return candidate


def _case_id(evidence_path: str) -> str:
    for part in Path(evidence_path).parts:
        if part.startswith("calibration-") or part.startswith("holdout-"):
            return part
    return ""


def _mode(evidence_path: str, stage: str) -> str:
    if "production-slot" in Path(evidence_path).parts or stage == "production_slot":
        return "production_slot"
    return "native"


def _issue_from_dict(payload: dict[str, Any]) -> CalibrationIssue:
    fields = {field: payload[field] for field in CalibrationIssue.__dataclass_fields__ if field in payload}
    fields.setdefault("message", "")
    fields.setdefault("model", "")
    fields.setdefault("status", "open")
    return CalibrationIssue(**fields)


async def resolve_existing_evidence(
    *,
    source_root: Path,
    output_root: Path,
    profiles_dir: Path,
) -> dict[str, Any]:
    """Inspect every original issue and retain its full lifecycle history."""

    original_queue = _read_json(source_root / "resolution-queue.json")
    if not isinstance(original_queue, list):
        raise ValueError("source resolution queue must be a list")
    output_root.mkdir(parents=True, exist_ok=True)
    existing_output_queue_path = output_root / "resolution-queue.json"
    existing_output_queue = _read_json(existing_output_queue_path) if existing_output_queue_path.exists() else []
    if not isinstance(existing_output_queue, list):
        existing_output_queue = []
    runner = OllamaCalibrationRunner(
        CalibrationRunnerConfig(output_root=output_root, profiles_dir=profiles_dir, run_holdout=False, dry_run=True),
        repo_root=source_root.parents[3],
    )
    runner.experiment_root = output_root
    original_records: list[CalibrationIssue] = []
    profile_hashes: dict[str, str] = {}
    for original in original_queue:
        model = str(original.get("model", ""))
        evidence_path = str(original.get("evidence_path", ""))
        mode = _mode(evidence_path, str(original.get("stage", "")))
        case_id = _case_id(evidence_path)
        expected_identity = next((item for item in EXPECTED_MODEL_IDENTITIES if item.model_name == model), None)
        profile = None
        if expected_identity is not None:
            profile = load_calibration_profile(profiles_dir / OllamaCalibrationRunner._profile_filename(expected_identity.model_id or ""))
        raw_path = _raw_path(source_root, evidence_path)
        raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
        if mode == "production_slot":
            inspection = inspect_structured_response(raw, expected_slot_ids=SLOT_IDS)
        else:
            inspection = inspect_native_response(raw)
        record_root = output_root / "resolution-history" / str(original.get("issue_id"))
        record_root.mkdir(parents=True, exist_ok=True)
        inspection_payload = {
            "original_issue": original,
            "raw_path": str(raw_path),
            "raw_hash": inspection.raw_hash,
            "normalized_hash": inspection.normalized_hash,
            "prompt_mode": mode,
            "calibration_case": case_id,
            "profile_version": profile.profile_version if profile else "unknown",
            "profile_hash": profile.profile_hash if profile else "",
            "stop_reason": "not available in original calibration response record",
            "token_count": "not available in original calibration response record",
            "signature": inspection.signature,
            "classification": inspection.classification,
            "safe_normalization_eligible": inspection.safe_normalization_eligible,
            "parser_result": inspection.parser_result,
            "codes": list(inspection.codes),
        }
        if inspection.normalized_response is not None:
            inspection_payload["normalized_response"] = inspection.normalized_response
            (record_root / "normalized-response.txt").write_text(inspection.normalized_response, encoding="utf-8")
        (record_root / "inspection.json").write_text(json.dumps(inspection_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        status = "accepted_model_limitation"
        result = "precise classification recorded; no safe normalization applied"
        if inspection.normalized_response is not None and inspection.safe_normalization_eligible:
            status = "normalized"
            result = "safe representation normalization succeeded; worker reprocessing pending"
        elif inspection.classification == "rejected" and original.get("owner") == "cad":
            status = "cad_quality_finding"
            result = "worker/topology finding preserved from original evidence"
        elif inspection.signature in {"native_script_instead_of_slots", "unsupported_helpers", "imports_in_slot", "missing_slots", "duplicate_slots", "unknown_slots"}:
            status = "accepted_model_limitation"

        updated = _issue_from_dict({
            **original,
            "message": original.get("message", inspection.parser_result),
            "aggregate_signature": inspection.signature,
            "safe_normalization_eligible": inspection.safe_normalization_eligible,
            "required_next_action": "Preserve CAD finding" if original.get("owner") == "cad" else "No CAD repair; retain native/slot capability separation",
            "reprocessing_result": result,
            "status": status,
            "response_mode": mode,
            "calibration_case": case_id,
            "profile_version": profile.profile_version if profile else "unknown",
            "profile_hash": profile.profile_hash if profile else "",
            "raw_hash": inspection.raw_hash,
            "normalized_hash": inspection.normalized_hash,
        })
        original_records.append(updated)

        if inspection.normalized_response is None or not inspection.safe_normalization_eligible:
            continue
        try:
            if mode == "production_slot":
                normalized = normalize_structured_response(raw, expected_slot_ids=SLOT_IDS)
                payload = json.loads(normalized.normalized_response)
                statements = [statement for slot in payload["slots"] for statement in slot["statements"]]
                result_symbol = str(payload["slots"][-1]["result_symbol"])
                if not re.fullmatch(r"[A-Za-z_]\w*", result_symbol):
                    raise ValueError("slot result_symbol is not an unambiguous Python name")
                source = "import cadquery as cq\n" + "\n".join(str(statement) for statement in statements) + f"\nresult = {result_symbol}\n"
            else:
                normalized = normalize_native_source(raw)
                source = normalized.normalized_response
            worker = await runner._execute_worker(
                wrap_native_source_for_worker(source),
                record_root,
                f"resolution-{original.get('issue_id')}",
                case_id=case_id,
            )
            runner._record_worker_finding(
                model,
                record_root,
                worker,
                response_mode=mode,
                calibration_case=case_id,
                profile_version=profile.profile_version if profile else "unknown",
                profile_hash=profile.profile_hash if profile else "",
                raw_hash=inspection.raw_hash,
                normalized_hash=inspection.normalized_hash,
            )
            updated_index = len(original_records) - 1
            if worker.get("success") and worker.get("topology_validated") and worker.get("broad_geometry_validated"):
                original_records[updated_index] = replace(
                    original_records[updated_index],
                    status="resolved",
                    reprocessing_result="normalized, worker executed, topology and broad geometry validated",
                )
            else:
                original_records[updated_index] = replace(
                    original_records[updated_index],
                    status="cad_quality_finding" if original.get("owner") == "cad" else "resolved",
                    reprocessing_result="representation normalized; worker/topology CAD finding reproduced" if original.get("owner") == "cad" else "representation normalized; worker finding retained as separate CAD evidence",
                )
        except (ValueError, json.JSONDecodeError) as exc:
            original_records[-1] = replace(
                original_records[-1],
                status="accepted_model_limitation",
                reprocessing_result=f"safe extraction did not yield executable source: {exc}",
            )

    current_pass_records = []
    for item in existing_output_queue:
        record = _issue_from_dict(item)
        record = replace(
            record,
            issue_id=hashlib.sha256(
                f"current-pass:{record.issue_id}:{record.model}:{record.stage}:{record.evidence_path}".encode("utf-8")
            ).hexdigest()[:16],
        )
        if not record.profile_hash:
            expected_identity = next((candidate for candidate in EXPECTED_MODEL_IDENTITIES if candidate.model_name == record.model), None)
            if expected_identity is not None:
                profile = load_calibration_profile(profiles_dir / OllamaCalibrationRunner._profile_filename(expected_identity.model_id or ""))
                record = replace(record, profile_version=profile.profile_version, profile_hash=profile.profile_hash or "")
        if record.status == "open" and record.error_code.startswith("cad."):
            record = replace(record, status="cad_quality_finding")
        elif record.status == "open" and (record.error_code.startswith("model.") or record.error_code.startswith("profile.")):
            record = replace(record, status="accepted_model_limitation")
        current_pass_records.append(record)
    all_issues = original_records + current_pass_records + runner.issues
    queue = build_resolution_queue(all_issues)
    aggregates = build_resolution_aggregates(all_issues)
    experiment = {
        "schema_version": "ollama-resolution-v1",
        "source_evidence_root": str(source_root),
        "calibration_schema_version": CALIBRATION_SCHEMA_VERSION,
        "original_issue_count": len(original_records),
        "new_issue_count": len(current_pass_records) + len(runner.issues),
        "formal_benchmark_started": False,
        "gemini_called": False,
        "one_active_model_at_a_time": True,
    }
    (output_root / "resolution-experiment.json").write_text(json.dumps(experiment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_root / "resolution-queue.json").write_text(json.dumps(queue, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_root / "resolution-aggregates.json").write_text(json.dumps(aggregates, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"issues": queue, "aggregates": aggregates, "experiment": experiment}
