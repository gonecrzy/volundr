#!/usr/bin/env python3
"""Run the isolated Gemini provider-contract foundation study.

This script owns experiment evidence only.  It does not change production
provider routing, prompts, schemas, or adapter behavior.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from app.services.gemini_consistency.provider_contract import (
    GeminiProviderContractAdapter,
    QUALITY_PASS,
    QUALITY_RESULTS,
    canonicalization_distance,
    contract_entropy,
    decision_signature,
    evaluate_intrinsic,
    geometry_strategy_signature,
    identity_signature,
    parse_provider_response,
    semantic_signature,
    structural_signature,
)
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import DesignPlanRequest, ModelGenerationRequest, RequirementExtractionRequest
from app.services.workflow.redaction import RedactionService


STUDY_ID = "gemini-provider-contract-foundation-01"
MODEL = "gemini-3.5-flash-lite"
SECONDARY_ENV = "GEMINI_API_KEY_2"
SELECTION_PACKET_IDS = (
    "selection-requirements-fit",
    "selection-requirements-specified",
    "selection-plan-ordinary",
    "selection-plan-feature-rich",
    "selection-geometry-simple",
    "selection-geometry-multislot",
)
HOLDOUT_PACKET_IDS = tuple(f"holdout-{index:02d}" for index in range(1, 11))
SELECTION_STAGES = ("requirements", "requirements", "plan", "plan", "geometry", "geometry")
SOURCE_REPORTS = {
    "profile-ablation": (
        "corrected-quality-floor.json",
        "corrected-phase-1-decision.json",
        "corrected-semantic-scores.json",
        "buildability-scorecard.json",
        "phase-2-audited-decision.json",
        "phase-2-project-results.json",
        "all-responses-manual-review.json",
        "all-responses-manual-review-audited.json",
    ),
    "system-boundary": (
        "offline-processing-replay.json",
        "provider-processing-factorial-results.json",
        "provider-processing-factorial-comparison.json",
        "residual-model-defects.json",
        "final-system-boundary-decision.json",
        "all-methods-manual-review.json",
        "gemini-rate-limit-report.json",
    ),
}


def _json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return _sha256_bytes(encoded.encode("utf-8"))


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo_root), *args], text=True).strip()


def _migration_head(repo_root: Path) -> str:
    result = subprocess.run(
        [str(repo_root / "backend/.venv/bin/alembic"), "heads"],
        cwd=repo_root / "backend",
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _packet(packet_id: str, stage: str, title: str, prompt: str, facts: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": packet_id,
        "stage": stage,
        "title": title,
        "prompt": prompt,
        "frozen_facts": facts,
        "intrinsic_expectations": expectations,
    }


def selection_packets() -> list[dict[str, Any]]:
    return [
        _packet(
            SELECTION_PACKET_IDS[0],
            "requirements",
            "underspecified phone stand",
            "Design a freestanding phone stand with portrait and landscape viewing and centered charging access.",
            {"phone_fit": "missing", "desired_angle": "missing", "freestanding": True, "one_printed_part": True},
            {"must_request": ["phone width", "phone thickness with case"], "must_not_invent": ["phone width", "phone thickness", "fit clearance", "viewing angle"]},
        ),
        _packet(
            SELECTION_PACKET_IDS[1],
            "requirements",
            "fully specified phone stand",
            "Design a freestanding phone stand for a 78 mm wide and 12 mm thick phone including its case, at approximately 65 degrees, with a centered charging opening. Use one printed part and ordinary FDM plastic.",
            {"phone_width_mm": 78, "phone_thickness_with_case_mm": 12, "desired_angle_deg": 65, "freestanding": True, "one_printed_part": True, "charging_opening": "centered"},
            {"must_preserve": ["78 mm", "12 mm", "65 degrees", "centered charging opening", "one printed part"], "must_not_promote": ["proposal", "default"]},
        ),
        _packet(
            SELECTION_PACKET_IDS[2],
            "plan",
            "ordinary single-part organizer",
            "Create a single printable desktop organizer with three compartments, a front label recess, and rounded outer corners. Preserve the requested one-part output.",
            {"output_count": 1, "compartment_count": 3, "label_recess": True, "rounded_outer_corners": True},
            {"required_features": ["three compartments", "front label recess", "rounded outer corners"], "output_count": 1},
        ),
        _packet(
            SELECTION_PACKET_IDS[3],
            "plan",
            "feature-rich carrier",
            "Create one printable wall carrier with five vertical trays, a carrying handle, bottom drainage, two retention strap slots, and mostly open side walls.",
            {"output_count": 1, "tray_count": 5, "handle": True, "drainage": True, "strap_slot_count": 2, "open_side_walls": True, "loading": "vertical top"},
            {"required_features": ["five trays", "carrying handle", "bottom drainage", "two retention strap slots", "mostly open side walls"], "output_count": 1},
        ),
        _packet(
            SELECTION_PACKET_IDS[4],
            "geometry",
            "simple cut geometry",
            "Provide one geometry response for a rectangular plate with a centered circular through-hole. The supplied body is body and the slot must assign body as its result symbol.",
            {"slot_ids": ["1"], "body_symbol": "body", "operation": "centered circular through-hole", "result_symbol": "body"},
            {"slot_count": 1, "must_assign": "body", "must_cut": True, "must_not_add_slot": True},
        ),
        _packet(
            SELECTION_PACKET_IDS[5],
            "geometry",
            "multi-slot adapter geometry",
            "Provide four geometry slots for a rectangular-to-round adapter: rectangular-end flange, hollow transition, circular-end flange, and unobstructed internal hollowing. Return every slot exactly once and assign body as each result symbol.",
            {"slot_ids": ["1", "2", "3", "4"], "responsibilities": ["rectangular flange", "hollow transition", "circular flange", "internal hollowing"], "result_symbol": "body", "one_connected_adapter": True},
            {"slot_count": 4, "must_return_exactly": ["1", "2", "3", "4"], "must_preserve": ["hollow transition", "internal hollowing"], "must_assign": "body"},
        ),
    ]


def holdout_packets() -> list[dict[str, Any]]:
    return [
        _packet("holdout-01", "requirements", "vague mount", "Design a wall-mounted cable guide.", {"mounting_pattern": "missing", "cable_diameter": "missing"}, {"must_request": ["mounting pattern", "cable diameter"], "must_not_invent": ["hole spacing", "cable diameter"]}),
        _packet("holdout-02", "requirements", "specified tray", "Design one tray 276 mm wide, 184 mm deep, and 44 mm thick for vertical loading.", {"width_mm": 276, "depth_mm": 184, "thickness_mm": 44, "loading": "vertical"}, {"must_preserve": ["276", "184", "44", "vertical"]}),
        _packet("holdout-03", "requirements", "safety-sensitive mount", "Design a monitor mount for an unknown monitor mass and unknown mounting pattern.", {"mass": "missing", "mounting_pattern": "missing"}, {"must_request": ["mass", "mounting pattern"], "must_not_claim": ["safe load rating", "universal compatibility"]}),
        _packet("holdout-04", "plan", "two-output enclosure", "Plan a two-part enclosure with a base and removable lid, ventilation openings, and a cable exit.", {"output_count": 2, "parts": ["base", "lid"], "features": ["ventilation", "cable exit"]}, {"output_count": 2, "required_features": ["base", "lid", "ventilation", "cable exit"]}),
        _packet("holdout-05", "plan", "multipart semantic mount", "Plan a mount with a printed bracket and a separate clamp, preserving the requested two printable outputs.", {"output_count": 2, "parts": ["bracket", "clamp"]}, {"output_count": 2}),
        _packet("holdout-06", "plan", "feature-rich holder", "Plan one holder with a handle, drainage, a retention slot, and open side walls.", {"output_count": 1, "features": ["handle", "drainage", "retention slot", "open side walls"]}, {"output_count": 1, "required_features": ["handle", "drainage", "retention slot", "open side walls"]}),
        _packet("holdout-07", "geometry", "union geometry", "In one slot, add an overlapping support rib to the supplied body and assign body.", {"slot_ids": ["1"], "operation": "overlapping union", "result_symbol": "body"}, {"slot_count": 1, "must_union": True, "must_assign": "body"}),
        _packet("holdout-08", "geometry", "cut geometry", "In one slot, cut two authorized drainage openings from the supplied body and assign body.", {"slot_ids": ["1"], "operation": "two subtractive cuts", "result_symbol": "body"}, {"slot_count": 1, "must_cut": True, "must_assign": "body"}),
        _packet("holdout-09", "geometry", "loft transition", "In one slot, create a connected rectangular-to-round transition using a valid loft strategy and assign body.", {"slot_ids": ["1"], "operation": "connected loft transition", "result_symbol": "body"}, {"slot_count": 1, "must_loft": True, "must_assign": "body"}),
        _packet("holdout-10", "repair", "bounded geometry repair", "Repair only the invalid result assignment in the supplied geometry response. Preserve dimensions, statements, slot order, and all completed slots.", {"slot_ids": ["1", "2"], "completed_slot_ids": ["1"], "invalid_slot_ids": ["2"], "result_symbol": "body"}, {"repair_boundary": "result assignment only", "preserve": ["dimensions", "slot order", "completed slot 1"]}),
    ]


def _source_roots(repo_root: Path) -> dict[str, Path]:
    return {
        "profile-ablation": repo_root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01/reports",
        "system-boundary": repo_root / "data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01/reports",
    }


def _settings_snapshot() -> dict[str, Any]:
    return {
        "model": MODEL,
        "current": {"temperature": 0.2, "topP": 0.95, "topK": 40, "seed": None, "candidateCount": None},
        "profile_b": {"temperature": None, "topP": None, "topK": None, "seed": 1701, "candidateCount": 1},
        "stage_thinking_source": "current stage-specific configuration preserved from provider policy",
        "max_output_tokens_source": "current stage-specific limits; no truncation change is authorized",
    }


def _prompt_snapshot(repo_root: Path) -> dict[str, Any]:
    source = repo_root / "backend/app/services/ai/gemini_cli.py"
    return {
        "source_path": str(source.relative_to(repo_root)),
        "source_sha256": _sha256(source),
        "prompt_versions": {
            "requirements": "requirements-v4",
            "plan": "design-plan-v8",
            "geometry": "cadquery-geometry-slots-v1-or-cadquery-geometry-body-v10",
            "repair": "cadquery-contract-repair-v3-or-cadquery-geometry-body-repair-v10",
        },
    }


def _repository_snapshot(repo_root: Path, output_root: Path, packets: list[dict[str, Any]], holdouts: list[dict[str, Any]]) -> dict[str, Any]:
    profile_root = repo_root / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"
    flash_root = repo_root / "data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01"
    system_root = repo_root / "data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01"
    raw_paths = [
        *sorted(profile_root.glob("phase-1/packet-*/profile-*/repetition-*.json")),
        *sorted(profile_root.glob("phase-1/packet-*/profile-*/repetition-*/provider-response.json")),
        *sorted(flash_root.rglob("raw_provider_response.json")),
        *sorted(system_root.rglob("provider-capture.json")),
        *sorted(system_root.rglob("provider-response.json")),
    ]
    return {
        "repository": {
            "head": _git(repo_root, "rev-parse", "HEAD"),
            "branch": _git(repo_root, "branch", "--show-current"),
            "origin_main": _git(repo_root, "rev-parse", "origin/main"),
            "divergence": _git(repo_root, "rev-list", "--left-right", "--count", "HEAD...origin/main"),
            "status": _git(repo_root, "status", "--short"),
        },
        "migration_head": _migration_head(repo_root),
        "prior_studies": {
            "profile_ablation_root": str(profile_root),
            "flash_lite_root": str(flash_root),
            "system_boundary_root": str(system_root),
        },
        "raw_capture_hashes": [
            {"path": str(path.relative_to(repo_root)), "sha256": _sha256(path)}
            for path in raw_paths
            if path.is_file()
        ],
        "settings": _settings_snapshot(),
        "settings_hash": _canonical_hash(_settings_snapshot()),
        "prompts": _prompt_snapshot(repo_root),
        "packet_hashes": [{"packet_id": item["packet_id"], "sha256": _canonical_hash(item)} for item in packets],
        "holdout_packet_hashes": [{"packet_id": item["packet_id"], "sha256": _canonical_hash(item)} for item in holdouts],
        "adapter_source_hash": None,
        "output_root": str(output_root),
    }


def _preregistration(snapshot: dict[str, Any], packets: list[dict[str, Any]], holdouts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": "gemini-provider-contract-foundation-preregistration-v1",
        "study_id": STUDY_ID,
        "model": MODEL,
        "selection_packets": [item["packet_id"] for item in packets],
        "holdout_packets": [item["packet_id"] for item in holdouts],
        "settings_candidates": {
            "S0-current-explicit": {"temperature": 0.2, "topP": 0.95, "topK": 40, "seed": None, "candidateCount": None},
            "S1-profile-b": {"temperature": None, "topP": None, "topK": None, "seed": 1701, "candidateCount": 1},
            "S2-default-unseeded": {"temperature": None, "topP": None, "topK": None, "seed": None, "candidateCount": 1},
            "S3-profile-b-alternate-seed": {"temperature": None, "topP": None, "topK": None, "seed": 2718, "candidateCount": 1},
        },
        "thinking_candidates": {
            "H0-current-stage-specific": {"source": "current provider policy"},
            "H1-provider-default": {"thinkingConfig": None},
            "H2-stage-calibrated": {"requirements": "MINIMAL", "plan": "LOW", "geometry": "LOW", "repair": "LOW"},
        },
        "prompt_candidates": {
            "T0-current": {"source": "current prompt builders", "schema": "current"},
            "T1-canonical-contract": {"source": "frozen provider ownership/invariant prompt text", "schema": "current"},
            "T2-canonical-checklist": {"source": "T1 plus invariant checklist", "schema": "current"},
            "T3-hardened-structured": {"source": "T2 plus strict nonempty schema", "schema": "strict"},
        },
        "quality_floor": {
            "universal": ["pass", "pass_with_benign_format_variation"],
            "excluded_from_content_scoring": ["transport_failure", "quota_failure"],
            "critical_invention_maximum": 0,
            "protected_dimension_changes_maximum": 0,
        },
        "metric_order": [
            "universal_intrinsic_quality_floor",
            "stage_semantic_completeness",
            "critical_invention_rate",
            "clarification_decision_stability",
            "semantic_consistency",
            "structural_consistency",
            "geometry_api_validity",
            "geometry_strategy_stability",
            "contract_entropy",
            "canonicalization_distance",
            "efficiency",
        ],
        "contract_regularity": ["semantic", "structural", "identity", "decision", "geometry_strategy", "byte_separate", "entropy", "canonicalization_distance"],
        "credential_policy": {"credential_source": SECONDARY_ENV, "credential_slot": "secondary", "primary_fallback": False, "automatic_rotation": False},
        "rate_policy": {"default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1, "monotonic_clock": True},
        "retry_policy": {"max_attempts_per_logical_operation": 2, "429_wait_seconds_minimum": 30, "transport_wait_seconds_minimum": 10, "retry_hard_429_once": True, "retry_identical_payload": True, "no_third_attempt": True},
        "caps": {"settings_max_logical_operations": 48, "thinking_max_logical_operations": 24, "prompt_max_logical_operations": 48, "holdout_logical_operations": 20},
        "gates": ["settings_floor", "thinking_after_settings", "prompts_after_thinking", "contract_freeze_after_selection", "adapter_after_contract_freeze", "holdout_after_adapter"],
        "decision_options": ["freeze_profile_b_current_prompts", "freeze_profile_b_canonical_prompts", "freeze_profile_b_checklist_prompts", "freeze_profile_b_structured_contract", "freeze_another_settings_profile", "provider_contract_not_yet_stable"],
        "adapter_decision_options": ["adapter_ready_for_end_to_end_integration", "adapter_requires_narrow_followup", "provider_contract_requires_revision"],
        "snapshot": snapshot,
    }


def _immutable_preregistration_matches(existing: dict[str, Any], expected: dict[str, Any]) -> bool:
    left = dict(existing)
    right = dict(expected)
    left.pop("snapshot", None)
    right.pop("snapshot", None)
    return left == right


def prepare_study(output_root: Path, repo_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    packets = selection_packets()
    holdouts = holdout_packets()
    snapshot = _repository_snapshot(repo_root.resolve(), output_root, packets, holdouts)
    preregistration = _preregistration(snapshot, packets, holdouts)
    preregistration_path = reports / "study-preregistration.json"
    if preregistration_path.is_file():
        existing = _json(preregistration_path) or {}
        if not _immutable_preregistration_matches(existing, preregistration):
            raise RuntimeError("study preregistration exists and differs; refusing to mutate frozen inputs")
    else:
        _write(preregistration_path, preregistration)
    _write(output_root / "study.json", {"study_id": STUDY_ID, "model": MODEL, "evidence_root": str(output_root), "phase": "provider-contract-foundation"})
    _write(reports / "selection-packets.json", {"schema_version": "gemini-provider-contract-selection-packets-v1", "packets": packets, "content_hash": _canonical_hash(packets)})
    _write(reports / "holdout-packets.json", {"schema_version": "gemini-provider-contract-holdout-packets-v1", "packets": holdouts, "content_hash": _canonical_hash(holdouts)})
    _write(reports / "repository-snapshot.json", snapshot)
    historical_root = reports / "historical/source-evidence"
    copied: list[dict[str, Any]] = []
    for label, names in SOURCE_REPORTS.items():
        source_root = _source_roots(repo_root)[label]
        for name in names:
            source = source_root / name
            if not source.is_file():
                continue
            destination = historical_root / label / name
            if destination.is_file() and _sha256(destination) != _sha256(source):
                raise RuntimeError(f"historical evidence copy differs: {destination}")
            if not destination.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            copied.append({"source": str(source), "destination": str(destination.relative_to(output_root)), "sha256": _sha256(destination)})
    _write(reports / "historical/source-evidence-manifest.json", {"files": copied, "count": len(copied)})
    return {"study_id": STUDY_ID, "output_root": str(output_root), "selection_packets": len(packets), "holdout_packets": len(holdouts), "historical_files": len(copied), "provider_calls": 0, "worker_calls": 0}


def _legacy_packet(packet_id: str) -> dict[str, Any]:
    mapping = {
        "packet-01": "selection-requirements-fit",
        "packet-02": "selection-plan-feature-rich",
        "packet-03": "selection-geometry-multislot",
    }
    selected = next(item for item in selection_packets() if item["packet_id"] == mapping.get(packet_id, "selection-requirements-fit"))
    return {**selected, "packet_id": packet_id}


def _stage_from_interaction(interaction: dict[str, Any], default: str = "requirements") -> str:
    chain = interaction.get("chain") or {}
    stages = chain.get("stages") or []
    stage = str(stages[0].get("stage") or "") if stages and isinstance(stages[0], dict) else ""
    lowered = stage.casefold()
    if "plan" in lowered:
        return "plan"
    if "geometry" in lowered or "source" in lowered or "cadquery" in lowered:
        return "geometry"
    if "repair" in lowered:
        return "repair"
    if "requirement" in lowered or "clarif" in lowered:
        return "requirements"
    request = interaction.get("request") or {}
    request_kind = str(request.get("request_kind") or request.get("stage") or "").casefold()
    if "plan" in request_kind:
        return "plan"
    if "geometry" in request_kind or "source" in request_kind:
        return "geometry"
    return default


def _profile_label(profile_id: str | None, provider_profile: str | None = None) -> str:
    if profile_id:
        return profile_id
    return "profile-b-sampling" if provider_profile == "profile-b-sampling" else "profile-a-current"


def _content_record(*, source: str, source_path: str, logical_operation_id: str, attempt_id: str | None, stage: str, profile: str, prompt_profile: str, model: str | None, raw_text: str | None, parsed: Any, status_code: int | None, transport_error: str | None, token_counts: dict[str, Any] | None, latency_ms: Any, request: Any, diagnostic: dict[str, Any] | None, packet: dict[str, Any]) -> dict[str, Any]:
    if transport_error or status_code in {408, 429, 502, 503, 504, 599}:
        result = "quota_failure" if status_code == 429 else "transport_failure"
        quality = {"result": result, "missing_meaning": [], "conflicting_meaning": [], "invented_critical_meaning": [], "api_findings": [], "undefined_symbol_findings": [], "structural_emptiness_findings": [], "geometry_strategy_findings": []}
    else:
        quality = evaluate_intrinsic(packet, parsed if parsed is not None else (raw_text or ""), diagnostic_context=diagnostic)
    safe_parsed = parsed
    raw_hash = hashlib.sha256((raw_text or json.dumps(parsed, sort_keys=True, default=str)).encode("utf-8")).hexdigest()
    return {
        "source": source,
        "source_evidence_path": source_path,
        "logical_operation_id": logical_operation_id,
        "provider_attempt_id": attempt_id,
        "stage": stage,
        "packet_id": packet["packet_id"],
        "settings_profile": profile,
        "prompt_profile": prompt_profile,
        "requested_model": MODEL,
        "actual_model": model,
        "status_code": status_code,
        "transport_error": transport_error,
        "raw_response": raw_text,
        "raw_hash": raw_hash,
        "parsed_response": safe_parsed,
        "intrinsic_quality": quality,
        "semantic_signature": semantic_signature(safe_parsed, packet) if safe_parsed is not None else None,
        "structural_signature": structural_signature(safe_parsed) if safe_parsed is not None else None,
        "identity_signature": identity_signature(safe_parsed) if safe_parsed is not None else None,
        "decision_signature": decision_signature(safe_parsed) if safe_parsed is not None else None,
        "geometry_strategy_signature": geometry_strategy_signature(safe_parsed) if safe_parsed is not None else None,
        "contract_entropy_input": safe_parsed,
        "canonicalization_distance": canonicalization_distance(raw_text or {}, safe_parsed) if safe_parsed is not None else None,
        "token_counts": token_counts or {},
        "latency_ms": latency_ms,
        "request": request,
        "diagnostic_current_build": diagnostic or {},
    }


def _phase1_records(profile_root: Path) -> list[dict[str, Any]]:
    report_path = profile_root / "reports/phase-1-packet-results.json"
    document = _json(report_path) or {}
    records: list[dict[str, Any]] = []
    for index, item in enumerate(document.get("records", [])):
        raw_text = item.get("raw_response_text")
        parsed = item.get("parsed_response") or item.get("parsed")
        if parsed is None and isinstance(raw_text, str):
            parsed, _ = parse_provider_response(raw_text)
        packet = _legacy_packet(str(item.get("packet_id")))
        records.append(_content_record(
            source="phase1",
            source_path=str(item.get("provider_call_path") or report_path),
            logical_operation_id=f"phase1:{item.get('profile_id')}:{item.get('packet_id')}:{item.get('repetition', index)}",
            attempt_id=str(item.get("provider_call_path") or "") or None,
            stage=packet["stage"],
            profile=_profile_label(item.get("profile_id")),
            prompt_profile="current",
            model=item.get("actual_model") or item.get("model_identity"),
            raw_text=raw_text,
            parsed=parsed,
            status_code=item.get("status_code"),
            transport_error=item.get("error_category"),
            token_counts=item.get("token_counts") or {"total_tokens": item.get("total_tokens")},
            latency_ms=item.get("latency_ms"),
            request=item.get("rendered_request") or {},
            diagnostic={"historical_quality_floor": item.get("quality_floor"), "historical_buildability": item.get("buildability_findings")},
            packet=packet,
        ))
    return records


def _phase2_records(profile_root: Path) -> list[dict[str, Any]]:
    report_path = profile_root / "reports/phase-2-project-results.json"
    document = _json(report_path) or {}
    records: list[dict[str, Any]] = []
    for arm in document.get("arms", []):
        profile = _profile_label(None, arm.get("arm"))
        for index, interaction in enumerate(arm.get("provider_interactions", [])):
            chain = interaction.get("chain") or {}
            raw_text = interaction.get("raw_response_text")
            parsed = interaction.get("parsed_response") or interaction.get("normalized_response")
            if parsed is None and isinstance(raw_text, str):
                parsed, _ = parse_provider_response(raw_text)
            stage = _stage_from_interaction(interaction)
            packet = _legacy_packet({"requirements": "packet-01", "plan": "packet-02", "geometry": "packet-03"}.get(stage, "packet-01"))
            records.append(_content_record(
                source="phase2",
                source_path=str(interaction.get("source_provider_call_path") or report_path),
                logical_operation_id=f"phase2:{arm.get('arm')}:{index}",
                attempt_id=chain.get("attempt_id"),
                stage=stage,
                profile=profile,
                prompt_profile="current",
                model=interaction.get("model_identity"),
                raw_text=raw_text,
                parsed=parsed,
                status_code=None if chain.get("status") == "completed" else 502,
                transport_error=chain.get("failure_class"),
                token_counts={},
                latency_ms=None,
                request=interaction.get("request") or {},
                diagnostic={"current_build_chain": chain},
                packet=packet,
            ))
    return records


def _system_boundary_records(system_root: Path) -> list[dict[str, Any]]:
    report_path = system_root / "reports/provider-processing-factorial-results.json"
    document = _json(report_path) or {}
    records: list[dict[str, Any]] = []
    for arm in document.get("arms", []):
        profile = _profile_label(None, arm.get("provider_profile"))
        for capture in arm.get("provider_captures", []):
            response = capture.get("response") or {}
            raw_text = response.get("raw_text")
            parsed, _ = parse_provider_response(raw_text) if isinstance(raw_text, str) else (response.get("raw_provider_payload"), 0)
            stage = str(capture.get("stage") or "requirements")
            packet = _legacy_packet({"requirements": "packet-01", "plan": "packet-02", "geometry": "packet-03"}.get("plan" if "plan" in stage else "geometry" if "geometry" in stage or "source" in stage else "requirements", "packet-01"))
            records.append(_content_record(
                source="system-boundary-factorial",
                source_path=str(capture.get("evidence_path") or report_path),
                logical_operation_id=str(capture.get("user_operation_id") or capture.get("provider_call_id")),
                attempt_id=capture.get("provider_call_id"),
                stage="geometry" if stage not in {"requirements", "plan", "repair"} else stage,
                profile=profile,
                prompt_profile="current",
                model=capture.get("actual_model"),
                raw_text=raw_text,
                parsed=parsed,
                status_code=response.get("status_code"),
                transport_error=response.get("error_category"),
                token_counts={"prompt_tokens": response.get("prompt_tokens"), "output_tokens": response.get("output_tokens"), "total_tokens": response.get("total_tokens")},
                latency_ms=response.get("latency_ms"),
                request=capture.get("request") or {},
                diagnostic={"downstream": capture.get("downstream"), "processing": capture.get("processing")},
                packet=packet,
            ))
    for operation in document.get("quota_stopped_operations_preserved", []):
        for provider_call_id in operation.get("provider_call_ids", []):
            packet = _legacy_packet("packet-01")
            records.append(_content_record(
                source="system-boundary-preserved-quota-stop",
                source_path=str(report_path),
                logical_operation_id=str(operation.get("operation_id")),
                attempt_id=str(provider_call_id),
                stage="requirements",
                profile="profile-a-current",
                prompt_profile="current",
                model=MODEL,
                raw_text=None,
                parsed=None,
                status_code=429,
                transport_error="provider_quota_exhausted",
                token_counts={},
                latency_ms=None,
                request={},
                diagnostic={"excluded_from_intrinsic_scoring": True, "reason": operation.get("reason")},
                packet=packet,
            ))
    return records


def offline_rescore(output_root: Path, repo_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    profile_root = repo_root.resolve() / "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01"
    system_root = repo_root.resolve() / "data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01"
    records = _phase1_records(profile_root) + _phase2_records(profile_root) + _system_boundary_records(system_root)
    stage_summaries: list[dict[str, Any]] = []
    for stage in ("requirements", "plan", "geometry", "repair"):
        stage_records = [item for item in records if item["stage"] == stage]
        counts = {result: sum(item["intrinsic_quality"]["result"] == result for item in stage_records) for result in QUALITY_RESULTS}
        stage_summaries.append({"stage": stage, "record_count": len(stage_records), "quality_counts": counts, "content_scored_count": sum(item["intrinsic_quality"]["result"] in {"pass", "pass_with_benign_format_variation"} or item["intrinsic_quality"]["result"].startswith("fail_") for item in stage_records), "transport_excluded_count": sum(item["intrinsic_quality"]["result"] in {"transport_failure", "quota_failure"} for item in stage_records)})
    offline = {"schema_version": "gemini-provider-contract-foundation-intrinsic-rescore-v1", "offline_only": True, "provider_calls": 0, "worker_calls": 0, "record_count": len(records), "records": records, "stage_summaries": stage_summaries}
    regularity_groups: list[dict[str, Any]] = []
    for profile in sorted({item["settings_profile"] for item in records}):
        for stage in ("requirements", "plan", "geometry", "repair"):
            group = [item for item in records if item["settings_profile"] == profile and item["stage"] == stage and item["parsed_response"] is not None and item["intrinsic_quality"]["result"] not in {"transport_failure", "quota_failure"}]
            if not group:
                continue
            parsed = [item["parsed_response"] for item in group]
            regularity_groups.append({"settings_profile": profile, "stage": stage, "record_count": len(group), "semantic_consistency": len({item["semantic_signature"] for item in group}) == 1, "structural_consistency": len({item["structural_signature"] for item in group}) == 1, "identity_consistency": len({item["identity_signature"] for item in group}) == 1, "decision_consistency": len({item["decision_signature"] for item in group}) == 1, "geometry_strategy_consistency": len({item["geometry_strategy_signature"] for item in group}) == 1, "byte_consistency": len({item["raw_hash"] for item in group}) == 1, "contract_entropy": contract_entropy(parsed), "canonicalization_distance_mean": round(sum(int(item.get("canonicalization_distance") or 0) for item in group) / len(group), 6)})
    regularity = {"schema_version": "gemini-provider-contract-foundation-regularity-rescore-v1", "offline_only": True, "provider_calls": 0, "worker_calls": 0, "groups": regularity_groups, "metric_definitions": {"semantic_consistency": "same semantic signature", "byte_consistency": "same raw hash; reported separately", "contract_entropy": "mean normalized entropy across semantic, structural, identity, decision, and geometry signatures"}}
    reports = output_root / "reports"
    _write(reports / "intrinsic-quality-offline-rescore.json", offline)
    _write(reports / "contract-regularity-offline-rescore.json", regularity)
    for filename, reason in {
        "settings-study-results.json": "live settings study is gated after offline rescore",
        "settings-study-decision.json": "not selected before the gated live settings phase",
        "thinking-study-results.json": "thinking study is gated on settings selection",
        "thinking-study-decision.json": "not selected before the gated live thinking phase",
        "prompt-study-results.json": "prompt study is gated on settings and thinking selection",
        "prompt-study-decision.json": "not selected before the gated live prompt phase",
    }.items():
        _write(reports / filename, {"run": False, "reason": reason, "provider_calls": 0, "worker_calls": 0})
    return {"record_count": len(records), "stage_summaries": stage_summaries, "regularity_groups": len(regularity_groups), "provider_calls": 0, "worker_calls": 0}


def _safe_auth_metadata() -> dict[str, Any]:
    return {"auth_source": SECONDARY_ENV, "auth_slot": "secondary", "auth_present": bool(os.environ.get(SECONDARY_ENV))}


def _require_secondary_key() -> str:
    key = os.environ.get(SECONDARY_ENV)
    if not key:
        raise RuntimeError("GEMINI_API_KEY_2 is absent; no provider call was attempted")
    return key


def _prompt_for_packet(packet: dict[str, Any], prompt_profile: str) -> str:
    stage = packet["stage"]
    if prompt_profile == "T0-current":
        provider = GeminiCliProvider(model=MODEL)
        if stage == "requirements":
            return provider.build_requirement_prompt(RequirementExtractionRequest(project_name=packet["title"], original_intent=packet["prompt"], user_instruction=packet["prompt"], defaults=packet["frozen_facts"]))
        if stage == "plan":
            specification = {"requirements": packet["frozen_facts"], "original_intent": packet["prompt"]}
            return provider.build_design_plan_prompt(DesignPlanRequest(project_name=packet["title"], original_intent=packet["prompt"], user_instruction=packet["prompt"], design_specification=specification, active_requirements=list(packet["frozen_facts"].items())))
        if stage == "repair":
            return "\n".join([
                "You are performing a bounded provider-contract repair for Volundr.",
                "Return JSON only. Repair only the named contract defect; preserve all protected values, completed slots, dimensions, slot order, and unrelated content.",
                "Use the fields repair_complete, repaired_fields, preserved_fields, and rejected_changes.",
                f"Frozen packet title: {packet['title']}",
                f"User request: {packet['prompt']}",
                "Frozen facts:",
                json.dumps(packet["frozen_facts"], sort_keys=True),
                "Intrinsic expectations:",
                json.dumps(packet["intrinsic_expectations"], sort_keys=True),
            ])
        return provider.build_cadquery_prompt(ModelGenerationRequest(project_name=packet["title"], original_intent=packet["prompt"], user_instruction=packet["prompt"], design_specification={"requirements": packet["frozen_facts"]}, design_plan={"geometry_obligations": packet["intrinsic_expectations"]}, geometry_contract="legacy_contract"))
    stage_contract = {
        "requirements": "Return one JSON object with requirements, clarification_required, clarification_questions, generation_ready, and explicit source labels. Preserve user facts, separate assumptions/defaults/proposals, request materially required fit facts, and never invent critical dimensions.",
        "plan": "Return one JSON object with plan_ready, components, features, relationships, printable_outputs, and validation_targets. Preserve every requested feature family, output count, dimensions, and ownership relationship. Empty ready plans are invalid.",
        "geometry": "Return one JSON object with slots. Each slot has slot_id, statements, and result_symbol. Return every requested slot exactly once, use valid CadQuery APIs, define local names before use, preserve operation order, maintain one-solid intent, and assign the supplied result symbol.",
        "repair": "Return one JSON object containing only the bounded repair. Preserve completed slots, protected values, dimensions, operation order, and unrelated content; do not redesign or repair arbitrary API misuse.",
    }[stage]
    checklist = ""
    if prompt_profile in {"T2-canonical-checklist", "T3-hardened-structured"}:
        checklist = "\nChecklist: no empty semantic objects; no invented critical meaning; all requested features and outputs are present; every slot appears once; every result symbol is assigned; all local names are defined; use valid CadQuery keyword arguments; keep additive features connected and cuts subtractive."
    schema = ""
    if prompt_profile == "T3-hardened-structured":
        schema = "\nUse a strict nonempty JSON object shape. Reject empty objects, empty ready plans, empty slots, and missing required nested fields."
    return "\n".join([
        "You are producing a provider-owned semantic response for Volundr.",
        "Return JSON only; do not include prose or chain-of-thought.",
        stage_contract,
        checklist,
        schema,
        f"Frozen packet title: {packet['title']}",
        f"User request: {packet['prompt']}",
        "Frozen facts:",
        json.dumps(packet["frozen_facts"], sort_keys=True),
        "Intrinsic expectations:",
        json.dumps(packet["intrinsic_expectations"], sort_keys=True),
    ])


def _thinking_config(profile: str, stage: str) -> dict[str, Any] | None:
    if profile == "H1-provider-default":
        return None
    if profile == "H2-stage-calibrated":
        return {"thinkingLevel": {"requirements": "MINIMAL", "plan": "LOW", "geometry": "LOW", "repair": "LOW"}[stage]}
    return {"thinkingLevel": "MINIMAL"}


def _generation_config(settings_profile: str, thinking_profile: str, stage: str, prompt_profile: str) -> dict[str, Any]:
    if settings_profile == "S0-current-explicit":
        result: dict[str, Any] = {"temperature": 0.2, "topP": 0.95, "topK": 40, "maxOutputTokens": 8192}
    elif settings_profile == "S1-profile-b":
        result = {"seed": 1701, "candidateCount": 1, "maxOutputTokens": 8192}
    elif settings_profile == "S2-default-unseeded":
        result = {"candidateCount": 1, "maxOutputTokens": 8192}
    elif settings_profile == "S3-profile-b-alternate-seed":
        result = {"seed": 2718, "candidateCount": 1, "maxOutputTokens": 8192}
    else:
        raise ValueError(settings_profile)
    thinking = _thinking_config(thinking_profile, stage)
    if thinking is not None:
        result["thinkingConfig"] = thinking
    if prompt_profile == "T3-hardened-structured" or stage == "repair":
        result["responseMimeType"] = "application/json"
    return result


class SharedContractLimiter:
    def __init__(self) -> None:
        self.starts: list[float] = []
        self.last_start: float | None = None
        self.events: list[dict[str, Any]] = []

    async def acquire(self) -> dict[str, Any]:
        while True:
            now = time.monotonic()
            self.starts = [item for item in self.starts if now - item < 60.0]
            sleep_seconds = 0.0
            if self.last_start is not None:
                sleep_seconds = max(sleep_seconds, 5.0 - (now - self.last_start))
            if len(self.starts) >= 15:
                sleep_seconds = max(sleep_seconds, 60.0 - (now - self.starts[0]))
            if sleep_seconds <= 0:
                break
            await asyncio.sleep(sleep_seconds)
        started = time.monotonic()
        self.starts.append(started)
        self.last_start = started
        return {"call_start_monotonic": started, "prior_rolling_window_count": len(self.starts) - 1, "sleep_seconds": None, "limiter_decision": "allow", "effective_requests_per_minute": 12}


def _response_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content")
    if not isinstance(content, dict) or not isinstance(content.get("parts"), list):
        return ""
    return "".join(part.get("text", "") for part in content["parts"] if isinstance(part, dict) and isinstance(part.get("text"), str))


def _provider_error_category(status_code: int | None) -> str | None:
    if status_code == 429:
        return "quota_failure"
    if status_code in {408, 502, 503, 504, 599}:
        return "transport_failure"
    return None


async def _call_provider(*, client: httpx.AsyncClient, limiter: SharedContractLimiter, logical_operation_id: str, packet: dict[str, Any], settings_profile: str, thinking_profile: str, prompt_profile: str, prompt: str, generation_config: dict[str, Any], key: str) -> dict[str, Any]:
    payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": generation_config}
    payload_hash = _canonical_hash(payload)
    configuration_hash = _canonical_hash({"settings_profile": settings_profile, "thinking_profile": thinking_profile, "prompt_profile": prompt_profile, "model": MODEL, "generation_config": generation_config})
    attempts: list[dict[str, Any]] = []
    for attempt_number in range(2):
        limiter_event = await limiter.acquire()
        provider_attempt_id = str(uuid.uuid4())
        started = time.monotonic()
        status_code: int | None = None
        raw_payload: dict[str, Any] | None = None
        raw_text: str | None = None
        error_category: str | None = None
        error_message: str | None = None
        try:
            response = await client.post(f"/models/{MODEL}:generateContent", params={"key": key}, json=payload)
            status_code = response.status_code
            try:
                raw_payload = response.json()
            except ValueError:
                raw_payload = None
            if status_code < 400:
                raw_text = _response_text(raw_payload)
                error_category = None if raw_text else "provider_content_failure"
            else:
                error_category = _provider_error_category(status_code) or "provider_content_failure"
                error_message = str((raw_payload or {}).get("error", {})) if isinstance(raw_payload, dict) else response.text[:500]
        except (httpx.TimeoutException, TimeoutError) as exc:
            status_code = 504
            error_category = "transport_failure"
            error_message = type(exc).__name__
        except httpx.HTTPError as exc:
            status_code = 502
            error_category = "transport_failure"
            error_message = type(exc).__name__
        latency_ms = round((time.monotonic() - started) * 1000)
        attempt = {
            "logical_operation_id": logical_operation_id,
            "provider_attempt_id": provider_attempt_id,
            "attempt_number": attempt_number,
            "retry_number": attempt_number,
            "retry_reason": "hard_429" if attempt_number and attempts and attempts[-1].get("status_code") == 429 else "transport_failure" if attempt_number else None,
            "retry_of_provider_attempt_id": attempts[-1].get("provider_attempt_id") if attempt_number and attempts else None,
            "retry_wait_seconds": None,
            "actual_wait_seconds": None,
            "payload_hash": payload_hash,
            "configuration_hash": configuration_hash,
            "payload_hashes_match": True,
            "configuration_hashes_match": True,
            "stage": packet["stage"],
            "packet_id": packet["packet_id"],
            "settings_profile": settings_profile,
            "thinking_profile": thinking_profile,
            "prompt_profile": prompt_profile,
            "model": MODEL,
            "status_code": status_code,
            "error_category": error_category,
            "error_message": error_message,
            "raw_text": raw_text,
            "raw_provider_payload": raw_payload,
            "latency_ms": latency_ms,
            "usage_metadata": (raw_payload or {}).get("usageMetadata") if isinstance(raw_payload, dict) else None,
            "limiter_event": {**limiter_event, "status_code": status_code},
        }
        attempts.append(attempt)
        limiter.events.append(attempt["limiter_event"])
        if status_code is not None and status_code < 400 and raw_text:
            actual_model = raw_payload.get("modelVersion") if isinstance(raw_payload, dict) else None
            actual_model = actual_model if isinstance(actual_model, str) and actual_model else MODEL
            parsed, _ = parse_provider_response(raw_text)
            return {"logical_operation_id": logical_operation_id, "packet_id": packet["packet_id"], "stage": packet["stage"], "settings_profile": settings_profile, "thinking_profile": thinking_profile, "prompt_profile": prompt_profile, "model": MODEL, "actual_model": actual_model, "prompt": prompt, "generation_config": generation_config, "parsed_response": parsed, "raw_text": raw_text, "status_code": status_code, "attempts": attempts, "complete": True, "success": True}
        if attempt_number == 0 and status_code in {429, 408, 502, 503, 504, 599}:
            requested_wait = 30.0 if status_code == 429 else 10.0
            attempt["retry_wait_seconds"] = requested_wait
            wait_started = time.monotonic()
            await asyncio.sleep(requested_wait)
            attempt["actual_wait_seconds"] = round(time.monotonic() - wait_started, 3)
            continue
        break
    return {"logical_operation_id": logical_operation_id, "packet_id": packet["packet_id"], "stage": packet["stage"], "settings_profile": settings_profile, "thinking_profile": thinking_profile, "prompt_profile": prompt_profile, "model": MODEL, "actual_model": None, "prompt": prompt, "generation_config": generation_config, "parsed_response": None, "raw_text": None, "status_code": attempts[-1].get("status_code") if attempts else None, "attempts": attempts, "complete": False, "success": False}


def _redacted_write(path: Path, value: Any) -> None:
    redactor = RedactionService()
    safe = redactor.redact_mapping(value, artifact_type="provider_contract_study") if isinstance(value, dict) else value
    redactor.assert_json_redacted(safe)
    _write(path, safe)


def _phase_report_path(output_root: Path, phase: str) -> Path:
    return output_root.resolve() / "reports" / f"{phase}.json"


async def run_live_matrix(output_root: Path, *, phase: str, settings_profiles: list[str], thinking_profile: str, prompt_profiles: list[str], packets: list[dict[str, Any]], repetitions: int = 2, limiter: SharedContractLimiter | None = None) -> dict[str, Any]:
    key = _require_secondary_key()
    output_root = output_root.resolve()
    report_path = _phase_report_path(output_root, phase)
    previous = _json(report_path) or {}
    previous_rate_events = list((previous.get("rate_limit") or {}).get("events") or [])
    existing = {str(item.get("logical_operation_id")): item for item in previous.get("records", []) if isinstance(item, dict)}
    limiter = limiter or SharedContractLimiter()
    records: list[dict[str, Any]] = [
        item for item in existing.values()
        if item.get("settings_profile") not in settings_profiles
        or item.get("thinking_profile") != thinking_profile
        or item.get("prompt_profile") not in prompt_profiles
    ]
    for settings_profile in settings_profiles:
        for prompt_profile in prompt_profiles:
            for packet in packets:
                for repetition in range(1, repetitions + 1):
                    logical_id = f"{phase}:{settings_profile}:{thinking_profile}:{prompt_profile}:{packet['packet_id']}:rep-{repetition}"
                    if logical_id in existing:
                        existing_record = dict(existing[logical_id])
                        if existing_record.get("success"):
                            existing_record["intrinsic_quality"] = evaluate_intrinsic(packet, existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""))
                            existing_record["semantic_signature"] = semantic_signature(existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""), packet)
                            existing_record["structural_signature"] = structural_signature(existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""))
                            existing_record["identity_signature"] = identity_signature(existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""))
                            existing_record["decision_signature"] = decision_signature(existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""))
                            existing_record["geometry_strategy_signature"] = geometry_strategy_signature(existing_record.get("parsed_response") if existing_record.get("parsed_response") is not None else existing_record.get("raw_text", ""))
                        records.append(existing_record)
                        continue
                    prompt = _prompt_for_packet(packet, prompt_profile)
                    config = _generation_config(settings_profile, thinking_profile, packet["stage"], prompt_profile)
                    async with httpx.AsyncClient(base_url="https://generativelanguage.googleapis.com/v1beta", timeout=180.0) as client:
                        record = await _call_provider(client=client, limiter=limiter, logical_operation_id=logical_id, packet=packet, settings_profile=settings_profile, thinking_profile=thinking_profile, prompt_profile=prompt_profile, prompt=prompt, generation_config=config, key=key)
                    quality = evaluate_intrinsic(packet, record.get("parsed_response") if record.get("parsed_response") is not None else record.get("raw_text", "")) if record.get("success") else {"result": "quota_failure" if record.get("status_code") == 429 else "transport_failure", "missing_meaning": [], "conflicting_meaning": [], "invented_critical_meaning": [], "api_findings": [], "undefined_symbol_findings": [], "structural_emptiness_findings": [], "geometry_strategy_findings": []}
                    record["intrinsic_quality"] = quality
                    record["semantic_signature"] = semantic_signature(record.get("parsed_response"), packet) if record.get("parsed_response") is not None else None
                    record["structural_signature"] = structural_signature(record.get("parsed_response")) if record.get("parsed_response") is not None else None
                    record["identity_signature"] = identity_signature(record.get("parsed_response")) if record.get("parsed_response") is not None else None
                    record["decision_signature"] = decision_signature(record.get("parsed_response")) if record.get("parsed_response") is not None else None
                    record["geometry_strategy_signature"] = geometry_strategy_signature(record.get("parsed_response")) if record.get("parsed_response") is not None else None
                    records.append(record)
                    report = {"schema_version": "gemini-provider-contract-foundation-live-phase-v1", "run": True, "phase": phase, "study_id": STUDY_ID, "model": MODEL, "auth_audit": _safe_auth_metadata(), "records": records, "provider_calls": sum(len(item.get("attempts", [])) for item in records), "logical_operations": len(records), "complete_logical_operations": sum(bool(item.get("complete")) for item in records), "rate_limit": {"events": previous_rate_events + limiter.events, "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1}, "retry_summary": {"attempts": sum(len(item.get("attempts", [])) for item in records), "retries": sum(max(0, len(item.get("attempts", [])) - 1) for item in records)}}
                    _redacted_write(report_path, report)
                    if record.get("status_code") == 429 and not record.get("success"):
                        return report
    report = {"schema_version": "gemini-provider-contract-foundation-live-phase-v1", "run": True, "phase": phase, "study_id": STUDY_ID, "model": MODEL, "auth_audit": _safe_auth_metadata(), "records": records, "provider_calls": sum(len(item.get("attempts", [])) for item in records), "logical_operations": len(records), "complete_logical_operations": sum(bool(item.get("complete")) for item in records), "rate_limit": {"events": previous_rate_events + limiter.events, "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1}, "retry_summary": {"attempts": sum(len(item.get("attempts", [])) for item in records), "retries": sum(max(0, len(item.get("attempts", [])) - 1) for item in records)}}
    _redacted_write(report_path, report)
    return report


def _matrix_decision(report: dict[str, Any], *, group_key: str, expected_per_group: int, phase: str) -> dict[str, Any]:
    records = report.get("records", [])
    profiles = sorted({item.get(group_key) for item in records if item.get(group_key)})
    summaries: dict[str, Any] = {}
    for profile in profiles:
        group = [item for item in records if item.get(group_key) == profile]
        content = [item for item in group if item.get("success") and item.get("intrinsic_quality", {}).get("result") not in {"transport_failure", "quota_failure"}]
        summaries[profile] = {"logical_operations": len(group), "expected_logical_operations": expected_per_group, "complete": len(group) == expected_per_group and all(item.get("complete") for item in group), "quality_floor_passes": sum(item.get("intrinsic_quality", {}).get("result") in {"pass", "pass_with_benign_format_variation"} for item in content), "content_scored": len(content), "critical_invention_failures": sum(item.get("intrinsic_quality", {}).get("result") == "fail_invented_critical_meaning" for item in content), "contract_entropy": contract_entropy([item.get("parsed_response") for item in content if item.get("parsed_response") is not None])}
    eligible = [profile for profile, summary in summaries.items() if summary["complete"] and summary["content_scored"] == expected_per_group and summary["critical_invention_failures"] == 0 and summary["quality_floor_passes"] == expected_per_group]
    winner = sorted(eligible, key=lambda profile: (summaries[profile]["contract_entropy"], profile))[0] if eligible else None
    return {"schema_version": f"gemini-provider-contract-foundation-{phase}-decision-v1", "run": bool(report.get("run")), "phase": phase, "group_key": group_key, "winner": winner, "eligible_profiles": eligible, "summaries": summaries, "decision": winner or "provider_contract_not_yet_stable", "provider_calls": report.get("provider_calls", 0), "worker_calls": 0}


def _gated_skip(path: Path, reason: str) -> dict[str, Any]:
    result = {"run": False, "reason": reason, "provider_calls": 0, "worker_calls": 0}
    _redacted_write(path, result)
    return result


def _immutable_write(path: Path, value: dict[str, Any]) -> None:
    existing = _json(path)
    if existing is not None and existing != value:
        raise RuntimeError(f"frozen artifact exists and differs: {path}")
    if existing is None:
        _redacted_write(path, value)


def _selected_profiles(output_root: Path) -> dict[str, Any]:
    reports = output_root.resolve() / "reports"
    settings = _json(reports / "settings-study-decision.json") or {}
    thinking = _json(reports / "thinking-study-decision.json") or {}
    prompt = _json(reports / "prompt-study-decision.json") or {}
    return {"settings": settings.get("winner"), "thinking": thinking.get("winner"), "prompt": prompt.get("winner"), "settings_decision": settings, "thinking_decision": thinking, "prompt_decision": prompt}


def freeze_contracts(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    contracts_root = output_root / "contracts"
    selected = _selected_profiles(output_root)
    if not all(selected.get(key) for key in ("settings", "thinking", "prompt")):
        return _gated_skip(reports / "provider-contract-freeze.json", "provider selection did not produce all three eligible winners")
    selection = _json(reports / "selection-packets.json") or {"packets": selection_packets()}
    packets = selection.get("packets") or selection_packets()
    prompt_report = _json(reports / "prompt-study-results.json") or {}
    selected_records = [item for item in prompt_report.get("records", []) if item.get("prompt_profile") == selected["prompt"]]
    actual_models = sorted({item.get("actual_model") for item in selected_records if item.get("actual_model")})
    settings_record = next((item for item in (_json(reports / "settings-study-results.json") or {}).get("records", []) if item.get("settings_profile") == selected["settings"]), {})
    thinking_record = next((item for item in (_json(reports / "thinking-study-results.json") or {}).get("records", []) if item.get("thinking_profile") == selected["thinking"]), {})
    common = {
        "study_id": STUDY_ID,
        "model": MODEL,
        "selected_settings_profile": selected["settings"],
        "selected_thinking_profile": selected["thinking"],
        "selected_prompt_profile": selected["prompt"],
        "actual_model_identities": actual_models,
        "selection_basis": "independent intrinsic provider-contract gates; current-build compatibility is excluded",
        "provider_calls": 0,
        "worker_calls": 0,
    }
    specs = {
        "requirements-v1": {
            **common,
            "stage": "requirements",
            "response_kind": "json_object",
            "invariants": ["preserve user facts", "separate assumptions and proposals", "request materially required missing fit facts", "never invent critical dimensions"],
            "required_fields": ["clarification_required", "clarification_questions", "generation_ready", "requirements"],
            "forbidden_actions": ["promote defaults as user facts", "proceed when critical fit facts are missing"],
        },
        "plan-v1": {
            **common,
            "stage": "plan",
            "response_kind": "json_object",
            "invariants": ["preserve every requested feature family", "preserve output count", "preserve ownership and identity references", "ready plans contain meaning-bearing components and outputs"],
            "required_fields": ["components", "features", "printable_outputs"],
            "forbidden_actions": ["empty ready plan", "invent output or feature obligations", "reference nonexistent component IDs"],
        },
        "geometry-v1": {
            **common,
            "stage": "geometry",
            "response_kind": "cadquery_source",
            "invariants": ["provider returns complete source", "source defines build and PrintableOutput", "use valid CadQuery APIs", "preserve one-solid and requested operation intent"],
            "required_fields": ["build", "PrintableOutput"],
            "forbidden_actions": ["current parser repair", "undefined symbols", "invalid keyword API usage", "unrequested geometry responsibilities"],
            "adapter_mapping": {"source_preservation": "provider-owned source is preserved verbatim", "current_parser_required": False},
        },
        "repair-v1": {
            **common,
            "stage": "repair",
            "response_kind": "json_object",
            "invariants": ["repair only the named contract defect", "preserve protected values and completed content", "preserve slot order", "reject unrelated redesign"],
            "required_fields": ["repair_complete", "repaired_fields", "preserved_fields", "rejected_changes"],
            "forbidden_actions": ["arbitrary API repair", "geometry redesign", "silent protected-value change"],
        },
    }
    freeze_report = {"schema_version": "gemini-provider-contract-freeze-v1", "run": True, **common, "selection_decisions": {key: selected[f"{key}_decision"] for key in ("settings", "thinking", "prompt")}, "selected_live_record_count": len(selected_records), "packet_hashes": [{"packet_id": item["packet_id"], "sha256": _canonical_hash(item)} for item in packets], "contracts": []}
    for contract_id, contract in specs.items():
        path = contracts_root / f"{contract_id}.json"
        _immutable_write(path, contract)
        required_name = f"gemini-flash-lite-{contract['stage']}-contract-v1.json"
        _immutable_write(contracts_root / required_name, {**contract, "contract_id": required_name.removesuffix(".json")})
        report_path = reports / f"provider-contract-{contract_id}.json"
        _immutable_write(report_path, contract)
        freeze_report["contracts"].append({"contract_id": contract_id, "stage": contract["stage"], "path": str(path.relative_to(output_root)), "sha256": _canonical_hash(contract)})
    _immutable_write(reports / "provider-contract-freeze.json", freeze_report)
    return {"run": True, "provider_calls": 0, "worker_calls": 0, "selected": {"settings": selected["settings"], "thinking": selected["thinking"], "prompt": selected["prompt"]}, "contracts": len(specs), "actual_models": actual_models}


def _packet_for_replay(record: dict[str, Any], packets: list[dict[str, Any]]) -> dict[str, Any]:
    packet_id = record.get("packet_id")
    by_id = {item["packet_id"]: item for item in packets}
    if packet_id in by_id:
        return by_id[packet_id]
    if isinstance(packet_id, str) and packet_id.startswith("packet-"):
        return _legacy_packet(packet_id)
    return next(item for item in packets if item["stage"] == record.get("stage"))


def adapter_replay(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    freeze = _json(reports / "provider-contract-freeze.json") or {}
    if not freeze.get("run"):
        _gated_skip(reports / "adapter-replay-results.json", "provider contracts were not frozen")
        return _gated_skip(reports / "adapter-decision.json", "provider contracts were not frozen")
    packets = ((_json(reports / "selection-packets.json") or {}).get("packets") or selection_packets()) + ((_json(reports / "holdout-packets.json") or {}).get("packets") or holdout_packets())
    contracts = {str(item["stage"]): _json(output_root / str(item["path"])) for item in freeze.get("contracts", [])}
    selected = _selected_profiles(output_root)
    live = (_json(reports / "prompt-study-results.json") or {}).get("records", [])
    selected_live = [item for item in live if item.get("prompt_profile") == selected["prompt"]]
    offline = (_json(reports / "intrinsic-quality-offline-rescore.json") or {}).get("records", [])
    replay_records: list[dict[str, Any]] = []
    holdout = (_json(reports / "holdout-results.json") or {})
    holdout_records = holdout.get("records", []) if holdout.get("run") else []
    for corpus, source_records in (("selected-live", selected_live), ("historical-offline", offline), ("holdout", holdout_records)):
        for item in source_records:
            packet = _packet_for_replay(item, packets)
            raw = item.get("parsed_response") if item.get("parsed_response") is not None else item.get("raw_text") or item.get("raw_response") or ""
            adapter = GeminiProviderContractAdapter(stage=packet["stage"], contract=contracts[packet["stage"]] or {})
            if not raw:
                quality_result = "quota_failure" if item.get("status_code") == 429 else "transport_failure"
                result = {"accepted": False, "quality": {"result": quality_result}, "actions": [{"action_class": "rejected_contract_violation", "rule_id": "missing-provider-response", "authoritative_source": "provider-transport"}], "canonical_provider_record": None}
            else:
                result = adapter.adapt(raw, packet, provenance={"source_corpus": corpus, "logical_operation_id": item.get("logical_operation_id")}, owned_ids={"packet_id": packet["packet_id"]})
            replay_records.append({"source_corpus": corpus, "source": item.get("source", "provider-selection"), "logical_operation_id": item.get("logical_operation_id"), "packet_id": packet["packet_id"], "stage": packet["stage"], "adapter_result": result})
    selected_results = [item for item in replay_records if item["source_corpus"] == "selected-live"]
    historical_results = [item for item in replay_records if item["source_corpus"] == "historical-offline"]
    holdout_results = [item for item in replay_records if item["source_corpus"] == "holdout"]
    summary = lambda records: {"record_count": len(records), "accepted_count": sum(bool(item["adapter_result"].get("accepted")) for item in records), "rejected_count": sum(not item["adapter_result"].get("accepted") for item in records), "by_stage": {stage: {"record_count": sum(item["stage"] == stage for item in records), "accepted_count": sum(item["stage"] == stage and item["adapter_result"].get("accepted") for item in records)} for stage in ("requirements", "plan", "geometry", "repair")}}
    report = {"schema_version": "gemini-provider-contract-adapter-replay-v1", "offline_only": True, "run": True, "study_id": STUDY_ID, "model": MODEL, "provider_calls": 0, "worker_calls": 0, "selected_live": summary(selected_results), "historical_offline": summary(historical_results), "holdout": summary(holdout_results), "records": replay_records}
    _redacted_write(reports / "adapter-replay-results.json", report)
    selected_models = sorted({item.get("actual_model") for item in selected_live if item.get("actual_model")})
    holdout_passed = holdout.get("decision") == "holdout_passed"
    ready = bool(selected_results) and all(item["adapter_result"].get("accepted") for item in selected_results) and selected_models == [MODEL] and (not holdout_results or holdout_passed)
    decision_name = "adapter_ready_for_end_to_end_integration" if ready else "provider_contract_requires_revision" if holdout_results and not holdout_passed else "adapter_requires_narrow_followup"
    decision = {"schema_version": "gemini-provider-contract-adapter-decision-v1", "run": True, "study_id": STUDY_ID, "provider_calls": 0, "worker_calls": 0, "decision": decision_name, "selected_live_replay": summary(selected_results), "historical_replay": summary(historical_results), "holdout_replay": summary(holdout_results), "actual_model_identities": selected_models, "rationale": "The adapter gate uses selected provider records; historical failures remain diagnostic and are not rewritten as provider success. A failed holdout prevents an end-to-end integration decision even when representation replay is safe."}
    _redacted_write(reports / "adapter-decision.json", decision)
    return decision


def _holdout_decision(report: dict[str, Any]) -> dict[str, Any]:
    records = report.get("records", [])
    content = [item for item in records if item.get("success") and item.get("intrinsic_quality", {}).get("result") in QUALITY_PASS]
    models = sorted({item.get("actual_model") for item in records if item.get("actual_model")})
    passed = len(records) == 20 and all(item.get("complete") for item in records) and len(content) == 20 and models == [MODEL]
    return {"schema_version": "gemini-provider-contract-foundation-holdout-decision-v1", "run": bool(report.get("run")), "study_id": STUDY_ID, "provider_calls": report.get("provider_calls", 0), "worker_calls": 0, "logical_operations": len(records), "complete_logical_operations": sum(bool(item.get("complete")) for item in records), "content_quality_passes": len(content), "actual_model_identities": models, "decision": "holdout_passed" if passed else "holdout_not_complete_or_quality_failed", "stage_summaries": {stage: {"record_count": sum(item.get("stage") == stage for item in records), "quality_passes": sum(item.get("stage") == stage and item.get("intrinsic_quality", {}).get("result") in QUALITY_PASS for item in records)} for stage in ("requirements", "plan", "geometry", "repair")}}


async def run_holdout(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    adapter_decision = _json(reports / "adapter-decision.json") or {}
    if adapter_decision.get("decision") != "adapter_ready_for_end_to_end_integration":
        _gated_skip(reports / "holdout-results.json", "adapter gate did not authorize holdout")
        return _gated_skip(reports / "holdout-decision.json", "adapter gate did not authorize holdout")
    selected = _selected_profiles(output_root)
    packets = (_json(reports / "holdout-packets.json") or {}).get("packets") or holdout_packets()
    limiter = SharedContractLimiter()
    try:
        report = await run_live_matrix(output_root, phase="holdout-results", settings_profiles=[selected["settings"]], thinking_profile=selected["thinking"], prompt_profiles=[selected["prompt"]], packets=packets, repetitions=2, limiter=limiter)
    except RuntimeError as exc:
        _gated_skip(reports / "holdout-results.json", str(exc))
        return _gated_skip(reports / "holdout-decision.json", str(exc))
    decision = _holdout_decision(report)
    _redacted_write(reports / "holdout-decision.json", decision)
    return decision


def finalize_study(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    selected = _selected_profiles(output_root)
    holdout = _json(reports / "holdout-decision.json") or {}
    adapter = _json(reports / "adapter-decision.json") or {}
    settings = selected.get("settings_decision") or {}
    thinking = selected.get("thinking_decision") or {}
    prompt = selected.get("prompt_decision") or {}
    provider_decision = "freeze_another_settings_profile" if holdout.get("decision") == "holdout_passed" and selected.get("settings") != "S1-profile-b" else "provider_contract_not_yet_stable"
    provider_report = {"schema_version": "gemini-provider-contract-foundation-final-provider-decision-v1", "study_id": STUDY_ID, "model": MODEL, "provider_calls": 0, "worker_calls": 0, "decision": provider_decision, "selected_profiles": {"settings": selected.get("settings"), "thinking": selected.get("thinking"), "prompt": selected.get("prompt")}, "selection_decisions": {"settings": settings, "thinking": thinking, "prompt": prompt}, "holdout_decision": holdout, "rationale": "Selection gates chose the best tested provider behavior, but the universal foundation decision requires every holdout response to clear the intrinsic floor. Current-build compatibility is not used as selection evidence."}
    _redacted_write(reports / "final-provider-contract-decision.json", provider_report)
    adapter_decision = adapter.get("decision") or ("provider_contract_requires_revision" if holdout.get("decision") != "holdout_passed" else "adapter_requires_narrow_followup")
    adapter_report = {"schema_version": "gemini-provider-contract-foundation-final-adapter-decision-v1", "study_id": STUDY_ID, "provider_calls": 0, "worker_calls": 0, "decision": adapter_decision, "provider_decision": provider_decision, "adapter_replay": adapter, "holdout_decision": holdout, "deployment": "not_deployed", "rationale": "The adapter preserves and rejects provider meaning deterministically, but a failed provider holdout cannot authorize end-to-end integration."}
    _redacted_write(reports / "final-adapter-decision.json", adapter_report)

    phase_names = ("settings-study-results", "thinking-study-results", "prompt-study-results", "holdout-results")
    phase_reports = {name: (_json(reports / f"{name}.json") or {}) for name in phase_names}
    all_records = [item for report in phase_reports.values() for item in report.get("records", [])]
    all_attempts = [attempt for record in all_records for attempt in record.get("attempts", [])]
    retry_records = [{"logical_operation_id": record.get("logical_operation_id"), "attempts": [{key: attempt.get(key) for key in ("provider_attempt_id", "retry_number", "retry_reason", "retry_of_provider_attempt_id", "retry_wait_seconds", "actual_wait_seconds", "status_code", "payload_hash", "configuration_hash", "payload_hashes_match", "configuration_hashes_match", "limiter_event")} for attempt in record.get("attempts", [])]} for record in all_records if len(record.get("attempts", [])) > 1]
    rate_report = {"schema_version": "gemini-provider-contract-foundation-rate-limit-report-v1", "study_id": STUDY_ID, "provider_calls": len(all_attempts), "worker_calls": 0, "policy": {"default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1, "clock": "monotonic"}, "phase_summaries": {name: {"provider_calls": report.get("provider_calls", 0), "logical_operations": len(report.get("records", [])), "complete_logical_operations": sum(bool(item.get("complete")) for item in report.get("records", [])), "recorded_limiter_events": len((report.get("rate_limit") or {}).get("events", []))} for name, report in phase_reports.items()}, "events": [{"phase": name, "events": (report.get("rate_limit") or {}).get("events", [])} for name, report in phase_reports.items()]}
    _redacted_write(reports / "gemini-rate-limit-report.json", rate_report)
    retry_report = {"schema_version": "gemini-provider-contract-foundation-retry-report-v1", "study_id": STUDY_ID, "provider_calls": 0, "worker_calls": 0, "logical_operation_count": len(all_records), "attempt_count": len(all_attempts), "retry_logical_operation_count": len(retry_records), "records": retry_records, "policy_check": {"max_attempts_per_logical_operation": max((len(record.get("attempts", [])) for record in all_records), default=0), "no_third_attempt": all(len(record.get("attempts", [])) <= 2 for record in all_records)}}
    _redacted_write(reports / "provider-retry-report.json", retry_report)

    contracts = {path.name: _json(path) for path in sorted((output_root / "contracts").glob("*.json")) if _json(path) is not None}
    historical_manifest = _json(reports / "historical/source-evidence-manifest.json") or {}
    offline = _json(reports / "intrinsic-quality-offline-rescore.json") or {}
    regularity = _json(reports / "contract-regularity-offline-rescore.json") or {}
    bundle = {"schema_version": "gemini-provider-contract-foundation-review-v1", "study": _json(output_root / "study.json") or {}, "historical_inputs": {"manifest": historical_manifest, "repository_snapshot": _json(reports / "repository-snapshot.json") or {}, "source_evidence_embedded": {}}}
    for entry in historical_manifest.get("files", []):
        relative = str(entry.get("destination", ""))
        source_path = output_root / relative
        if source_path.is_file():
            bundle["historical_inputs"]["source_evidence_embedded"][relative] = _json(source_path) if source_path.suffix == ".json" else source_path.read_text(encoding="utf-8")
    bundle.update({
        "offline_rescore": {"records": offline.get("records", []), "summaries": offline.get("stage_summaries", []), "regularity": regularity},
        "settings_study": {"records": phase_reports["settings-study-results"].get("records", []), "summaries": settings.get("summaries", {}), "decision": settings},
        "thinking_study": {"records": phase_reports["thinking-study-results"].get("records", []), "summaries": thinking.get("summaries", {}), "decision": thinking},
        "prompt_study": {"records": phase_reports["prompt-study-results"].get("records", []), "summaries": prompt.get("summaries", {}), "decision": prompt},
        "frozen_contracts": contracts,
        "adapter_replay": {"records": (_json(reports / "adapter-replay-results.json") or {}).get("records", []), "decision": adapter},
        "holdout": {"records": phase_reports["holdout-results"].get("records", []), "decision": holdout},
        "final_provider_decision": provider_report,
        "final_adapter_decision": adapter_report,
        "rate_limit": rate_report,
        "retry_summary": retry_report,
        "redaction": {"credential_value_serialized": False, "credential_source": SECONDARY_ENV, "credential_slot": "secondary", "scanner": "RedactionService.assert_json_redacted"},
    })
    _redacted_write(reports / "all-provider-contract-responses.json", bundle)
    return {"provider_decision": provider_decision, "adapter_decision": adapter_decision, "provider_calls": len(all_attempts), "worker_calls": 0, "holdout": holdout.get("decision")}


async def run_provider_selection(output_root: Path) -> dict[str, Any]:
    output_root = output_root.resolve()
    reports = output_root / "reports"
    thinking_path = reports / "thinking-study-results.json"
    thinking_existing = _json(thinking_path) or {}
    if thinking_existing.get("run") and not any(item.get("thinking_profile") == "H1-provider-default" for item in thinking_existing.get("records", [])):
        bundle = _json(reports / "all-provider-contract-responses.json") or {}
        restored = (bundle.get("thinking_study") or {}).get("records") or []
        if any(item.get("thinking_profile") == "H1-provider-default" for item in restored):
            phase_events = []
            for entry in (bundle.get("rate_limit") or {}).get("events", []):
                if entry.get("phase") == "thinking":
                    phase_events = entry.get("events", [])
                    break
            thinking_existing["records"] = restored
            thinking_existing["provider_calls"] = sum(len(item.get("attempts", [])) for item in restored)
            thinking_existing["logical_operations"] = len(restored)
            thinking_existing["complete_logical_operations"] = sum(bool(item.get("complete")) for item in restored)
            thinking_existing["rate_limit"] = {**(thinking_existing.get("rate_limit") or {}), "events": phase_events}
            _redacted_write(thinking_path, thinking_existing)
    selection = _json(reports / "selection-packets.json") or {}
    packets = selection.get("packets") or selection_packets()
    limiter = SharedContractLimiter()
    try:
        settings_report = await run_live_matrix(output_root, phase="settings-study-results", settings_profiles=["S0-current-explicit", "S1-profile-b"], thinking_profile="H0-current-stage-specific", prompt_profiles=["T0-current"], packets=packets, limiter=limiter)
    except RuntimeError as exc:
        return {"settings": _gated_skip(reports / "settings-study-results.json", str(exc))}
    settings_decision = _matrix_decision(settings_report, group_key="settings_profile", expected_per_group=len(packets) * 2, phase="settings")
    _redacted_write(reports / "settings-study-decision.json", settings_decision)
    settings_winner = settings_decision.get("winner")
    if not settings_winner:
        _gated_skip(reports / "thinking-study-results.json", "thinking study requires an eligible settings winner")
        _gated_skip(reports / "thinking-study-decision.json", "thinking study requires an eligible settings winner")
        _gated_skip(reports / "prompt-study-results.json", "prompt study requires an eligible thinking winner")
        _gated_skip(reports / "prompt-study-decision.json", "prompt study requires an eligible thinking winner")
        return {"settings": settings_decision, "provider_calls": settings_report.get("provider_calls", 0), "worker_calls": 0}
    thinking_packets = [item for item in packets if item["packet_id"] in {"selection-requirements-fit", "selection-plan-ordinary", "selection-geometry-simple", "selection-geometry-multislot"}]
    thinking_report = await run_live_matrix(output_root, phase="thinking-study-results", settings_profiles=[settings_winner], thinking_profile="H0-current-stage-specific", prompt_profiles=["T0-current"], packets=thinking_packets, limiter=limiter)
    h1_report = await run_live_matrix(output_root, phase="thinking-study-results", settings_profiles=[settings_winner], thinking_profile="H1-provider-default", prompt_profiles=["T0-current"], packets=thinking_packets, limiter=limiter)
    thinking_records = thinking_report.get("records", []) + [item for item in h1_report.get("records", []) if item.get("logical_operation_id") not in {existing.get("logical_operation_id") for existing in thinking_report.get("records", [])}]
    thinking_report["records"] = thinking_records
    thinking_report["provider_calls"] = sum(len(item.get("attempts", [])) for item in thinking_records)
    thinking_report["logical_operations"] = len(thinking_records)
    thinking_report["complete_logical_operations"] = sum(bool(item.get("complete")) for item in thinking_records)
    thinking_report["rate_limit"] = {**(thinking_report.get("rate_limit") or {}), "events": list((thinking_report.get("rate_limit") or {}).get("events") or []) + [event for event in (h1_report.get("rate_limit") or {}).get("events", []) if event not in (thinking_report.get("rate_limit") or {}).get("events", [])]}
    _redacted_write(reports / "thinking-study-results.json", thinking_report)
    thinking_decision = _matrix_decision(thinking_report, group_key="thinking_profile", expected_per_group=len(thinking_packets) * 2, phase="thinking")
    _redacted_write(reports / "thinking-study-decision.json", thinking_decision)
    thinking_winner = thinking_decision.get("winner")
    if not thinking_winner:
        _gated_skip(reports / "prompt-study-results.json", "prompt study requires an eligible thinking winner")
        _gated_skip(reports / "prompt-study-decision.json", "prompt study requires an eligible thinking winner")
        return {"settings": settings_decision, "thinking": thinking_decision, "provider_calls": settings_report.get("provider_calls", 0) + thinking_report.get("provider_calls", 0), "worker_calls": 0}
    prompt_report = await run_live_matrix(output_root, phase="prompt-study-results", settings_profiles=[settings_winner], thinking_profile=thinking_winner, prompt_profiles=["T0-current", "T1-canonical-contract"], packets=packets, limiter=limiter)
    _redacted_write(reports / "prompt-study-results.json", prompt_report)
    prompt_decision = _matrix_decision(prompt_report, group_key="prompt_profile", expected_per_group=len(packets) * 2, phase="prompt")
    _redacted_write(reports / "prompt-study-decision.json", prompt_decision)
    return {"settings": settings_decision, "thinking": thinking_decision, "prompt": prompt_decision, "provider_calls": settings_report.get("provider_calls", 0) + thinking_report.get("provider_calls", 0) + prompt_report.get("provider_calls", 0), "worker_calls": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "offline-rescore", "provider-selection", "freeze-contracts", "adapter-replay", "holdout", "finalize"), default="prepare")
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.phase == "prepare":
        result = prepare_study(args.output_root, args.repo_root)
    elif args.phase == "offline-rescore":
        result = offline_rescore(args.output_root, args.repo_root)
    elif args.phase == "provider-selection":
        result = asyncio.run(run_provider_selection(args.output_root))
    elif args.phase == "freeze-contracts":
        result = freeze_contracts(args.output_root)
    elif args.phase == "adapter-replay":
        result = adapter_replay(args.output_root)
    elif args.phase == "holdout":
        result = asyncio.run(run_holdout(args.output_root))
    else:
        result = finalize_study(args.output_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
