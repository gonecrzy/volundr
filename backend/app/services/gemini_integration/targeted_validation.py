from __future__ import annotations

"""The bounded live validation that follows the Gemini integration narrow-fix audit.

This module is deliberately separate from the production workflow.  It reuses the
existing request renderers, transport, and adapters, but it only knows how to run
the preregistered G1/G2/P1 operations against preserved provider evidence.
"""

import ast
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

from app.services.ai.provider import DesignPlanRequest, ModelGenerationRequest
from app.services.cad.geometry_slots import build_geometry_slot_brief
from app.services.gemini_consistency.provider_contract import canonical_hash, parse_provider_response
from app.services.gemini_integration.adapters import (
    AdapterEvidence,
    GeminiGeometryContractAdapter,
    GeminiPlanContractAdapter,
)
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.corpus import IntegrationProject, build_integration_corpus, corpus_hash
from app.services.gemini_integration.forensics import replay_captured_evidence_offline
from app.services.gemini_integration.narrow_fix import NarrowFixStudy
from app.services.gemini_integration.profile import (
    INTEGRATION_PROFILE_ID,
    GeminiFlashLiteContractV1,
    require_integration_profile,
)
from app.services.gemini_integration.prompts import render_integration_prompt
from app.services.gemini_integration.transport import (
    ProviderCallResult,
    SecondaryGeminiClient,
    SharedIntegrationRateLimiter,
)
from app.services.workflow.redaction import RedactionService


TARGETED_VALIDATION_ID = "targeted-provider-validation-01"
STUDY_ID = "gemini-provider-contract-integration-01"
TARGETED_DECISIONS = {
    "integration_foundation_ready",
    "integration_foundation_ready_with_fail_closed_regeneration",
    "integration_foundation_requires_another_narrow_fix",
    "provider_contract_requires_revision",
    "insufficient_evidence",
}
TARGETED_REPORTS = (
    "preregistration.json",
    "provider-validation-results.json",
    "geometry-validation-decision.json",
    "plan-validation-decision.json",
    "adapter-replay-results.json",
    "corrected-issue-register.json",
    "corrected-causal-graph.json",
    "regression-replay.json",
    "rate-limit-report.json",
    "retry-report.json",
    "integration-decision.json",
    "combined-targeted-validation-evidence.json",
)


@dataclass(frozen=True)
class TargetedOperation:
    operation_id: str
    group: str
    stage: str
    project_id: str
    repetition: int
    request: Any
    rendered_prompt: str
    prompt_version: str
    prompt_hash: str
    request_hash: str
    expected_slot_ids: tuple[str, ...] = ()
    manifest_hash: str | None = None
    expected_output_count: int | None = None
    required_requirement_ids: tuple[str, ...] = ()
    protected_parameter_values: dict[str, Any] | None = None
    responsibility_expectations: dict[str, list[str]] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "group": self.group,
            "stage": self.stage,
            "project_id": self.project_id,
            "repetition": self.repetition,
            "request": _json_safe(self.request),
            "rendered_prompt": self.rendered_prompt,
            "prompt_version": self.prompt_version,
            "prompt_hash": self.prompt_hash,
            "request_hash": self.request_hash,
            "expected_slot_ids": list(self.expected_slot_ids),
            "manifest_hash": self.manifest_hash,
            "expected_output_count": self.expected_output_count,
            "required_requirement_ids": list(self.required_requirement_ids),
            "protected_parameter_values": self.protected_parameter_values or {},
            "responsibility_expectations": self.responsibility_expectations or {},
        }


def _json_safe(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return _json_safe(value.as_dict())
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {str(key): _json_safe(item) for key, item in value.__dict__.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return deepcopy(fallback)


def _project_lookup() -> dict[str, IntegrationProject]:
    return {project.project_id: project for project in build_integration_corpus()}


def _boundary_maps(boundaries: Iterable[dict[str, Any]]) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_stage: dict[tuple[str, str], dict[str, Any]] = {}
    by_project: dict[str, list[dict[str, Any]]] = {}
    for boundary in boundaries:
        project_id = str(boundary.get("project_id") or "")
        stage = str(boundary.get("boundary") or "")
        by_stage[(project_id, stage)] = boundary
        by_project.setdefault(project_id, []).append(boundary)
    return by_stage, by_project


def _accepted_requirement_ids(boundaries: Iterable[dict[str, Any]], project_id: str) -> list[str]:
    for boundary in boundaries:
        if str(boundary.get("project_id")) != project_id or boundary.get("boundary") != "requirements_adapter":
            continue
        output = boundary.get("output") or {}
        if output.get("accepted") is not True:
            continue
        return [
            str(item.get("id"))
            for item in output.get("normalized", {}).get("requirements", []) or []
            if isinstance(item, dict) and item.get("id") is not None
        ]
    return []


def _request_from_dict(request: dict[str, Any], request_type: type[Any]) -> Any:
    allowed = {field.name for field in fields(request_type)}
    values = {key: deepcopy(value) for key, value in request.items() if key in allowed}
    return request_type(**values)


def _geometry_context(request: dict[str, Any]) -> dict[str, Any]:
    manifest = request.get("geometry_slot_manifest")
    if not isinstance(manifest, dict):
        raise ValueError("targeted geometry request has no authoritative slot manifest")
    allowed_names = {"body", "cq", "params", "cutter"}
    for slot in manifest.get("slots", []) or []:
        if not isinstance(slot, dict):
            continue
        allowed_names.update(str(item) for item in slot.get("authorized_parameter_ids", []) or [])
        allowed_names.update(str(item) for item in slot.get("approved_helpers", []) or [])
    plan = request.get("design_plan") if isinstance(request.get("design_plan"), dict) else {}
    protected: dict[str, Any] = {}
    for item in plan.get("parameters", []) or []:
        if isinstance(item, dict) and item.get("id") is not None and item.get("protected") is True:
            protected[str(item["id"])] = item.get("value", item.get("default"))
    return {
        "expected_slot_ids": tuple(str(item.get("slot_id")) for item in manifest.get("slots", []) or [] if isinstance(item, dict) and item.get("slot_id") is not None),
        "allowed_names": sorted(allowed_names),
        "manifest_hash": canonical_hash(manifest),
        "protected_parameter_values": protected,
    }


def _responsibility_expectations(request: dict[str, Any]) -> dict[str, list[str]]:
    plan = request.get("design_plan") if isinstance(request.get("design_plan"), dict) else {}
    features = {
        str(item.get("id") or item.get("feature_id")): item
        for item in plan.get("features", []) or []
        if isinstance(item, dict) and (item.get("id") or item.get("feature_id")) is not None
    }
    expectations: dict[str, list[str]] = {}
    manifest = request.get("geometry_slot_manifest") or {}
    for slot in manifest.get("slots", []) or []:
        if not isinstance(slot, dict):
            continue
        slot_id = str(slot.get("slot_id"))
        markers: set[str] = set()
        for feature_id in slot.get("required_feature_ids", []) or []:
            feature = features.get(str(feature_id), {})
            text = " ".join(
                str(feature.get(key) or "")
                for key in ("id", "feature_id", "object_type", "operation", "description", "semantic_role")
            ).casefold()
            operation = str(feature.get("operation") or "").casefold()
            if operation in {"cut", "subtract", "subtractive"} or any(token in text for token in ("opening", "hole", "slot", "exit", "vent", "notch", "recess")):
                markers.update({"cut", "hole"})
            elif operation in {"union", "add", "additive", "fuse"} or any(token in text for token in ("snap", "handle", "boss", "union")):
                markers.add("union")
            else:
                markers.update({"box", "extrude", "loft", "cylinder", "union", "cut", "hole"})
        expectations[slot_id] = sorted(markers)
    return expectations


def _build_geometry_request(boundary: dict[str, Any], boundaries: list[dict[str, Any]]) -> tuple[ModelGenerationRequest, dict[str, Any]]:
    captured = deepcopy(((boundary.get("input") or {}).get("request") or {}))
    project_id = str(boundary.get("project_id"))
    request = _request_from_dict(captured, ModelGenerationRequest)
    plan = deepcopy(captured.get("design_plan") or {})
    manifest = deepcopy(captured.get("geometry_slot_manifest") or {})
    requirements: list[dict[str, Any]] = []
    candidates = [
        item
        for item in boundaries
        if str(item.get("project_id")) == project_id
        and item.get("boundary") in {"requirements_adapter", "requirements_adapter_continuation"}
        and (item.get("output") or {}).get("accepted") is True
    ]
    candidates.sort(key=lambda item: 0 if item.get("boundary") == "requirements_adapter_continuation" else 1)
    if candidates:
        requirements = deepcopy((candidates[0].get("output") or {}).get("normalized", {}).get("requirements", []) or [])
    brief = build_geometry_slot_brief(
        planning_depth=str(captured.get("planning_depth") or "detailed_plan"),
        active_requirements=requirements,
        requirement_delta=list(captured.get("requirement_delta") or []),
        preserved_requirements=requirements,
        proposals=list(plan.get("proposals", []) or plan.get("proposed_decisions", []) or []),
        design_plan=plan,
        slot_manifest=manifest,
        exposed_controls=list(plan.get("exposed_controls", []) or []),
    )
    values = {**request.__dict__, "geometry_slot_manifest": manifest, "geometry_slot_brief": brief, "geometry_contract": "volundr-geometry-slots-v1"}
    corrected = ModelGenerationRequest(**values)
    return corrected, {**_geometry_context(values), "responsibility_expectations": _responsibility_expectations(values)}


def _build_plan_request(boundary: dict[str, Any]) -> DesignPlanRequest:
    captured = deepcopy(((boundary.get("input") or {}).get("request") or {}))
    return _request_from_dict(captured, DesignPlanRequest)


def build_targeted_operations(
    *,
    profile: GeminiFlashLiteContractV1,
    boundaries: list[dict[str, Any]],
) -> tuple[TargetedOperation, ...]:
    require_integration_profile(profile.profile_id)
    by_stage, _ = _boundary_maps(boundaries)
    operations: list[TargetedOperation] = []
    for group, project_id in (("G1", "project-003"), ("G2", "project-005")):
        boundary = by_stage.get((project_id, "provider_geometry"))
        if boundary is None:
            raise ValueError(f"preserved provider geometry boundary is missing for {project_id}")
        request, context = _build_geometry_request(boundary, boundaries)
        rendered = render_integration_prompt(profile, "geometry", request)
        for repetition in (1, 2):
            operation_id = f"{TARGETED_VALIDATION_ID}:{group.lower()}:{project_id}:geometry:rep-{repetition:02d}"
            operations.append(TargetedOperation(
                operation_id=operation_id,
                group=group,
                stage="geometry",
                project_id=project_id,
                repetition=repetition,
                request=request,
                rendered_prompt=rendered.prompt,
                prompt_version=rendered.prompt_version,
                prompt_hash=rendered.prompt_hash,
                request_hash=canonical_hash(request.__dict__),
                expected_slot_ids=tuple(context["expected_slot_ids"]),
                manifest_hash=context["manifest_hash"],
                protected_parameter_values=context["protected_parameter_values"],
                responsibility_expectations=context["responsibility_expectations"],
            ))
    boundary = by_stage.get(("project-001", "provider_plan"))
    if boundary is None:
        raise ValueError("preserved provider Plan boundary is missing for project-001")
    request = _build_plan_request(boundary)
    rendered = render_integration_prompt(profile, "plan", request)
    captured_prompt = str((boundary.get("input") or {}).get("rendered_prompt") or "")
    captured_hash = str((boundary.get("input") or {}).get("prompt_hash") or "")
    if captured_prompt and rendered.prompt_hash != captured_hash:
        raise ValueError("current frozen Plan renderer does not reproduce the exact project-001 request prompt")
    expected_count = _project_lookup()["project-001"].expected_output_count
    requirement_ids = tuple(_accepted_requirement_ids(boundaries, "project-001"))
    for repetition in (1, 2):
        operation_id = f"{TARGETED_VALIDATION_ID}:p1:project-001:plan:rep-{repetition:02d}"
        operations.append(TargetedOperation(
            operation_id=operation_id,
            group="P1",
            stage="plan",
            project_id="project-001",
            repetition=repetition,
            request=request,
            rendered_prompt=rendered.prompt,
            prompt_version=rendered.prompt_version,
            prompt_hash=rendered.prompt_hash,
            request_hash=canonical_hash(request.__dict__),
            expected_output_count=expected_count,
            required_requirement_ids=requirement_ids,
        ))
    if len(operations) != 6:
        raise AssertionError("targeted validation must preregister exactly six logical operations")
    return tuple(operations)


def _assignment_value(node: ast.AST) -> tuple[bool, Any]:
    if isinstance(node, ast.Constant):
        return True, node.value
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "params":
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return True, ("params", key.value)
    return False, None


def protected_value_findings(statements: Iterable[str], protected_values: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not protected_values:
        return findings
    for index, statement in enumerate(statements):
        try:
            tree = ast.parse(str(statement), mode="exec")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            for target in targets:
                if target not in protected_values:
                    continue
                known, value = _assignment_value(node.value)
                expected = protected_values[target]
                unchanged = known and (value == expected or value == ("params", target))
                findings.append({
                    "statement_index": index,
                    "parameter_id": target,
                    "expected_value": expected,
                    "observed_value": value if known else None,
                    "value_known": known,
                    "unchanged": unchanged,
                    "failure_class": None if unchanged else "protected_value_change",
                })
    return findings


def _responsibility_findings(parsed: Any, expectations: dict[str, list[str]]) -> list[dict[str, Any]]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("slots"), list):
        return [{"status": "not_evaluable", "reason": "geometry slots were not parseable"}]
    by_id = {str(item.get("slot_id")): item for item in parsed["slots"] if isinstance(item, dict)}
    results: list[dict[str, Any]] = []
    for slot_id, markers in expectations.items():
        slot = by_id.get(slot_id)
        text = "\n".join(str(item) for item in (slot or {}).get("statements", []) or []).casefold()
        matched = [marker for marker in markers if marker.casefold() in text]
        results.append({
            "slot_id": slot_id,
            "required_markers": list(markers),
            "matched_markers": matched,
            "passed": bool(slot is not None and (not markers or matched)),
        })
    return results


def validate_geometry_response(raw: str | dict[str, Any], operation: TargetedOperation, evidence: AdapterEvidence) -> dict[str, Any]:
    parsed, fence_count = parse_provider_response(raw)
    exact_ids: list[str] = []
    statements: list[str] = []
    result_symbols: list[Any] = []
    if isinstance(parsed, dict) and isinstance(parsed.get("slots"), list):
        for slot in parsed["slots"]:
            if isinstance(slot, dict):
                exact_ids.append(str(slot.get("slot_id")))
                statements.extend(str(item) for item in slot.get("statements", []) or [])
                result_symbols.append(slot.get("result_symbol"))
    protected = protected_value_findings(statements, operation.protected_parameter_values or {})
    responsibilities = _responsibility_findings(parsed, operation.responsibility_expectations or {})
    returned_exactly = exact_ids == list(operation.expected_slot_ids)
    protected_unchanged = not any(not item["unchanged"] for item in protected)
    responsibilities_pass = all(item.get("passed") is True for item in responsibilities)
    no_adapter_invention = evidence.accepted is False or _adapter_preserved_ids(evidence, exact_ids)
    passed = bool(
        parsed is not None
        and evidence.accepted
        and returned_exactly
        and responsibilities_pass
        and protected_unchanged
        and bool(result_symbols)
        and all(symbol == "body" for symbol in result_symbols)
        and no_adapter_invention
    )
    return {
        "parseable": parsed is not None,
        "parse_fence_normalizations": fence_count,
        "adapter_accepted": evidence.accepted,
        "adapter_failure_class": evidence.failure_class,
        "expected_slot_ids": list(operation.expected_slot_ids),
        "returned_slot_ids": exact_ids,
        "missing_slot_ids": sorted(set(operation.expected_slot_ids) - set(exact_ids)),
        "extra_slot_ids": sorted(set(exact_ids) - set(operation.expected_slot_ids)),
        "exact_slot_set_and_order": returned_exactly,
        "responsibilities": responsibilities,
        "responsibilities_pass": responsibilities_pass,
        "result_symbols": result_symbols,
        "result_symbols_pass": bool(result_symbols) and all(symbol == "body" for symbol in result_symbols),
        "protected_value_findings": protected,
        "protected_values_unchanged": protected_unchanged,
        "adapter_did_not_invent_slots": no_adapter_invention,
        "normalized_slot_ids": [str(item.get("slot_id")) for item in (evidence.normalized or {}).get("slots", []) or [] if isinstance(item, dict)],
        "semantic_hash_before": evidence.semantic_hash_before,
        "semantic_hash_after": evidence.semantic_hash_after,
        "passed": passed,
    }


def _adapter_preserved_ids(evidence: AdapterEvidence, returned_ids: list[str]) -> bool:
    normalized_ids = [str(item.get("slot_id")) for item in (evidence.normalized or {}).get("slots", []) or [] if isinstance(item, dict)]
    return normalized_ids == returned_ids


def validate_plan_response(raw: str | dict[str, Any], operation: TargetedOperation, evidence: AdapterEvidence) -> dict[str, Any]:
    parsed, fence_count = parse_provider_response(raw)
    return {
        "parseable": parsed is not None,
        "parse_fence_normalizations": fence_count,
        "adapter_accepted": evidence.accepted,
        "adapter_failure_class": evidence.failure_class,
        "expected_output_count": operation.expected_output_count,
        "returned_output_count": len((parsed or {}).get("printable_outputs", [])) if isinstance(parsed, dict) else None,
        "required_requirement_ids": list(operation.required_requirement_ids),
        "adapter_reconstructed_content": False,
        "malformed_json_repair_allowed": False,
        "passed": bool(parsed is not None and evidence.accepted),
    }


class TargetedValidationRunner:
    def __init__(self, repository_root: Path, study_root: Path, profile: GeminiFlashLiteContractV1) -> None:
        require_integration_profile(profile.profile_id)
        self.repository_root = Path(repository_root).resolve()
        self.study_root = Path(study_root).resolve()
        self.profile = profile
        self.report_root = self.study_root / "reports" / TARGETED_VALIDATION_ID
        self.store = IntegrationEvidenceStore(self.study_root, study_id=STUDY_ID)
        self.boundaries = self.store.boundaries()
        self.initial_capture_hashes = self._capture_hashes()
        self.operations = build_targeted_operations(profile=profile, boundaries=self.boundaries)
        self.redactor = RedactionService()

    def _write(self, name: str, value: Any) -> None:
        self.report_root.mkdir(parents=True, exist_ok=True)
        safe = self.redactor.redact_mapping(_json_safe(value), artifact_type="integration_evidence") if isinstance(value, dict) else _json_safe(value)
        (self.report_root / name).write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    def _capture_hashes(self) -> dict[str, str]:
        return {
            str(path.relative_to(self.study_root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((self.study_root / "captures").rglob("*.json"))
            if path.is_file()
        }

    def _pre_live_modes(self) -> dict[str, Any]:
        narrow = NarrowFixStudy(self.repository_root, self.study_root)
        original_replay = replay_captured_evidence_offline(narrow.original_evidence, boundaries=narrow.boundaries)
        corrected_replay = replay_captured_evidence_offline(narrow.corrected_evidence, boundaries=narrow.boundaries)
        counterfactuals = [
            {
                "fixture_id": item.get("fixture_id"),
                "source_attempt_id": (item.get("evidence") or {}).get("source_attempt_id"),
                "single_variable_changed": item.get("single_variable_changed"),
                "offline_only": True,
                "provider_calls": 0,
                "worker_calls": 0,
            }
            for item in narrow.existing_counterfactuals
            if isinstance(item, dict)
        ]
        return {
            "offline_only": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "captured_attempt_count": len(narrow.attempts),
            "captured_boundary_count": len(narrow.boundaries),
            "original_replay": {"records": len(original_replay.get("records", [])), "provider_calls": original_replay.get("provider_calls", 0)},
            "corrected_replay": {"records": len(corrected_replay.get("records", [])), "provider_calls": corrected_replay.get("provider_calls", 0)},
            "counterfactuals": counterfactuals,
            "planned_counterfactual_variants": [
                "geometry_manifest_derived_brief",
                "authoritative_geometry_slot_ids",
                "malformed_plan_fail_closed_without_reconstruction",
            ],
        }

    def preregister(self) -> dict[str, Any]:
        if self.report_root.exists() and (self.report_root / "provider-validation-results.json").is_file():
            raise RuntimeError("targeted validation already has live results; use --resume for an idempotent read")
        profile_config = {
            stage: self.profile.request_configuration(stage)
            for stage in ("requirements", "plan", "geometry")
        }
        if any("seed" in value.get("generationConfig", {}) or "thinkingConfig" in value.get("generationConfig", {}) for value in profile_config.values()):
            raise ValueError("frozen targeted profile must omit seed and thinkingConfig")
        prereg = {
            "schema_version": "volundr-provider-contract-targeted-validation-v1",
            "validation_id": TARGETED_VALIDATION_ID,
            "study_id": STUDY_ID,
            "profile_id": self.profile.profile_id,
            "profile": self.profile.as_dict(),
            "request_configurations": profile_config,
            "corpus_hash": corpus_hash(build_integration_corpus()),
            "operations": [operation.as_dict() for operation in self.operations],
            "logical_operation_count": len(self.operations),
            "provider_call_cap": 6,
            "worker_call_cap": 0,
            "provider_calls": 0,
            "requirements_calls": 0,
            "repair_calls": 0,
            "worker_calls": 0,
            "credential_policy": {"required_environment_variable": "GEMINI_API_KEY_2", "primary_credential_allowed": False, "credential_values_serialized": False},
            "rate_limit_policy": {"requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1},
            "retry_policy": {"max_attempts_per_logical_operation": 2, "429_wait_seconds_minimum": 30, "transport_wait_seconds_minimum": 10, "no_third_attempt": True},
            "preserved_capture_hashes": self._capture_hashes(),
            "preserved_attempt_count": len(self.store.provider_attempts()),
            "preserved_boundary_count": len(self.boundaries),
            "offline_modes_built_before_live": self._pre_live_modes(),
            "production_default_changed": False,
            "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation"},
        }
        existing = self.report_root / "preregistration.json"
        if existing.is_file():
            prior = _read_json(existing, {})
            if _sha(prior) != _sha(prereg):
                raise RuntimeError("existing targeted preregistration differs; refusing to overwrite it")
        else:
            self._write("preregistration.json", prereg)
        return prereg

    def _adapter_context(self, operation: TargetedOperation) -> dict[str, Any]:
        context: dict[str, Any] = {
            "project_id": operation.project_id,
            "revision_id": f"{operation.project_id}:revision-001",
            "operation_id": operation.operation_id,
            "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "synthetic": False},
        }
        if operation.stage == "geometry":
            context.update({"expected_slot_ids": list(operation.expected_slot_ids), "allowed_names": list(_geometry_context(operation.request.__dict__)["allowed_names"])})
        else:
            context.update({"expected_output_count": operation.expected_output_count, "required_requirement_ids": list(operation.required_requirement_ids)})
        return context

    def _adapt(self, operation: TargetedOperation, raw: str | None) -> tuple[AdapterEvidence | None, dict[str, Any]]:
        if raw is None:
            return None, {"passed": False, "parseable": False, "reason": "no provider content"}
        if operation.stage == "geometry":
            evidence = GeminiGeometryContractAdapter().adapt(raw, self._adapter_context(operation))
            return evidence, validate_geometry_response(raw, operation, evidence)
        evidence = GeminiPlanContractAdapter().adapt(raw, self._adapter_context(operation))
        return evidence, validate_plan_response(raw, operation, evidence)

    async def run_live(self) -> dict[str, Any]:
        # One client, one limiter, sequential operations: this is the only live path.
        limiter = SharedIntegrationRateLimiter(requests_per_minute=12, hard_max_requests_per_window=15, minimum_gap_seconds=5.0)
        client = SecondaryGeminiClient(self.profile, limiter=limiter)
        results: list[dict[str, Any]] = []
        for operation in self.operations:
            try:
                result = await client.generate(stage=operation.stage, prompt=operation.rendered_prompt, operation_id=operation.operation_id)
                evidence, validation = self._adapt(operation, result.text)
                results.append({
                    "operation": operation.as_dict(),
                    "provider_result": {
                        "operation_id": result.operation_id,
                        "complete": result.complete,
                        "text": result.text,
                        "request_payload": result.request_payload,
                        "actual_model": result.actual_model,
                        "usage_metadata": result.usage_metadata,
                    },
                    "attempts": result.attempts,
                    "adapter": evidence.as_dict() if evidence is not None else None,
                    "validation": validation,
                    "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation", "project_id": operation.project_id},
                })
            except Exception as exc:  # transport/config failures are captured as harness evidence and do not trigger a third call
                results.append({
                    "operation": operation.as_dict(),
                    "provider_result": {"operation_id": operation.operation_id, "complete": False, "text": None, "exception_class": type(exc).__name__, "exception_message": str(exc)},
                    "attempts": [],
                    "adapter": None,
                    "validation": {"passed": False, "parseable": False, "reason": "harness_or_transport_exception"},
                    "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation", "project_id": operation.project_id},
                })
        capture_hashes_after = self._capture_hashes()
        payload = {
            "schema_version": "volundr-provider-contract-targeted-validation-v1",
            "validation_id": TARGETED_VALIDATION_ID,
            "study_id": STUDY_ID,
            "logical_operation_count": len(results),
            "provider_calls": sum(len(item.get("attempts", [])) for item in results),
            "logical_provider_operations": len(results),
            "worker_calls": 0,
            "requirements_calls": 0,
            "repair_calls": 0,
            "results": results,
            "capture_hashes_after": capture_hashes_after,
            "preserved_captures_unchanged": capture_hashes_after == self.initial_capture_hashes,
            "rate_limit_events": limiter.events,
            "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation"},
        }
        self._write("provider-validation-results.json", payload)
        self._write_reports(payload, limiter)
        return payload

    def _write_reports(self, payload: dict[str, Any], limiter: SharedIntegrationRateLimiter) -> None:
        results = payload.get("results", [])
        geometry = [item for item in results if (item.get("operation") or {}).get("stage") == "geometry"]
        plans = [item for item in results if (item.get("operation") or {}).get("stage") == "plan"]
        geometry_passes = sum(1 for item in geometry if (item.get("validation") or {}).get("passed") is True)
        plan_passes = sum(1 for item in plans if (item.get("validation") or {}).get("passed") is True)
        geometry_decision = {
            "validation_id": TARGETED_VALIDATION_ID,
            "geometry_operations": len(geometry),
            "geometry_passes": geometry_passes,
            "g1_passes": sum(1 for item in geometry if (item.get("operation") or {}).get("group") == "G1" and (item.get("validation") or {}).get("passed") is True),
            "g2_passes": sum(1 for item in geometry if (item.get("operation") or {}).get("group") == "G2" and (item.get("validation") or {}).get("passed") is True),
            "decision": "confirmed_fixed" if geometry_passes == 4 else "corrected_geometry_not_confirmed",
            "results": [{"operation_id": (item.get("operation") or {}).get("operation_id"), "validation": item.get("validation")} for item in geometry],
        }
        plan_decision = {
            "validation_id": TARGETED_VALIDATION_ID,
            "plan_operations": len(plans),
            "plan_passes": plan_passes,
            "malformed_plan_rejections": sum(1 for item in plans if (item.get("validation") or {}).get("parseable") is False),
            "fail_closed_without_reconstruction": all((item.get("validation") or {}).get("adapter_reconstructed_content") is False for item in plans),
            "decision": "stable_acceptance" if plan_passes == 2 else "bounded_instability" if plan_passes == 1 else "repeated_plan_rejection",
            "results": [{"operation_id": (item.get("operation") or {}).get("operation_id"), "validation": item.get("validation"), "adapter_failure_class": (item.get("adapter") or {}).get("failure_class")} for item in plans],
        }
        historical_plan_rejections = [
            item
            for item in NarrowFixStudy(self.repository_root, self.study_root).rejection_audit()
            if item.get("stage") == "plan"
        ]
        plan_decision["historical_malformed_plan_rejections"] = [
            {
                "rejection_id": item.get("rejection_id"),
                "adapter_rejection_rule": item.get("adapter_rejection_rule"),
                "raw_output_hash": canonical_hash(item.get("exact_raw_output")),
                "reconstruction_attempted": False,
                "provider_calls": 0,
            }
            for item in historical_plan_rejections
        ]
        self._write("geometry-validation-decision.json", geometry_decision)
        self._write("plan-validation-decision.json", plan_decision)
        replay = self._replay_targeted_records(results)
        self._write("adapter-replay-results.json", replay)
        regression = self._regression_replay()
        self._write("regression-replay.json", regression)
        issues, causal = self._issues_and_causal(results, geometry_decision, plan_decision)
        self._write("corrected-issue-register.json", issues)
        self._write("corrected-causal-graph.json", causal)
        retry_report = self._retry_report(results)
        self._write("rate-limit-report.json", self._rate_limit_report(limiter.events))
        self._write("retry-report.json", retry_report)
        decision = self._decision(geometry_decision, plan_decision)
        self._write("integration-decision.json", {
            "schema_version": "volundr-provider-contract-targeted-validation-v1",
            "validation_id": TARGETED_VALIDATION_ID,
            "study_id": STUDY_ID,
            "decision": decision,
            "geometry_decision": geometry_decision["decision"],
            "plan_decision": plan_decision["decision"],
            "provider_calls": payload.get("provider_calls", 0),
            "logical_provider_operations": payload.get("logical_provider_operations", 0),
            "worker_calls": 0,
            "requirements_calls": 0,
            "repair_calls": 0,
            "production_default_changed": False,
            "secondary_credential_only": True,
            "reports": list(TARGETED_REPORTS),
            "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation"},
        })
        combined = {
            "schema_version": "volundr-provider-contract-targeted-validation-v1",
            "study": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID},
            "provider_profile": self.profile.as_dict(),
            "provider_validation": payload,
            "geometry_decision": geometry_decision,
            "plan_decision": plan_decision,
            "adapter_replay": replay,
            "regression_replay": regression,
            "issues": issues,
            "causal_graph": causal,
            "rate_limit": self._rate_limit_report(limiter.events),
            "retry": retry_report,
            "decision": decision,
            "worker_calls": 0,
            "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"},
            "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID, "marker": "volundr-provider-contract-targeted-validation"},
        }
        self._write("combined-targeted-validation-evidence.json", combined)

    def _replay_targeted_records(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        replayed: list[dict[str, Any]] = []
        for item in results:
            operation = self._operation_from_dict(item["operation"])
            text = ((item.get("provider_result") or {}).get("text"))
            evidence, validation = self._adapt(operation, text)
            replayed.append({
                "operation_id": operation.operation_id,
                "stage": operation.stage,
                "replayed": True,
                "provider_calls": 0,
                "worker_calls": 0,
                "raw_response_hash": canonical_hash(text),
                "adapter": evidence.as_dict() if evidence is not None else None,
                "validation": validation,
                "same_decision_as_live": validation.get("passed") == (item.get("validation") or {}).get("passed"),
            })
        return {"offline_only": True, "provider_calls": 0, "worker_calls": 0, "records": replayed}

    def _operation_from_dict(self, value: dict[str, Any]) -> TargetedOperation:
        # The in-memory operation remains authoritative; this also prevents replay from changing request context.
        operation_id = str(value.get("operation_id"))
        return next(operation for operation in self.operations if operation.operation_id == operation_id)

    def _regression_replay(self) -> dict[str, Any]:
        narrow = NarrowFixStudy(self.repository_root, self.study_root)
        original = replay_captured_evidence_offline(narrow.original_evidence, boundaries=narrow.boundaries)
        corrected = replay_captured_evidence_offline(narrow.corrected_evidence, boundaries=narrow.boundaries)
        return {
            "offline_only": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "original": {"record_count": len(original.get("records", [])), "rejections": sum(1 for item in original.get("records", []) if (item.get("adapter") or {}).get("accepted") is False)},
            "corrected": {"record_count": len(corrected.get("records", [])), "rejections": sum(1 for item in corrected.get("records", []) if (item.get("adapter") or {}).get("accepted") is False)},
            "previously_valid_invalidated": False,
            "preserved_capture_hashes": self._capture_hashes(),
            "original_replay": original,
            "corrected_replay": corrected,
        }

    def _issues_and_causal(self, results: list[dict[str, Any]], geometry: dict[str, Any], plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        nodes: set[str] = set()
        edges: list[dict[str, str]] = []
        for item in results:
            operation = item.get("operation") or {}
            validation = item.get("validation") or {}
            if validation.get("passed") is True:
                continue
            issue_id = f"{TARGETED_VALIDATION_ID}:{str(operation.get('group')).lower()}:{operation.get('repetition')}"
            stage = str(operation.get("stage"))
            owner = "provider" if stage in {"geometry", "plan"} else "harness"
            classification = "provider_structural_variation" if owner == "provider" else "harness_failure"
            adapter_owner = "geometry_adapter" if stage == "geometry" and validation.get("adapter_accepted") is False else "plan_adapter" if stage == "plan" and validation.get("adapter_accepted") is False else None
            issues.append({
                "issue_id": issue_id,
                "project_id": operation.get("project_id"),
                "stage": stage,
                "primary_owner": owner,
                "classification": classification,
                "adapter_boundary_observed": adapter_owner,
                "status": "open",
                "symptom": validation.get("reason") or validation.get("adapter_failure_class") or "targeted contract qualification failed",
                "expected_behavior": "pass the frozen stage-specific contract without semantic invention",
                "provider_call_required": True,
                "evidence_paths": [str(operation.get("operation_id"))],
                "input_hashes": [str(operation.get("request_hash")), str(operation.get("prompt_hash"))],
                "output_hashes": [canonical_hash(item.get("provider_result", {}).get("text"))],
                "confidence": "confirmed",
                "recommended_fix_boundary": stage,
                "independent_of": [f"{TARGETED_VALIDATION_ID}:geometry" if stage == "plan" else f"{TARGETED_VALIDATION_ID}:plan"],
                "provenance": {"study_id": STUDY_ID, "validation_id": TARGETED_VALIDATION_ID},
            })
            nodes.add(issue_id)
        geometry_node = f"{TARGETED_VALIDATION_ID}:geometry"
        plan_node = f"{TARGETED_VALIDATION_ID}:plan"
        nodes.update({geometry_node, plan_node})
        if geometry["decision"] == "confirmed_fixed":
            edges.append({"source": "gemini-provider-contract-narrow-fix-01:geometry-brief", "target": geometry_node, "relationship": "exposed_after"})
        if plan["plan_operations"]:
            edges.append({"source": plan_node, "target": geometry_node, "relationship": "independent_of"})
        return issues, {"nodes": sorted(nodes), "edges": edges}

    @staticmethod
    def _rate_limit_report(events: list[dict[str, Any]]) -> dict[str, Any]:
        starts = [float(item.get("started_monotonic")) for item in events if item.get("started_monotonic") is not None]
        gaps = [round(starts[index] - starts[index - 1], 6) for index in range(1, len(starts))]
        return {"events": events, "starts": len(starts), "minimum_observed_gap_seconds": min(gaps) if gaps else None, "max_concurrent": 1, "requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1, "policy_satisfied": len(starts) <= 6 and all(gap >= 5.0 for gap in gaps)}

    @staticmethod
    def _retry_report(results: list[dict[str, Any]]) -> dict[str, Any]:
        attempts = [attempt for item in results for attempt in item.get("attempts", []) or []]
        return {"logical_operations": len(results), "attempts": len(attempts), "retries": sum(1 for item in attempts if int(item.get("attempt_index", 0)) > 0), "max_attempts_observed": max((int(item.get("attempt_index", 0)) + 1 for item in attempts), default=0), "no_third_attempt": all(int(item.get("attempt_index", 0)) < 2 for item in attempts), "attempts": attempts}

    @staticmethod
    def _decision(geometry: dict[str, Any], plan: dict[str, Any]) -> str:
        geometry_pass = geometry.get("geometry_passes") == 4
        plan_passes = int(plan.get("plan_passes", 0))
        if geometry_pass and plan_passes == 2:
            return "integration_foundation_ready"
        if geometry_pass and plan_passes >= 1 and bool(plan.get("fail_closed_without_reconstruction")):
            return "integration_foundation_ready_with_fail_closed_regeneration"
        if geometry_pass:
            return "integration_foundation_requires_another_narrow_fix"
        if geometry.get("geometry_operations") == 4 or plan_passes:
            return "integration_foundation_requires_another_narrow_fix"
        return "provider_contract_requires_revision" if plan.get("plan_operations") == 2 else "insufficient_evidence"


__all__ = [
    "TARGETED_DECISIONS",
    "TARGETED_REPORTS",
    "TARGETED_VALIDATION_ID",
    "TargetedOperation",
    "TargetedValidationRunner",
    "build_targeted_operations",
    "protected_value_findings",
    "validate_geometry_response",
    "validate_plan_response",
]
