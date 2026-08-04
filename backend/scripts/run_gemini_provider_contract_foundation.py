#!/usr/bin/env python3
"""Run the isolated Gemini provider-contract foundation study.

This script owns experiment evidence only.  It does not change production
provider routing, prompts, schemas, or adapter behavior.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services.gemini_consistency.provider_contract import (
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("prepare", "offline-rescore"), default="prepare")
    parser.add_argument("--output-root", type=Path, default=Path("data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01"))
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args()
    result = prepare_study(args.output_root, args.repo_root) if args.phase == "prepare" else offline_rescore(args.output_root, args.repo_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
