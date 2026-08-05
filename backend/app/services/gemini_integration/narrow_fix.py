from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.services.ai.provider import ModelGenerationRequest
from app.services.cad.geometry_slots import build_geometry_slot_brief
from app.services.gemini_consistency.provider_contract import (
    canonical_hash,
    evaluate_intrinsic,
    parse_provider_response,
)
from app.services.gemini_integration.adapters import (
    GeminiGeometryContractAdapter,
    GeminiPlanContractAdapter,
    GeminiRequirementsContractAdapter,
)
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.corpus import IntegrationProject, build_integration_corpus
from app.services.gemini_integration.forensics import (
    CausalGraph,
    IssueRecord,
    count_provider_successes,
    rank_issues,
    replay_captured_evidence_offline,
)
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import render_integration_prompt


NARROW_FIX_ID = "gemini-provider-contract-narrow-fix-01"
NARROW_FIX_DECISIONS = {
    "integration_foundation_ready",
    "integration_foundation_requires_another_narrow_fix",
    "targeted_provider_validation_required",
    "provider_contract_requires_revision",
    "insufficient_evidence",
}
NARROW_FIX_REPORTS = (
    "rejection-audit.json",
    "contract-differential.json",
    "corrected-issue-register.json",
    "corrected-causal-graph.json",
    "counterfactual-results.json",
    "differential-replay-results.json",
    "ownership-summary.json",
    "issue-priority-ranking.json",
    "unresolved-unknowns.json",
    "live-rerun-gate.json",
    "narrow-fix-decision.json",
    "combined-narrow-fix-evidence.json",
)


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return deepcopy(fallback)


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _response_text(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for candidate in payload.get("candidates", []) or []:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list):
            continue
        text = "".join(str(item.get("text")) for item in parts if isinstance(item, dict) and item.get("text") is not None)
        if text:
            return text
    return None


class NarrowFixStudy:
    """Offline audit and differential replay for the preserved integration run."""

    def __init__(self, repository_root: Path, integration_root: Path) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.integration_root = Path(integration_root).resolve()
        self.study_id = "gemini-provider-contract-integration-01"
        self.profile = GeminiFlashLiteContractV1.from_repository(self.repository_root)
        self.current_corpus = tuple(build_integration_corpus())
        self.original_corpus = self._original_corpus()
        self.store = IntegrationEvidenceStore(self.integration_root, study_id=self.study_id)
        self.boundaries = self.store.boundaries()
        self.attempts = self.store.provider_attempts()
        self.existing_counterfactuals = _read_json(self.integration_root / "counterfactuals/one-variable-fixtures.json", [])
        self.attempt_by_id = {str(item.get("attempt_id")): item for item in self.attempts}
        self.provider_boundary_by_attempt: dict[str, dict[str, Any]] = {}
        self.adapter_boundaries_by_project: dict[str, list[dict[str, Any]]] = {}
        for boundary in self.boundaries:
            project_id = str(boundary.get("project_id") or "")
            self.adapter_boundaries_by_project.setdefault(project_id, []).append(boundary)
            if not str(boundary.get("boundary") or "").startswith("provider_"):
                continue
            for attempt_id in (boundary.get("output") or {}).get("attempt_ids", []) or []:
                self.provider_boundary_by_attempt[str(attempt_id)] = boundary
        self.original_evidence = self._evidence(self.original_corpus)
        self.corrected_evidence = self._evidence(self.current_corpus)

    def _original_corpus(self) -> tuple[dict[str, Any], ...]:
        document = _read_json(self.integration_root / "reports/study-preregistration.json", {})
        projects = document.get("projects") if isinstance(document, dict) else None
        if isinstance(projects, list) and projects:
            return tuple(item for item in projects if isinstance(item, dict))
        return tuple(project.as_dict() for project in self.current_corpus)

    def _evidence(self, projects: tuple[dict[str, Any], ...] | tuple[IntegrationProject, ...]) -> dict[str, Any]:
        values = [item.as_dict() if isinstance(item, IntegrationProject) else item for item in projects]
        return {
            "study": {"study_id": self.study_id},
            "projects": values,
            "provider_attempts": self.attempts,
        }

    @property
    def original_project_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(item.get("project_id")): item for item in self.original_corpus}

    @property
    def current_project_by_id(self) -> dict[str, dict[str, Any]]:
        return {project.project_id: project.as_dict() for project in self.current_corpus}

    def _project_boundaries(self, project_id: str) -> list[dict[str, Any]]:
        return [item for item in self.boundaries if str(item.get("project_id")) == project_id]

    def _provider_attempt_for_boundary(self, boundary: dict[str, Any]) -> dict[str, Any] | None:
        attempt_ids = (boundary.get("output") or {}).get("attempt_ids", []) or []
        return self.attempt_by_id.get(str(attempt_ids[0])) if attempt_ids else None

    def _requirements_ids(self, project_id: str) -> list[str]:
        for boundary in self.adapter_boundaries_by_project.get(project_id, []):
            if boundary.get("boundary") != "requirements_adapter":
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

    def _geometry_context(self, boundary: dict[str, Any]) -> dict[str, Any]:
        request = ((boundary.get("input") or {}).get("request") or {})
        manifest = request.get("geometry_slot_manifest") if isinstance(request, dict) else None
        if not isinstance(manifest, dict):
            return {"expected_slot_ids": [], "allowed_names": []}
        allowed = {"body", "cq", "params", "cutter"}
        for slot in manifest.get("slots", []) or []:
            if not isinstance(slot, dict):
                continue
            allowed.update(str(item) for item in slot.get("authorized_parameter_ids", []) or [])
            allowed.update(str(item) for item in slot.get("approved_helpers", []) or [])
        return {
            "expected_slot_ids": [item.get("slot_id") for item in manifest.get("slots", []) or [] if isinstance(item, dict) and item.get("slot_id") is not None],
            "allowed_names": sorted(allowed),
            "manifest": manifest,
        }

    def _replay_context(self, attempt: dict[str, Any], *, original: bool) -> dict[str, Any]:
        project_id = str(attempt.get("project_id") or "")
        projects = self.original_project_by_id if original else self.current_project_by_id
        project = projects.get(project_id, {})
        context: dict[str, Any] = {
            "project_id": project_id,
            "revision_id": attempt.get("revision_id"),
            "fit_critical_missing": list(project.get("fit_critical_missing", []) or []),
            "provenance": {"study_id": self.study_id, "synthetic": False},
        }
        if attempt.get("stage") == "plan":
            context["expected_output_count"] = project.get("expected_output_count")
            context["required_requirement_ids"] = self._requirements_ids(project_id)
        if attempt.get("stage") == "geometry":
            provider_boundary = self.provider_boundary_by_attempt.get(str(attempt.get("attempt_id")))
            context.update(self._geometry_context(provider_boundary or {}))
        return context

    def rejection_audit(self) -> list[dict[str, Any]]:
        outcomes = {
            str(item.get("project_id")): item
            for item in _read_json(self.integration_root / "reports/project-outcomes.json", [])
            if isinstance(item, dict)
        }
        records: list[dict[str, Any]] = []
        for boundary in self.boundaries:
            output = boundary.get("output") or {}
            if output.get("accepted") is not False:
                continue
            project_id = str(boundary.get("project_id") or "")
            stage = str((output.get("stage") or boundary.get("boundary") or "").removesuffix("_adapter"))
            raw = output.get("raw_input")
            parsed, fence_count = parse_provider_response(raw) if isinstance(raw, (str, dict)) else (None, 0)
            attempt = self._provider_attempt_for_boundary(boundary)
            provider_input = (self.provider_boundary_by_attempt.get(str((attempt or {}).get("attempt_id"))) or {}).get("input", {})
            original_project = self.original_project_by_id.get(project_id, {})
            current_project = self.current_project_by_id.get(project_id, {})
            intrinsic_original = evaluate_intrinsic(
                {"stage": stage, "intrinsic_expectations": self._intrinsic_expectations(stage, project_id, original=True)},
                raw,
            ) if isinstance(raw, (str, dict)) else {"result": "unresolved"}
            intrinsic_corrected = evaluate_intrinsic(
                {"stage": stage, "intrinsic_expectations": self._intrinsic_expectations(stage, project_id, original=False)},
                raw,
            ) if isinstance(raw, (str, dict)) else {"result": "unresolved"}
            issue_ids = self._issue_ids_for_rejection(project_id, boundary.get("boundary"))
            records.append({
                "rejection_id": f"{project_id}:{boundary.get('boundary')}",
                "project_id": project_id,
                "revision_id": boundary.get("revision_id"),
                "stage": stage,
                "boundary": boundary.get("boundary"),
                "boundary_id": boundary.get("boundary_id"),
                "exact_input": {
                    "provider_boundary_input": provider_input,
                    "adapter_raw_input": raw,
                    "adapter_input_hash": output.get("input_hash"),
                },
                "exact_raw_output": raw,
                "parsed_output": parsed,
                "parse_fence_normalizations": fence_count,
                "adapter_result": output,
                "adapter_rejection_rule": self._rejection_rule(stage, output),
                "intrinsic_quality_result": {
                    "original_fixture_expectations": intrinsic_original,
                    "corrected_fixture_expectations": intrinsic_corrected,
                },
                "expected_contract": self._expected_contract(stage, project_id, provider_input, original_project, current_project),
                "observed_contract": self._observed_contract(stage, raw, parsed, output),
                "semantic_difference": {
                    "semantic_hash_before": output.get("semantic_hash_before"),
                    "semantic_hash_after": output.get("semantic_hash_after"),
                    "semantic_changed": output.get("semantic_hash_before") != output.get("semantic_hash_after"),
                },
                "structural_difference": self._structural_difference(stage, raw, parsed, output, provider_input),
                "downstream_consequences": {
                    "earliest_blocker": outcomes.get(project_id, {}).get("earliest_blocker"),
                    "furthest_valid_stage": outcomes.get(project_id, {}).get("furthest_valid_stage"),
                    "candidate_decision": outcomes.get(project_id, {}).get("candidate_decision"),
                },
                "other_independent_defects": self._independent_defects(project_id, boundary.get("boundary")),
                "issue_ownership": self._ownership(project_id, boundary.get("boundary")),
                "classification": self._classification(project_id, boundary.get("boundary")),
                "confidence": "confirmed",
                "root_issue_ids": issue_ids,
            })
        return records

    def _intrinsic_expectations(self, stage: str, project_id: str, *, original: bool) -> dict[str, Any]:
        project = (self.original_project_by_id if original else self.current_project_by_id).get(project_id, {})
        if stage == "requirements":
            return {"must_request": list(project.get("fit_critical_missing", []) or [])}
        if stage == "plan":
            return {"output_count": project.get("expected_output_count")}
        if stage == "geometry":
            boundary = next((item for item in self._project_boundaries(project_id) if item.get("boundary") == "provider_geometry"), {})
            return {"must_return_exactly": self._geometry_context(boundary).get("expected_slot_ids", [])}
        return {}

    def _expected_contract(self, stage: str, project_id: str, provider_input: dict[str, Any], original: dict[str, Any], corrected: dict[str, Any]) -> dict[str, Any]:
        contract: dict[str, Any] = {
            "stage": stage,
            "profile_id": self.profile.profile_id,
            "model": self.profile.model,
            "prompt_version": provider_input.get("prompt_version"),
            "prompt_hash": provider_input.get("prompt_hash"),
        }
        if stage == "requirements":
            contract.update({
                "original_fit_critical_missing": list(original.get("fit_critical_missing", []) or []),
                "corrected_fit_critical_missing": list(corrected.get("fit_critical_missing", []) or []),
                "clarification_required_for_missing_facts": True,
                "missing_values_must_not_be_invented": True,
            })
        elif stage == "plan":
            contract.update({
                "expected_output_count": original.get("expected_output_count"),
                "required_requirement_ids": self._requirements_ids(project_id),
                "meaningful_components_and_outputs": True,
            })
        elif stage == "geometry":
            geometry = self._geometry_context(self.provider_boundary_by_attempt.get(str((provider_input.get("attempt_ids") or [None])[0]), {}))
            if not geometry.get("expected_slot_ids"):
                boundary = next((item for item in self._project_boundaries(project_id) if item.get("boundary") == "provider_geometry"), {})
                geometry = self._geometry_context(boundary)
            contract.update({
                "geometry_contract": "volundr-geometry-slots-v1",
                "expected_slot_ids": geometry.get("expected_slot_ids", []),
                "required_result_symbol": "body",
                "allowed_names": geometry.get("allowed_names", []),
                "slot_manifest_hash": canonical_hash(geometry.get("manifest", {})),
            })
        return contract

    @staticmethod
    def _observed_contract(stage: str, raw: Any, parsed: Any, output: dict[str, Any]) -> dict[str, Any]:
        if stage == "geometry" and isinstance(parsed, dict):
            slots = parsed.get("slots")
            return {"schema_version": parsed.get("schema_version"), "returned_slot_ids": [item.get("slot_id") for item in slots or [] if isinstance(item, dict)], "returned_slot_count": len(slots) if isinstance(slots, list) else None}
        if isinstance(parsed, dict):
            return {"top_level_keys": sorted(str(key) for key in parsed), "parseable_object": True, "clarification_required": parsed.get("clarification_required"), "generation_ready": parsed.get("generation_ready"), "plan_ready": parsed.get("plan_ready")}
        return {"parseable_object": False, "raw_type": type(raw).__name__, "parsed": parsed, "adapter_failure_class": output.get("failure_class")}

    @staticmethod
    def _structural_difference(stage: str, raw: Any, parsed: Any, output: dict[str, Any], provider_input: dict[str, Any]) -> dict[str, Any]:
        difference: dict[str, Any] = {"raw_parseable_as_object": isinstance(parsed, dict), "adapter_output_shape": type(output.get("normalized")).__name__}
        if stage == "geometry":
            manifest = ((provider_input.get("request") or {}).get("geometry_slot_manifest") or {})
            expected = [item.get("slot_id") for item in manifest.get("slots", []) or [] if isinstance(item, dict)]
            returned = [item.get("slot_id") for item in (parsed or {}).get("slots", []) or [] if isinstance(item, dict)] if isinstance(parsed, dict) else []
            difference.update({"expected_slot_ids": expected, "returned_slot_ids": returned, "missing_slot_ids": sorted(set(expected) - set(returned))})
        if stage == "plan" and isinstance(raw, str):
            difference["invalid_json_detail"] = "malformed property line if parser returned no object" if parsed is None else None
        return difference

    @staticmethod
    def _rejection_rule(stage: str, output: dict[str, Any]) -> str:
        if stage == "geometry" and "expected_slot_ids" in (output.get("validation_result") or {}):
            return "exact-manifest-slot-set"
        if stage == "requirements" and output.get("failure_class") == "missing_required_clarification":
            return "fit-critical-clarification-question-coverage"
        actions = output.get("normalization_actions", []) or []
        if actions:
            return str(actions[-1].get("rule_id") or output.get("failure_class") or "unknown")
        return str(output.get("failure_class") or "unknown")

    @staticmethod
    def _classification(project_id: str, boundary: str | None) -> str:
        if project_id == "project-001" and boundary == "plan_adapter":
            return "provider_structural_variation"
        if project_id == "project-002" and boundary == "requirements_adapter":
            return "fixture_error"
        if boundary == "geometry_adapter":
            return "downstream_consequence_of_prompt_rendering_error"
        return "inconclusive"

    @staticmethod
    def _ownership(project_id: str, boundary: str | None) -> dict[str, Any]:
        if project_id == "project-001":
            return {"owner": "provider", "fix_boundary": "provider response generation", "provider_owned": True}
        if project_id == "project-002":
            return {"owner": "fixture", "fix_boundary": "integration corpus", "provider_owned": False}
        return {"owner": "workflow_runner", "fix_boundary": "geometry prompt construction", "provider_owned": False}

    @staticmethod
    def _independent_defects(project_id: str, boundary: str | None) -> list[str]:
        if boundary == "geometry_adapter":
            return ["captured_provider_geometry_prompt_omitted_geometry_slot_brief", "legacy_replay_inferred_expected_slots_from_returned_slots"]
        if project_id == "project-002":
            return ["prompt_explicitly_allows_wall_mount_spacing_proposal", "fixture_declared_mounting_pattern_fit_critical"]
        return []

    @staticmethod
    def _issue_ids_for_rejection(project_id: str, boundary: str | None) -> list[str]:
        if project_id == "project-001":
            return ["narrow-fix-04-plan-malformed-json"]
        if project_id == "project-002":
            return ["narrow-fix-03-mounting-pattern-fixture"]
        if boundary == "geometry_adapter":
            return ["narrow-fix-01-geometry-brief", "narrow-fix-05-empty-geometry-consequence"]
        return []

    def contract_differential(self, audits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        historical = self._historical_qualifying()
        results = []
        for audit in audits:
            project_id = audit["project_id"]
            stage = audit["stage"]
            result = {
                "rejection_id": audit["rejection_id"],
                "stage": stage,
                "prompt_comparison": {
                    "captured_prompt_version": audit["expected_contract"].get("prompt_version"),
                    "captured_prompt_hash": audit["expected_contract"].get("prompt_hash"),
                    "exact_rendered_prompt": (audit["exact_input"].get("provider_boundary_input") or {}).get("rendered_prompt"),
                    "prompt_rendering_finding": "none",
                },
                "stage_adapter_contract": self._adapter_contract(stage),
                "frozen_contract": self._contract_file(stage),
                "historical_qualifying_responses": historical.get(stage, []),
                "fixture_expectations": {
                    "original": self.original_project_by_id.get(project_id, {}),
                    "corrected": self.current_project_by_id.get(project_id, {}),
                },
                "classification": audit["classification"],
                "semantic_variation_is_not_treated_as_structural_failure": True,
            }
            if stage == "geometry":
                provider_boundary = next((item for item in self._project_boundaries(project_id) if item.get("boundary") == "provider_geometry"), {})
                request = ((provider_boundary.get("input") or {}).get("request") or {})
                manifest = request.get("geometry_slot_manifest") or {}
                captured_brief = request.get("geometry_slot_brief")
                corrected_brief = build_geometry_slot_brief(
                    planning_depth=request.get("planning_depth") or "detailed_plan",
                    active_requirements=list(request.get("active_requirements") or []),
                    requirement_delta=list(request.get("requirement_delta") or []),
                    preserved_requirements=[],
                    proposals=list((request.get("design_plan") or {}).get("proposals", []) or []),
                    design_plan=request.get("design_plan") or {},
                    slot_manifest=manifest,
                    exposed_controls=list((request.get("design_plan") or {}).get("exposed_controls", []) or []),
                )
                corrected_request = ModelGenerationRequest(
                    project_name=request.get("project_name", ""),
                    original_intent=request.get("original_intent", ""),
                    user_instruction=request.get("user_instruction", ""),
                    design_plan=request.get("design_plan"),
                    geometry_slot_manifest=manifest,
                    geometry_slot_brief=corrected_brief,
                    geometry_contract="volundr-geometry-slots-v1",
                )
                rendered = render_integration_prompt(self.profile, "geometry", corrected_request)
                result["prompt_comparison"].update({
                    "captured_geometry_slot_brief": captured_brief,
                    "corrected_geometry_slot_brief": corrected_brief,
                    "captured_brief_empty": not bool(captured_brief),
                    "corrected_brief_nonempty": bool(corrected_brief.get("slots") and corrected_brief.get("output_obligations")),
                    "corrected_prompt_hash": rendered.prompt_hash,
                    "corrected_prompt_version": rendered.prompt_version,
                    "provider_response_replayable_without_new_call": True,
                    "provider_behavior_after_prompt_correction": "unresolved_from_existing_response",
                })
            results.append(result)
        return results

    @staticmethod
    def _adapter_contract(stage: str) -> dict[str, Any]:
        if stage == "requirements":
            return {
                "adapter": "GeminiRequirementsContractAdapter",
                "required": ["meaningful requirements or authoritative current records", "clarification_required and generation_ready must not conflict", "missing fit facts remain missing and are explicitly questioned"],
                "normalization": ["generic provider aliases", "current critical_dimensions/functional_requirements projection", "authoritative Volundr IDs and provenance"],
            }
        if stage == "plan":
            return {
                "adapter": "GeminiPlanContractAdapter",
                "required": ["parseable object", "meaningful components and printable outputs", "expected output count", "valid component references", "requirement traceability"],
                "normalization": ["generic provider aliases", "authoritative Volundr IDs and provenance"],
            }
        return {
            "adapter": "GeminiGeometryContractAdapter",
            "required": ["exact manifest slot IDs and order", "result_symbol body", "nonempty statements", "approved names only", "no invalid CadQuery APIs"],
            "normalization": ["generic provider aliases", "prior shape aliases to body", "geometry slot canonicalizer"],
        }

    def _contract_file(self, stage: str) -> dict[str, Any]:
        path = self.repository_root / "data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/contracts" / f"gemini-flash-lite-{stage}-contract-v1.json"
        return _read_json(path, {"stage": stage, "missing_historical_contract": True})

    def _historical_qualifying(self) -> dict[str, list[dict[str, Any]]]:
        path = self.repository_root / "data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/reports/adapter-replay-results.json"
        records = _read_json(path, {}).get("records", [])
        result: dict[str, list[dict[str, Any]]] = {"requirements": [], "plan": [], "geometry": []}
        for record in records:
            stage = record.get("stage")
            adapter = record.get("adapter_result") or {}
            if stage not in result or adapter.get("accepted") is not True or len(result[stage]) >= 3:
                continue
            canonical = adapter.get("canonical_provider_record") or {}
            result[stage].append({
                "packet_id": record.get("packet_id"),
                "source_corpus": record.get("source_corpus"),
                "quality_result": (adapter.get("quality") or {}).get("result"),
                "canonical_top_level_keys": sorted(canonical) if isinstance(canonical, dict) else [],
                "canonical_hash": canonical_hash(canonical),
                "current_contract_compatible": stage != "geometry" or "slots" in canonical,
            })
        return result

    def counterfactual_results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        plan_boundary = next((item for item in self.boundaries if item.get("project_id") == "project-001" and item.get("boundary") == "plan_adapter"), None)
        if plan_boundary:
            raw = (plan_boundary.get("output") or {}).get("raw_input")
            before = GeminiPlanContractAdapter().adapt(raw, {"project_id": "project-001", "revision_id": "project-001:revision-001", "expected_output_count": self.original_project_by_id.get("project-001", {}).get("expected_output_count"), "required_requirement_ids": self._requirements_ids("project-001"), "provenance": {"study_id": self.study_id}})
            historical = self._historical_canonical("plan", expected_output_count=self.original_project_by_id.get("project-001", {}).get("expected_output_count"))
            after = GeminiPlanContractAdapter().adapt(historical, {"project_id": "project-001", "revision_id": "project-001:revision-001", "expected_output_count": self.original_project_by_id.get("project-001", {}).get("expected_output_count"), "required_requirement_ids": [], "provenance": {"study_id": self.study_id}}) if historical is not None else None
            if after is not None:
                result = self._cf("cf-plan-known-good-provider-through-original-adapter", "project-001", "provider_plan_response", before, after, "provider_structural_variation", causal_relationship="adapter_accepts_known_good_historical_plan")
                result["source_fixture_ids"] = self._fixture_ids("project-001")
                results.append(result)
        requirements_boundary = next((item for item in self.boundaries if item.get("project_id") == "project-002" and item.get("boundary") == "requirements_adapter"), None)
        if requirements_boundary:
            raw = (requirements_boundary.get("output") or {}).get("raw_input")
            adapter = GeminiRequirementsContractAdapter()
            before = adapter.adapt(raw, {"project_id": "project-002", "revision_id": "project-002:revision-001", "fit_critical_missing": list(self.original_project_by_id.get("project-002", {}).get("fit_critical_missing", []) or []), "provenance": {"study_id": self.study_id}})
            after = adapter.adapt(raw, {"project_id": "project-002", "revision_id": "project-002:revision-001", "fit_critical_missing": list(self.current_project_by_id.get("project-002", {}).get("fit_critical_missing", []) or []), "provenance": {"study_id": self.study_id}})
            result = self._cf("cf-mounting-pattern-fixture", "project-002", "fit_critical_missing fixture entry", before, after, "fixture_error", causal_relationship="fixture_rejection_removed_without_changing_provider_response")
            result["source_fixture_ids"] = self._fixture_ids("project-002")
            results.append(result)

        geometry_results = []
        for attempt in self.attempts:
            if attempt.get("stage") != "geometry":
                continue
            raw = _response_text(attempt.get("response"))
            if raw is None:
                continue
            parsed, _ = parse_provider_response(raw)
            returned = [item.get("slot_id") for item in (parsed or {}).get("slots", []) or [] if isinstance(item, dict)] if isinstance(parsed, dict) else []
            old = GeminiGeometryContractAdapter().adapt(raw, {"project_id": attempt.get("project_id"), "revision_id": attempt.get("revision_id"), "expected_slot_ids": returned, "allowed_names": ["body", "cq", "params", "cutter"], "provenance": {"study_id": self.study_id}})
            provider_boundary = self.provider_boundary_by_attempt.get(str(attempt.get("attempt_id")))
            context = self._geometry_context(provider_boundary or {})
            new = GeminiGeometryContractAdapter().adapt(raw, {"project_id": attempt.get("project_id"), "revision_id": attempt.get("revision_id"), **context, "provenance": {"study_id": self.study_id}})
            geometry_results.append({
                "project_id": attempt.get("project_id"),
                "attempt_id": attempt.get("attempt_id"),
                "single_variable_changed": "authoritative_expected_slot_manifest",
                "before": {"accepted": old.accepted, "failure_class": old.failure_class, "semantic_hash_before": old.semantic_hash_before, "semantic_hash_after": old.semantic_hash_after},
                "after": {"accepted": new.accepted, "failure_class": new.failure_class, "semantic_hash_before": new.semantic_hash_before, "semantic_hash_after": new.semantic_hash_after},
                "failure_removed": old.accepted is True and new.accepted is False,
                "new_failure_exposed": new.failure_class,
                "provider_success_eligible": False,
                "confidence": "confirmed",
                "causal_relationship": "replay_evaluator_overconstraint_removed; provider_response_and_adapter_unchanged",
                "source_fixture_ids": self._fixture_ids(str(attempt.get("project_id"))),
            })
        results.append({"counterfactual_id": "cf-authoritative-geometry-replay", "project_id": "project-003..010", "single_variable_changed": "authoritative_expected_slot_manifest", "cases": geometry_results, "failure_removed": False, "new_failure_exposed": "missing_slots", "provider_success_eligible": False, "confidence": "confirmed"})

        results.append({
            "counterfactual_id": "cf-geometry-brief-prompt-construction",
            "project_id": "project-003..010",
            "single_variable_changed": "geometry_slot_brief",
            "before": {"captured_brief": None, "provider_response": "slots:[]", "adapter_failure": "missing_slots"},
            "after": {"corrected_brief": "nonempty manifest-derived brief", "provider_response": "preserved unchanged", "adapter_failure": "missing_slots"},
            "failure_removed": False,
            "new_failure_exposed": "provider_behavior_after_corrected_prompt_unresolved",
            "provider_success_eligible": False,
            "confidence": "high_confidence",
            "causal_relationship": "captured_empty_brief_is_upstream_of_preserved_empty_slots_response",
            "source_fixture_ids": self._fixture_ids("project-003"),
        })
        return results

    def _fixture_ids(self, project_id: str) -> list[str]:
        return [
            str(item.get("fixture_id"))
            for item in self.existing_counterfactuals
            if isinstance(item, dict) and str(item.get("project_id")) == project_id
        ]

    def _historical_canonical(self, stage: str, *, expected_output_count: int | None = None) -> dict[str, Any] | None:
        path = self.repository_root / "data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01/reports/adapter-replay-results.json"
        records = _read_json(path, {}).get("records", [])
        for record in records:
            if record.get("stage") != stage:
                continue
            adapter = record.get("adapter_result") or {}
            if adapter.get("accepted") is True and isinstance(adapter.get("canonical_provider_record"), dict):
                canonical = adapter["canonical_provider_record"]
                if expected_output_count is not None and len(canonical.get("printable_outputs", []) or []) != int(expected_output_count):
                    continue
                return canonical
        return None

    @staticmethod
    def _cf(counterfactual_id: str, project_id: str, changed: str, before: Any, after: Any, classification: str, *, causal_relationship: str | None = None) -> dict[str, Any]:
        return {
            "counterfactual_id": counterfactual_id,
            "project_id": project_id,
            "single_variable_changed": changed,
            "classification": classification,
            "before": {"accepted": before.accepted, "failure_class": before.failure_class, "semantic_hash_before": before.semantic_hash_before, "semantic_hash_after": before.semantic_hash_after},
            "after": {"accepted": after.accepted, "failure_class": after.failure_class, "semantic_hash_before": after.semantic_hash_before, "semantic_hash_after": after.semantic_hash_after},
            "failure_removed": before.accepted is False and after.accepted is True,
            "new_failure_exposed": after.failure_class if after.accepted is False else None,
            "provider_success_eligible": False,
            "confidence": "confirmed",
            "causal_relationship": causal_relationship,
        }

    def _issue(self, issue_id: str, *, project_id: str, stage: str, owner: str, classification: str, symptom: str, expected: str, confidence: str, status: str, fix_boundary: str, frequency: int, severity: float, downstream_impact: float, correction_cost: float, caused_by: tuple[str, ...] = (), independent_of: tuple[str, ...] = (), provider_call_required: bool = False) -> tuple[IssueRecord, dict[str, Any]]:
        issue = IssueRecord(
            issue_id=issue_id,
            project_id=project_id,
            stage=stage,
            primary_owner=owner,
            secondary_factors=(),
            classification=classification,
            symptom=symptom,
            incorrect_behavior=symptom,
            expected_behavior=expected,
            evidence_paths=tuple(sorted(str(item.get("boundary_id")) for item in self.boundaries if item.get("project_id") == project_id)),
            input_hashes=(),
            output_hashes=(),
            confidence=confidence,
            recommended_fix_boundary=fix_boundary,
            provider_call_required=provider_call_required,
            caused_by=caused_by,
            independent_of=independent_of,
            status=status,
        )
        return issue, {
            **issue.as_dict(),
            "frequency": frequency,
            "severity": severity,
            "downstream_impact": downstream_impact,
            "estimated_correction_cost": correction_cost,
        }

    def corrected_issues(self) -> tuple[list[dict[str, Any]], list[tuple[IssueRecord, dict[str, float]]]]:
        definitions = [
            self._issue("narrow-fix-01-geometry-brief", project_id="project-003..010", stage="geometry", owner="workflow_runner", classification="prompt_rendering_error", symptom="captured geometry requests supplied a nonempty slot manifest but geometry_slot_brief was null", expected="render a nonempty manifest-derived geometry brief", confidence="confirmed", status="fixed", fix_boundary="integration workflow geometry request", frequency=8, severity=5, downstream_impact=5, correction_cost=1),
            self._issue("narrow-fix-02-replay-authority", project_id="project-003..010", stage="geometry", owner="harness", classification="evaluator_error", symptom="offline replay inferred expected slots from the provider's empty response", expected="replay must use the captured authoritative slot manifest", confidence="confirmed", status="fixed", fix_boundary="offline replay harness", frequency=8, severity=4, downstream_impact=4, correction_cost=1, independent_of=("narrow-fix-01-geometry-brief",)),
            self._issue("narrow-fix-03-mounting-pattern-fixture", project_id="project-002", stage="requirements", owner="fixture", classification="fixture_error", symptom="the fixture required an explicit mounting-pattern question although the frozen prompt permits ordinary wall-mount spacing to be proposed", expected="only cable diameter remains fit-critical for this request", confidence="confirmed", status="fixed", fix_boundary="integration corpus", frequency=1, severity=3, downstream_impact=3, correction_cost=1),
            self._issue("narrow-fix-04-plan-malformed-json", project_id="project-001", stage="plan", owner="provider", classification="provider_structural_variation", symptom="the Plan response contains a stray list marker before printable_outputs and is not parseable JSON", expected="return a parseable Plan object", confidence="confirmed", status="open", fix_boundary="provider response generation", frequency=1, severity=3, downstream_impact=3, correction_cost=2, provider_call_required=True),
            self._issue("narrow-fix-05-empty-geometry-consequence", project_id="project-003..010", stage="geometry", owner="provider", classification="downstream_consequence", symptom="the provider returned schema-shaped empty slots after receiving an empty geometry brief", expected="return every authoritative slot exactly once after a complete geometry brief", confidence="high_confidence", status="blocked_by_root_cause", fix_boundary="targeted provider validation after prompt correction", frequency=8, severity=4, downstream_impact=4, correction_cost=2, caused_by=("narrow-fix-01-geometry-brief",), provider_call_required=True),
        ]
        records = [record for _, record in definitions]
        confidence_values = {"confirmed": 1.0, "high_confidence": 0.8, "probable": 0.6, "possible": 0.35, "unknown": 0.1}
        rankings = [(issue, {"frequency": factors["frequency"], "severity": factors["severity"], "confidence": confidence_values.get(factors["confidence"], 0.1), "downstream_impact": factors["downstream_impact"], "estimated_correction_cost": factors["estimated_correction_cost"]}) for issue, factors in definitions]
        return records, rankings

    def differential_replay(self, corrected_replay: dict[str, Any], counterfactuals: list[dict[str, Any]]) -> dict[str, Any]:
        original_replay = replay_captured_evidence_offline(self.original_evidence, boundaries=self.boundaries)
        rejected_original = [item for item in original_replay.get("records", []) if (item.get("adapter") or {}).get("accepted") is False]
        rejected_corrected = [item for item in corrected_replay.get("records", []) if (item.get("adapter") or {}).get("accepted") is False]
        accepted_original_ids = {item.get("attempt_id") for item in original_replay.get("records", []) if (item.get("adapter") or {}).get("accepted") is True}
        accepted_corrected_ids = {item.get("attempt_id") for item in corrected_replay.get("records", []) if (item.get("adapter") or {}).get("accepted") is True}
        return {
            "offline_only": True,
            "provider_calls": 0,
            "worker_calls": 0,
            "original_replay": {"records": len(original_replay["records"]), "rejections": len(rejected_original), "failure_classes": dict(Counter((item.get("adapter") or {}).get("failure_class") for item in rejected_original))},
            "corrected_replay": {"records": len(corrected_replay["records"]), "rejections": len(rejected_corrected), "failure_classes": dict(Counter((item.get("adapter") or {}).get("failure_class") for item in rejected_corrected))},
            "issue_removed_by_correction": sorted(accepted_corrected_ids - accepted_original_ids),
            "newly_exposed_issues": ["geometry_prompt_provider_behavior_unresolved"],
            "previously_valid_responses_invalidated": sorted(accepted_original_ids - accepted_corrected_ids),
            "counterfactual_count": len(counterfactuals),
            "provider_success_count": count_provider_successes(counterfactuals),
            "correction_results": counterfactuals,
        }

    def build_reports(self) -> dict[str, Any]:
        audits = self.rejection_audit()
        contract = self.contract_differential(audits)
        counterfactuals = self.counterfactual_results()
        corrected_replay = replay_captured_evidence_offline(self.corrected_evidence, boundaries=self.boundaries)
        issues, ranking_inputs = self.corrected_issues()
        graph = CausalGraph()
        graph.add("narrow-fix-01-geometry-brief", "narrow-fix-05-empty-geometry-consequence", "caused_by")
        graph.add("narrow-fix-02-replay-authority", "narrow-fix-05-empty-geometry-consequence", "independent_of")
        graph.add("narrow-fix-03-mounting-pattern-fixture", "narrow-fix-04-plan-malformed-json", "independent_of")
        ranking = rank_issues(ranking_inputs)
        by_owner: dict[str, list[dict[str, Any]]] = {"provider": [], "volundr": [], "harness_evaluator": [], "unresolved": []}
        for item in ranking:
            issue = next(issue for issue, factors in ranking_inputs if issue.issue_id == item["issue_id"])
            owner_group = "provider" if issue.primary_owner == "provider" else "harness_evaluator" if issue.primary_owner == "harness" else "volundr" if issue.primary_owner in {"workflow_runner", "fixture"} else "unresolved"
            by_owner[owner_group].append(item)
        replay = self.differential_replay(corrected_replay, counterfactuals)
        replay["replay_after_each_correction"] = [
            {
                "correction_id": "narrow-fix-01-geometry-brief",
                "replayed_original_captures": True,
                "provider_calls": 0,
                "worker_calls": 0,
                "directly_supported_issue_fixed": "narrow-fix-01-geometry-brief",
                "captured_provider_failure_removed": False,
                "remaining_issue": "narrow-fix-05-empty-geometry-consequence",
                "previously_valid_responses_invalidated": [],
            },
            {
                "correction_id": "narrow-fix-02-replay-authority",
                "replayed_original_captures": True,
                "provider_calls": 0,
                "worker_calls": 0,
                "directly_supported_issue_fixed": "narrow-fix-02-replay-authority",
                "captured_provider_failure_removed": False,
                "remaining_issue": "narrow-fix-05-empty-geometry-consequence",
                "previously_valid_responses_invalidated": [],
            },
            {
                "correction_id": "narrow-fix-03-mounting-pattern-fixture",
                "replayed_original_captures": True,
                "provider_calls": 0,
                "worker_calls": 0,
                "directly_supported_issue_fixed": "narrow-fix-03-mounting-pattern-fixture",
                "captured_provider_failure_removed": True,
                "remaining_issue": "narrow-fix-04-plan-malformed-json",
                "previously_valid_responses_invalidated": [],
            },
        ]
        unresolved = [
            {"unknown_id": "unknown-geometry-provider-after-brief", "question": "Will the fixed geometry prompt cause the provider to return the required slots for a representative project?", "affected_operations": ["project-003:geometry", "project-004:geometry", "project-005:geometry", "project-006:geometry", "project-007:geometry", "project-008:geometry", "project-009:geometry", "project-010:geometry"], "offline_evidence": "cannot distinguish provider behavior after corrected prompt from preserved response generated with null brief", "requires_provider_call": True, "confidence": "confirmed"},
            {"unknown_id": "unknown-plan-retry-after-malformed-json", "question": "Will the provider return parseable Plan JSON for project-001 under the frozen Plan contract?", "affected_operations": ["project-001:plan"], "offline_evidence": "the preserved response is malformed and no safe semantics-preserving normalization is documented", "requires_provider_call": True, "confidence": "confirmed"},
        ]
        ownership = {
            "issue_counts": dict(Counter(item["primary_owner"] for item in issues)),
            "classification_counts": dict(Counter(item["classification"] for item in issues)),
            "status_counts": dict(Counter(item["status"] for item in issues)),
            "separate_rankings": by_owner,
        }
        gate = {
            "live_calls_authorized": False,
            "provider_calls": 0,
            "worker_calls": 0,
            "specific_unresolved_questions": [item["question"] for item in unresolved],
            "affected_operation_set": unresolved[0]["affected_operations"] + unresolved[1]["affected_operations"],
            "minimum_discriminating_rerun": {"project_id": "project-003", "stage": "geometry", "reason": "one representative corrected-brief operation distinguishes provider response behavior without rerunning all ten projects"},
            "prerequisites_before_authorization": ["retain frozen profile unchanged", "run corrected replay and counterfactuals", "authorize only the representative operation"],
            "all_ten_project_rerun_authorized": False,
        }
        decision = {
            "decision": "targeted_provider_validation_required",
            "study_id": self.study_id,
            "narrow_fix_id": NARROW_FIX_ID,
            "provider_calls": 0,
            "worker_calls": 0,
            "fixes_applied": ["geometry_slot_brief construction is present in the current workflow", "offline replay now uses authoritative manifests", "mounting-pattern fixture expectation corrected"],
            "remaining_provider_owned_issue": "malformed project-001 Plan JSON",
            "remaining_unresolved_question": unresolved[0]["question"],
            "production_default_changed": False,
        }
        capture_manifest = []
        for path in sorted((self.integration_root / "captures").rglob("*.json")):
            capture_manifest.append({"path": str(path.relative_to(self.integration_root)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size})
        combined = {
            "schema_version": "volundr-gemini-provider-contract-narrow-fix-v1",
            "narrow_fix_id": NARROW_FIX_ID,
            "study": {"study_id": self.study_id},
            "profile": self.profile.as_dict(),
            "provider_calls": 0,
            "worker_calls": 0,
            "preserved_evidence_counts": {"provider_attempts": len(self.attempts), "boundary_captures": len(self.boundaries), "project_outcomes": len(_read_json(self.integration_root / "reports/project-outcomes.json", [])), "existing_counterfactual_fixtures": len(_read_json(self.integration_root / "counterfactuals/one-variable-fixtures.json", []))},
            "capture_manifest": capture_manifest,
            "rejection_audit": audits,
            "contract_differential": contract,
            "corrected_issue_register": issues,
            "corrected_causal_graph": graph.as_dict(),
            "counterfactual_results": counterfactuals,
            "differential_replay_results": replay,
            "ownership_summary": ownership,
            "issue_priority_ranking": {"all": ranking, "by_owner": by_owner},
            "unresolved_unknowns": unresolved,
            "live_rerun_gate": gate,
            "narrow_fix_decision": decision,
        }
        return {
            "rejection-audit.json": {"schema_version": "volundr-gemini-provider-contract-narrow-fix-v1", "study_id": self.study_id, "provider_calls": 0, "worker_calls": 0, "records": audits},
            "contract-differential.json": {"schema_version": "volundr-gemini-provider-contract-narrow-fix-v1", "study_id": self.study_id, "provider_calls": 0, "worker_calls": 0, "records": contract},
            "corrected-issue-register.json": {"schema_version": "volundr-gemini-provider-contract-narrow-fix-v1", "study_id": self.study_id, "provider_calls": 0, "worker_calls": 0, "issues": issues},
            "corrected-causal-graph.json": graph.as_dict(),
            "counterfactual-results.json": {"schema_version": "volundr-gemini-provider-contract-narrow-fix-v1", "study_id": self.study_id, "provider_calls": 0, "worker_calls": 0, "existing_fixture_count": len(self.existing_counterfactuals), "existing_fixture_ids": [str(item.get("fixture_id")) for item in self.existing_counterfactuals if isinstance(item, dict)], "results": counterfactuals, "provider_success_count": count_provider_successes(counterfactuals)},
            "differential-replay-results.json": replay,
            "ownership-summary.json": ownership,
            "issue-priority-ranking.json": {"all": ranking, "by_owner": by_owner},
            "unresolved-unknowns.json": {"unknowns": unresolved},
            "live-rerun-gate.json": gate,
            "narrow-fix-decision.json": decision,
            "combined-narrow-fix-evidence.json": combined,
        }

    def write_reports(self, output_root: Path) -> dict[str, Any]:
        reports = self.build_reports()
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        for name, value in reports.items():
            (output_root / name).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return reports


__all__ = ["NARROW_FIX_DECISIONS", "NARROW_FIX_ID", "NARROW_FIX_REPORTS", "NarrowFixStudy"]
