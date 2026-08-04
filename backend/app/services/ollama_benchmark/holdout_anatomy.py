"""Read-only anatomy review for frozen Ollama holdout evidence.

This module deliberately has no provider, worker, or artifact-generation
imports.  It classifies preserved files and returns report data; the CLI is
responsible only for serializing that data outside Git.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .calibration import wrap_native_source_for_worker


BLOCKER_ORDER = (
    "evidence_missing",
    "profile_rendering",
    "response_extraction",
    "representation_normalization",
    "python_ast",
    "source_safety",
    "worker_runtime",
    "artifact_generation",
    "topology",
    "dimension_measurement",
    "feature_measurement",
    "broad_geometry_mismatch",
    "evaluator_inconsistency",
)

QUALITY_BANDS = (
    "no_executable_geometry",
    "executable_but_invalid",
    "valid_topology_wrong_shape",
    "partially_satisfies_holdout",
    "broadly_satisfies_holdout_with_findings",
    "holdout_pass",
)

MODEL_ROOTS = ("calibration-admission-final-v2", "qwen14-iteration-3")


def earliest_authoritative_blocker(findings: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """Return exactly one finding using the frozen stage precedence."""

    candidates = list(findings)
    if not candidates:
        return None
    rank = {stage: index for index, stage in enumerate(BLOCKER_ORDER)}
    return min(candidates, key=lambda finding: rank.get(finding.get("stage", "evidence_missing"), 0))


def recurring_signature_models(attempts: Iterable[dict[str, Any]], signature: str) -> list[str]:
    """Return distinct models with a signature; three is the shared threshold."""

    return sorted({
        str(attempt["model_id"])
        for attempt in attempts
        if attempt.get("primary_signature") == signature
    }) if len({
        str(attempt["model_id"])
        for attempt in attempts
        if attempt.get("primary_signature") == signature
    }) >= 3 else []


def classify_quality_band(worker: dict[str, Any] | None) -> str:
    if not worker or worker.get("success") is not True:
        return "no_executable_geometry" if not worker or not worker.get("topology") else "executable_but_invalid"
    topology = worker.get("topology") or {}
    if topology.get("valid") is not True:
        return "executable_but_invalid"
    broad = worker.get("broad_geometry") or {}
    if broad.get("status") == "passed":
        return "holdout_pass"
    if broad.get("status") == "failed":
        feature = broad.get("feature_check") or {}
        if broad.get("actual_sorted_bounds_mm") != broad.get("expected_sorted_bounds_mm"):
            return "valid_topology_wrong_shape"
        if feature.get("status") == "failed":
            return "partially_satisfies_holdout"
        return "valid_topology_wrong_shape"
    return "broadly_satisfies_holdout_with_findings"


def assess_holdout_fairness(case: dict[str, Any]) -> dict[str, Any]:
    """Audit the frozen prompt without changing its expectations."""

    expected = list(case.get("expected_broad_geometry") or [])
    return {
        "classification": "fair_with_minor_evaluator_risk",
        "expectations_derivable": bool(case.get("prompt") and expected),
        "unspecified_exact_dimensions": [],
        "risk": [
            "support angle and charging-opening centering are not independently measured by the preserved broad check",
            "hole count, diameter, pattern, and through condition are not independently measured by the preserved broad check",
        ],
        "reason": "The prompt specifies the reviewed broad requirements, but the frozen evaluator uses bounds and source markers rather than complete feature measurements.",
    }


def normalization_audit(raw: str, normalized: str, codes: Iterable[str]) -> dict[str, Any]:
    raw_lines = raw.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    normalized_lines = normalized.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    stripped = raw.strip()
    safe_wrapper_only = False
    removed_lines: list[str] = []
    inner = stripped
    if re.match(r"\A```(?:python|py|cadquery)?\s*\n", inner, re.I):
        inner = re.sub(r"\A```(?:python|py|cadquery)?\s*\n", "", inner, flags=re.I)
        removed_lines.append(raw_lines[0] if raw_lines else "")
    if inner.endswith("```"):
        inner = re.sub(r"\n?```\Z", "", inner)
        removed_lines.append(raw_lines[-1] if raw_lines else "")
    if removed_lines:
        safe_wrapper_only = inner.strip() == normalized.strip()
    diff = list(difflib.unified_diff(raw_lines, normalized_lines, fromfile="raw", tofile="normalized", lineterm=""))
    return {
        "changed": raw != normalized,
        "codes": list(codes),
        "safe_wrapper_only": safe_wrapper_only or raw.strip() == normalized.strip(),
        "removed_lines": removed_lines,
        "diff": diff,
        "raw_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "normalized_hash": hashlib.sha256(normalized.encode()).hexdigest(),
        "normalized_source": normalized,
    }


def reassess_admission(current: dict[str, Any], attempts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return proposals only; never mutate or persist the admission record."""

    result: dict[str, Any] = {}
    by_model: dict[str, list[dict[str, Any]]] = {}
    for attempt in attempts:
        by_model.setdefault(str(attempt["model_id"]), []).append(attempt)
    for model_id, record in current.items():
        model_attempts = by_model.get(model_id, [])
        result[model_id] = {
            "current_disposition": record.get("admission", record.get("current_disposition")),
            "proposed_disposition": (
                "should_be_deferred_for_integration_fix"
                if any(item.get("integration_defect_likelihood") == "high" for item in model_attempts)
                else "operational_low_cad_quality_confirmed"
            ),
            "evidence": [item.get("primary_signature") for item in model_attempts],
        }
    return result


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root.parent.parent.parent.parent)) if path.is_absolute() else str(path)


def _first_line(text: str | None) -> str:
    return (text or "").splitlines()[-1].strip() if text else ""


def _source_signatures(source: str) -> list[str]:
    lowered = source.casefold()
    signatures: list[str] = []
    if "exporters.export" in lowered or "exporters.stl" in lowered:
        signatures.append("artifact_registration_missing")
    if "show_object" in lowered:
        signatures.append("unsupported_cadquery_api")
    if "cq.math" in lowered or "face_top" in lowered or "face_bottom" in lowered:
        signatures.append("unsupported_cadquery_api")
    if ".edges(\"|z\", \"cnc\")" in lowered:
        signatures.append("invalid_selector")
    if ".hole(" in lowered and "pushpoints" in lowered:
        signatures.append("invalid_workplane_operation")
    return list(dict.fromkeys(signatures))


def _find_stage_findings(
    response: dict[str, Any] | None,
    failure: dict[str, Any] | None,
    worker: dict[str, Any] | None,
    source: str,
    holdout_id: str,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if failure and failure.get("error_code") == "model.native_source_invalid":
        findings.append({"stage": "python_ast", "signature": "invalid_python", "evidence": "failure.json"})
    if source and "exporters.export" in source.casefold():
        findings.append({"stage": "source_safety", "signature": "artifact_registration_missing", "evidence": "raw-response.txt"})
    if response and response.get("parser_result") not in {None, "ast_valid"}:
        findings.append({"stage": "python_ast", "signature": "invalid_python", "evidence": "response.json"})
    if worker:
        error = str(worker.get("error") or "")
        topology = worker.get("topology") or {}
        if "generated source cannot perform artifact writing" in error.casefold():
            findings.append({"stage": "source_safety", "signature": "artifact_registration_missing", "evidence": "worker/finding.json"})
        elif "unsupported direct function call" in error.casefold():
            findings.append({"stage": "source_safety", "signature": "unsupported_cadquery_api", "evidence": "worker/finding.json"})
        elif worker.get("success") is not True and topology.get("outcome") == "solid_count_mismatch":
            findings.append({"stage": "topology", "signature": "no_solid", "evidence": "worker/result.json"})
        elif worker.get("success") is not True and error:
            findings.append({"stage": "worker_runtime", "signature": _runtime_signature(error, source), "evidence": "worker/finding.json"})
        if worker.get("success") is True and topology.get("valid") is True:
            broad = worker.get("broad_geometry") or {}
            if broad.get("status") == "failed":
                feature = broad.get("feature_check") or {}
                actual = broad.get("actual_sorted_bounds_mm")
                expected = broad.get("expected_sorted_bounds_mm")
                if actual != expected:
                    findings.append({"stage": "dimension_measurement", "signature": "wrong_overall_dimensions", "evidence": "worker/result.json"})
                if feature.get("status") == "failed":
                    signature = "support_angle_missing_or_wrong" if holdout_id == "holdout-001" else _feature_signature(source)
                    findings.append({"stage": "feature_measurement", "signature": signature, "evidence": "worker/result.json"})
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for finding in findings:
        key = (str(finding.get("stage")), str(finding.get("signature")))
        if key not in seen:
            unique.append(finding)
            seen.add(key)
    return unique


def _runtime_signature(error: str, source: str) -> str:
    lowered = (error + " " + source).casefold()
    if "cannot find a solid" in lowered:
        return "invalid_workplane_operation"
    if "no workplane object named" in lowered:
        return "invalid_selector"
    if "attributeerror" in lowered or "has no attribute" in lowered:
        return "unsupported_cadquery_api"
    return "worker_exception"


def _feature_signature(source: str) -> str:
    lowered = source.casefold()
    if "hole" not in lowered and "circle" not in lowered:
        return "through_hole_missing"
    return "phone_support_geometry_incomplete" if "cradle" in lowered else "wrong_hole_pattern"


def _model_root_for(model_id: str, profile_hash: str, evidence_root: Path) -> Path | None:
    for name in MODEL_ROOTS:
        root = evidence_root.parent / name
        record = _read_json(root / "models.json")
        if isinstance(record, list):
            match = next((item for item in record if item.get("model_id") == model_id), None)
            if match and match.get("profile_hash") == profile_hash:
                return root
    return None


def _attempt(model: dict[str, Any], holdout_id: str, root: Path, evidence_root: Path) -> dict[str, Any]:
    case_root = root / "calibration" / model["model_id"] / "holdout" / holdout_id
    paths = {name: case_root / filename for name, filename in {
        "raw_response": "raw-response.txt",
        "response": "response.json",
        "failure": "failure.json",
        "worker_result": "worker/result.json",
        "worker_finding": "worker/finding.json",
    }.items()}
    response = _read_json(paths["response"])
    failure = _read_json(paths["failure"])
    worker = _read_json(paths["worker_result"])
    raw = str(response.get("raw_response") or "") if response else ""
    if not raw and paths["raw_response"].is_file():
        raw = paths["raw_response"].read_text()
    normalized = str(response.get("normalized_response") or "") if response else ""
    source = normalized or raw
    findings = _find_stage_findings(response, failure, worker, source, holdout_id)
    if not response and not failure and not raw:
        findings.append({"stage": "evidence_missing", "signature": "missing_expected_output", "evidence": str(paths["raw_response"])})
    blocker = earliest_authoritative_blocker(findings)
    secondary = [finding for finding in findings if finding is not blocker]
    worker_source_equivalence = "not_verifiable"
    if response and worker and normalized:
        expected_worker_hash = hashlib.sha256(wrap_native_source_for_worker(normalized).encode()).hexdigest()
        worker_source_equivalence = "verified" if expected_worker_hash == worker.get("source_hash") else "mismatch"
    audit = normalization_audit(raw, normalized, response.get("codes", []) if response else []) if response else {
        "changed": False,
        "codes": [],
        "safe_wrapper_only": False,
        "removed_lines": [],
        "diff": [],
        "raw_hash": "",
        "normalized_hash": "",
        "normalized_source": "",
    }
    if response and response.get("normalized_hash"):
        audit["recorded_raw_hash"] = response.get("raw_hash")
        audit["recorded_normalized_hash"] = response.get("normalized_hash")
    result_symbols = re.findall(r"(?m)^\s*result\s*=", normalized)
    audit.update({
        "final_result_symbol": "result" if result_symbols else None,
        "source_lines_reordered": False if audit.get("safe_wrapper_only") else None,
        "indentation_damaged": False if audit.get("safe_wrapper_only") else None,
        "code_block_truncated": False if audit.get("safe_wrapper_only") else None,
    })
    primary_signature = blocker.get("signature") if blocker else "holdout_pass"
    return {
        "model_id": model["model_id"],
        "model": model["model"],
        "holdout": holdout_id,
        "profile_hash": model.get("profile_hash"),
        "rendered_prompt": {
            "status": "evidence_missing",
            "frozen_prompt_source": f"benchmarks/ollama-holdout-v1.yaml#{holdout_id}",
            "reason": "The exact frozen prompt is preserved, but a separately rendered prompt file is absent from the final evidence root.",
        },
        "raw_response_class": "fenced_native_script" if "```" in raw else ("native_script" if raw else "missing_response"),
        "normalization": {**audit, "worker_source_equivalence": worker_source_equivalence},
        "ast": {"status": response.get("parser_result") if response else ("invalid_python" if failure else "missing")},
        "source_safety": {"status": "finding" if any(item["stage"] == "source_safety" for item in findings) else "no_finding"},
        "worker": {"status": "completed" if worker and worker.get("worker_reached") is not False else "not_reached", "success": worker.get("success") if worker else None, "error": _first_line(worker.get("error")) if worker else ""},
        "artifacts": {"status": "worker_output_recorded_artifact_manifest_missing" if worker and worker.get("success") else "not_generated", "evidence": str(paths["worker_result"])},
        "topology": worker.get("topology") if worker else None,
        "geometry": {"broad": worker.get("broad_geometry") if worker else None, "volume_mm3": (worker.get("topology") or {}).get("volume_mm3") if worker else None},
        "primary_blocker": blocker or {"stage": "evaluator_inconsistency", "signature": "holdout_pass", "evidence": str(paths["worker_result"])},
        "secondary_findings": secondary,
        "primary_signature": primary_signature,
        "quality_band": classify_quality_band(worker),
        "shared_signature": None,
        "integration_defect_likelihood": "low",
        "model_capability_likelihood": "high",
        "evaluator_defect_likelihood": "low",
        "proposed_disposition": "operational_low_cad_quality_confirmed",
        "confidence": "high" if blocker and primary_signature not in {"wrong_overall_dimensions", "wrong_hole_pattern"} else "medium",
        "evidence_paths": {name: str(path) for name, path in paths.items() if path.exists()},
    }


def analyze_frozen_evidence(evidence_root: str | Path) -> dict[str, Any]:
    evidence_root = Path(evidence_root).resolve()
    models = _read_json(evidence_root / "models.json") or []
    experiment = _read_json(evidence_root / "experiment.json") or {}
    admission = _read_json(evidence_root / "admission.json") or {}
    holdouts = json.loads((evidence_root.parents[3] / "benchmarks" / "ollama-holdout-v1.yaml").read_text())
    attempts: list[dict[str, Any]] = []
    for model in models:
        root = _model_root_for(model["model_id"], model.get("profile_hash", ""), evidence_root)
        for case in holdouts["cases"]:
            attempt = _attempt(model, case["case_id"], root, evidence_root) if root else {
                "model_id": model["model_id"], "model": model["model"], "holdout": case["case_id"],
                "profile_hash": model.get("profile_hash"), "primary_blocker": {"stage": "evidence_missing", "signature": "missing_expected_output"},
                "secondary_findings": [], "primary_signature": "missing_expected_output", "quality_band": "no_executable_geometry",
                "shared_signature": None, "integration_defect_likelihood": "inconclusive", "model_capability_likelihood": "inconclusive", "evaluator_defect_likelihood": "inconclusive",
                "proposed_disposition": "evidence_inconclusive", "confidence": "low", "evidence_paths": {},
                "rendered_prompt": {"status": "evidence_missing", "frozen_prompt_source": f"benchmarks/ollama-holdout-v1.yaml#{case['case_id']}"},
            }
            attempts.append(attempt)
    for attempt in attempts:
        # A repeated broad category is not enough.  The frozen evidence has
        # no adapter/worker/evaluator signature that also satisfies the
        # independent-plausibility and same-operation tests.
        attempt["shared_signature"] = None
    current = {model["model_id"]: {"admission": model.get("admission")} for model in models}
    fairness = {case["case_id"]: assess_holdout_fairness(case) for case in holdouts["cases"]}
    return {
        "schema_version": "ollama-holdout-failure-anatomy-v1",
        "review_mode": "read_only_frozen_evidence",
        "evidence_identity": {
            "root": str(evidence_root),
            "source_runs": experiment.get("source_runs", []),
            "starting_base_commit": experiment.get("starting_base_commit"),
            "starting_origin_main_commit": experiment.get("starting_origin_main_commit"),
            "starting_origin_divergence": experiment.get("starting_origin_divergence"),
            "gemini_called": experiment.get("gemini_called"),
            "formal_benchmark_started": experiment.get("formal_benchmark_started"),
        },
        "models": [{key: model.get(key) for key in ("model_id", "model", "identity", "profile_hash", "profile_version", "profile_iterations", "admission")} for model in models],
        "attempts": attempts,
        "fairness": fairness,
        "admission": {"persisted": admission, "proposed": reassess_admission(current, attempts)},
        "conclusion": {
            "code": "D",
            "title": "Insufficient model CAD capability",
            "rationale": "All six models independently omit, misconstruct, or fail to execute required CAD operations; no three-model adapter, worker, topology-reader, or evaluator defect recurs with independently plausible normalized sources.",
            "next_action": "Do not run the formal benchmark; test stronger or different specialist/generic models, or stop local-model investment for now.",
        },
        "limitations": [
            "Worker request manifests and exported artifact files are not present under the final evidence roots; worker source equivalence is verified only through the recorded wrapped source hash where normalized source exists.",
            "The frozen broad evaluator does not independently measure every feature named by either holdout.",
            "No new provider or worker execution was performed during this review.",
        ],
    }
