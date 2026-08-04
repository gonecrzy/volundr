#!/usr/bin/env python3
"""Run or analyze the quota-bounded Gemini Flash Lite profile ablation."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.gemini_consistency.interaction_capture import (
    ImmutableInteractionCapture,
    StudyContext,
)
from app.services.gemini_consistency.profile_ablation import (
    FLASH_LITE_MODEL,
    PHASE1_CALL_LIMIT,
    AblationProfile,
    FrozenPacket,
    GeminiProfileClient,
    aggregate_phase1_results,
    balanced_execution_order,
    build_profiles,
    build_request_payload,
    causal_comparison,
    phase1_decision,
    production_snapshot,
    readiness_probe,
    score_response,
    select_frozen_packets,
    validate_phase1_budget,
)
from app.services.workflow.redaction import RedactionService


DEFAULT_STUDY_ROOT = Path("data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01")
DEFAULT_OUTPUT_ROOT = Path("data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01")
QUOTA_STATUSES = {408, 429, 502, 503, 504, 599}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    import hashlib

    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: Any, *, overwrite: bool = False) -> None:
    redactor = RedactionService()
    safe, _ = redactor.redact_evidence_value(value, data_root=path.parents[2] if len(path.parents) > 2 else path.parent, evidence_root=path.parent)
    redactor.assert_json_redacted(safe)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def repository_identity(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        try:
            result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=3, check=False)
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        return result.stdout.strip() or "unknown"

    divergence = git("rev-list", "--left-right", "--count", "origin/main...HEAD").split()
    migration_head = "unknown"
    try:
        migration = subprocess.run(
            ["alembic", "heads"],
            cwd=root / "backend",
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        migration_head = migration.stdout.strip() or migration.stderr.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    if migration_head == "unknown":
        revisions = []
        versions_root = root / "backend/alembic/versions"
        for path in versions_root.glob("*.py"):
            match = re.match(r"(\d+)_", path.name)
            if match:
                revisions.append((int(match.group(1)), path.name))
        if revisions:
            migration_head = max(revisions)[1]
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "origin_main": git("rev-parse", "--verify", "origin/main"),
        "origin": git("remote", "get-url", "origin"),
        "migration_head": migration_head,
        "divergence": {
            "ahead": divergence[0] if len(divergence) > 0 else "unknown",
            "behind": divergence[1] if len(divergence) > 1 else "unknown",
        },
    }


def load_packets(output_root: Path, study_root: Path) -> list[FrozenPacket]:
    selection_path = output_root / "packet-selection.json"
    rewrite_selection = False
    if selection_path.is_file():
        selected = _read(selection_path).get("packets", [])
        packets = [FrozenPacket(**item) for item in selected if isinstance(item, dict)]
        if len(packets) == 3 and all(
            "invalid raw output:" not in packet.rendered_prompt.casefold()
            and "schema validation error:" not in packet.rendered_prompt.casefold()
            for packet in packets
        ):
            return packets
        if _result_paths(output_root):
            raise ValueError("frozen packet selection is invalid after Phase 1 evidence exists")
        rewrite_selection = True
    packets = select_frozen_packets(study_root)
    _write_json(
        selection_path,
        {
            "selection_version": "gemini-profile-ablation-packet-selection-v1",
            "source_study_root": str(study_root),
            "selection_frozen_before_profile_a": True,
            "packets": [packet.to_document() for packet in packets],
        },
        overwrite=rewrite_selection,
    )
    for packet in packets:
        _write_json(output_root / "phase-1" / packet.packet_id / "packet.json", packet.to_document())
    return packets


def initialize(output_root: Path, study_root: Path, repository_root: Path) -> tuple[list[FrozenPacket], tuple[AblationProfile, ...]]:
    output_root.mkdir(parents=True, exist_ok=True)
    has_experimental_results = bool(_result_paths(output_root))
    packets = load_packets(output_root, study_root)
    profiles = build_profiles()
    snapshot = production_snapshot(packets, repository_root=repository_root)
    _write_json(output_root / "current-production-profile.json", snapshot, overwrite=not has_experimental_results)
    _write_json(
        output_root / "study.json",
        {
            "study_id": output_root.name,
            "label": "Gemini 3.5 Flash-Lite prompt and generation-configuration ablation",
            "model": FLASH_LITE_MODEL,
            "actual_model_identity_required": True,
            "phase_1": {"packets": 3, "profiles": 5, "repetitions": 2, "calls": PHASE1_CALL_LIMIT},
            "phase_2": {"enabled_only_after_phase_1_qualification": True, "full_project_operations": 10},
            "provider_call_ceiling": {"phase_1": PHASE1_CALL_LIMIT, "readiness": 1, "phase_2": 50},
            "repository": repository_identity(repository_root),
            "production_mutation": False,
            "ollama_calls": 0,
        },
    )
    _write_json(
        output_root / "environment-snapshot.json",
        {
            "repository_at_snapshot": repository_identity(repository_root),
            "migration_head": repository_identity(repository_root).get("migration_head"),
            "provider_adapter": snapshot.get("provider_adapter"),
            "worker_identity": snapshot.get("worker_identity"),
            "verification_identity": snapshot.get("verification_identity"),
            "production_profile_path": "current-production-profile.json",
        },
    )
    _write_json(
        output_root / "migration-head.json",
        {
            "migration_head": repository_identity(repository_root).get("migration_head"),
            "source": "backend/alembic/versions",
            "captured_without_provider_call": True,
        },
    )
    for profile in profiles:
        _write_json(output_root / "profiles" / f"{profile.profile_id}.json", asdict(profile))
    return packets, profiles


def _raw_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))


def _finish_reason(payload: dict[str, Any]) -> str | None:
    candidates = payload.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        value = candidates[0].get("finishReason")
        return str(value) if value is not None else None
    return None


def _error_category(status: int, payload: dict[str, Any]) -> str | None:
    if status < 400:
        return None
    message = _canonical(payload).casefold()
    if status == 429 or "quota" in message or "resource_exhausted" in message:
        return "provider_quota_exhausted"
    if status == 408:
        return "provider_timeout"
    if status in {502, 503, 504, 599}:
        return "provider_transport_failure"
    return "provider_content_failure"


def _result_paths(output_root: Path) -> list[Path]:
    return sorted(output_root.glob("phase-1/packet-*/profile-*/repetition-*.json"))


def _load_results(output_root: Path) -> list[dict[str, Any]]:
    return [_read(path) for path in _result_paths(output_root)]


def write_phase1_reports(output_root: Path) -> dict[str, Any]:
    records = _load_results(output_root)
    scorecards = aggregate_phase1_results(records)
    decision = phase1_decision(baseline_profile_id="profile-a-current", profile_results=scorecards)
    run_state = _read(output_root / "phase-1" / "run-state.json") if (output_root / "phase-1" / "run-state.json").is_file() else {}
    phase1_complete = len(records) == PHASE1_CALL_LIMIT
    quota_interrupted = (
        run_state.get("stopped_reason") == "provider_quota_exhausted"
        or any(record.get("error_category") == "provider_quota_exhausted" for record in records)
    )
    if not phase1_complete:
        decision = {
            **decision,
            "qualifying_profiles": [],
            "decision": "prompt_configuration_improvement_not_established",
            "evaluation_status": "phase_1_incomplete_quota_interruption" if quota_interrupted else "phase_1_incomplete",
        }
    reports = {
        "phase-1-scorecard.json": {"schema_version": "gemini-profile-ablation-scorecard-v1", "records": len(records), "phase_1_complete": phase1_complete, "quota_interrupted": quota_interrupted, "profiles": scorecards},
        "phase-1-packet-results.json": {"schema_version": "gemini-profile-ablation-packet-results-v1", "records": records, "phase_1_complete": phase1_complete, "quota_interrupted": quota_interrupted},
        "phase-1-consistency.json": {
            "schema_version": "gemini-profile-ablation-consistency-v1",
            "profiles": {profile_id: {"semantic_consistency_packets": item.get("semantic_consistency_packets", 0)} for profile_id, item in scorecards.items()},
        },
        "phase-1-causal-comparison.json": {"schema_version": "gemini-profile-ablation-causal-v1", "comparisons": causal_comparison(scorecards)},
        "phase-1-decision.json": {"schema_version": "gemini-profile-ablation-decision-v1", **decision},
        "final-decision.json": {
            "schema_version": "gemini-profile-ablation-final-decision-v1",
            "decision": "prompt_configuration_improvement_not_established" if not decision["qualifying_profiles"] else "adopt_prompt_configuration_profile",
            "phase_2_run": False,
            "phase_1_complete": phase1_complete,
            "quota_interrupted": quota_interrupted,
            "winner": decision["qualifying_profiles"][0] if decision["qualifying_profiles"] else None,
            "phase_1": decision,
        },
    }
    for filename, payload in reports.items():
        _write_json(output_root / "reports" / filename, payload, overwrite=True)
    return decision


def run_phase1(*, output_root: Path, study_root: Path, repository_root: Path, client: GeminiProfileClient) -> dict[str, Any]:
    packets, profiles = initialize(output_root, study_root, repository_root)
    packet_by_id = {packet.packet_id: packet for packet in packets}
    profile_by_id = {profile.profile_id: profile for profile in profiles}
    _write_json(output_root / "readiness.json", readiness_probe(client, output_root))
    order = balanced_execution_order()
    validate_phase1_budget(order)
    _write_json(output_root / "phase-1" / "execution-order.json", {"calls": [list(item) for item in order]})
    experimental_calls = len(_result_paths(output_root))
    stopped_reason: str | None = None
    for packet_id, profile_id, repetition in order:
        result_path = output_root / "phase-1" / packet_id / profile_id / f"repetition-{repetition:02d}.json"
        if result_path.is_file():
            continue
        if experimental_calls >= PHASE1_CALL_LIMIT:
            stopped_reason = "phase_1_call_cap_reached"
            break
        packet = packet_by_id[packet_id]
        profile = profile_by_id[profile_id]
        request_payload = build_request_payload(packet, profile)
        status, response_payload, latency_ms = client.generate(request_payload)
        experimental_calls += 1
        actual_model = response_payload.get("modelVersion") if isinstance(response_payload.get("modelVersion"), str) else None
        raw_text = _raw_text(response_payload)
        error_category = _error_category(status, response_payload)
        if status < 400 and not (actual_model and (actual_model == FLASH_LITE_MODEL or actual_model.startswith(f"{FLASH_LITE_MODEL}-"))):
            error_category = "provider_model_mismatch"
            stopped_reason = "actual_model_mismatch"
        usage = response_payload.get("usageMetadata") if isinstance(response_payload.get("usageMetadata"), dict) else {}
        score = score_response(packet, raw_text, profile_id=profile_id, usage=usage, latency_ms=latency_ms) if not error_category else {
            "profile_id": profile_id,
            "packet_id": packet_id,
            "accepted": False,
            "semantic_fidelity": 0.0,
            "schema_pass": False,
            "provenance_pass": False,
            "slot_completeness": False,
            "source_contract_pass": False,
            "semantic_key": "provider_failure",
        }
        context = StudyContext(
            study_id=output_root.name,
            round="phase-1",
            repetition=repetition,
            case_id=packet_id,
            project_id=f"{profile_id}-{packet_id}",
            user_operation_id=f"{output_root.name}:{packet_id}:{profile_id}:{repetition}",
        )
        capture = ImmutableInteractionCapture(output_root, context)
        _, capture_path = capture.record_call(
            stage=packet.stage,
            prompt_mode=packet.prompt_mode,
            requested_model=FLASH_LITE_MODEL,
            actual_model=actual_model,
            rendered_prompt=_raw_prompt(request_payload),
            request_payload=request_payload,
            response_payload=response_payload,
            raw_text=raw_text,
            status_code=status,
            provider_metadata={"request_id": None},
            usage_metadata=usage,
            latency_ms=latency_ms,
            finish_reason=_finish_reason(response_payload),
            error_category=error_category,
            prompt_version=profile.prompt_variant,
            configuration_hash=_hash(request_payload.get("generationConfig", {})),
            experiment_metadata={
                "profile_id": profile_id,
                "profile_hash": _hash(asdict(profile)),
                "packet_id": packet_id,
                "packet_hash": packet.packet_hash,
                "repetition": repetition,
            },
        )
        record = {
            **score,
            "status_code": status,
            "error_category": error_category,
            "actual_model": actual_model,
            "finish_reason": _finish_reason(response_payload),
            "usage_metadata": usage,
            "latency_ms": latency_ms,
            "packet_hash": packet.packet_hash,
            "profile_hash": _hash(asdict(profile)),
            "provider_call_path": str(capture_path.relative_to(output_root)),
        }
        _write_json(result_path, record)
        if error_category in {"provider_quota_exhausted", "provider_model_mismatch"}:
            stopped_reason = error_category
            break
    _write_json(
        output_root / "phase-1" / "run-state.json",
        {
            "experimental_provider_calls": experimental_calls,
            "call_cap": PHASE1_CALL_LIMIT,
            "stopped_reason": stopped_reason,
            "complete": len(_result_paths(output_root)) == PHASE1_CALL_LIMIT,
        },
        overwrite=True,
    )
    return write_phase1_reports(output_root)


def _raw_prompt(payload: dict[str, Any]) -> str:
    contents = payload.get("contents")
    if isinstance(contents, list) and contents and isinstance(contents[0], dict):
        parts = contents[0].get("parts")
        if isinstance(parts, list):
            return "".join(str(item.get("text", "")) for item in parts if isinstance(item, dict))
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=DEFAULT_STUDY_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--phase-1", action="store_true")
    args = parser.parse_args(argv)
    args.output_root.mkdir(parents=True, exist_ok=True)
    packets, profiles = initialize(args.output_root, args.study_root, args.repo_root)
    if args.dry_run:
        print(json.dumps({"packets": [packet.packet_id for packet in packets], "profiles": [profile.profile_id for profile in profiles], "phase_1_calls": PHASE1_CALL_LIMIT}, indent=2))
        return 0
    if args.analyze_only:
        print(json.dumps(write_phase1_reports(args.output_root), indent=2))
        return 0
    if not args.phase_1:
        parser.error("choose --dry-run, --analyze-only, or --phase-1")
    client = GeminiProfileClient(base_url=args.base_url, timeout_seconds=args.timeout)
    decision = run_phase1(output_root=args.output_root, study_root=args.study_root, repository_root=args.repo_root, client=client)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
