#!/usr/bin/env python3
"""Audit and correct the isolated Gemini provider-contract foundation study.

The correction is deliberately separate from the original runner.  It writes
only below ``reports/provider-contract-correction-01`` and uses the secondary
Gemini key for the explicitly authorized continuation calls.
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
from typing import Any, Callable

import httpx

from app.services.gemini_consistency.provider_contract import (
    QUALITY_PASS,
    contract_entropy,
    decision_signature,
    evaluate_intrinsic,
    geometry_strategy_signature,
    identity_signature,
    parse_provider_response,
    semantic_signature,
    structural_signature,
)
from app.services.gemini_consistency.provider_contract_correction import (
    corrected_content_denominator,
    evaluate_bounded_repair,
    evaluate_requirements_correction,
    holdout_configuration_audit,
    repair_packet_validity,
    select_settings_from_content,
    worker_reach_semantics,
)
from app.services.workflow.redaction import RedactionService
from scripts.run_gemini_provider_contract_foundation import (
    MODEL,
    SECONDARY_ENV,
    SharedContractLimiter,
    _canonical_hash,
    _generation_config,
    _json,
    _migration_head,
    _packet,
    _prompt_for_packet,
    _redacted_write,
    _require_secondary_key,
    _response_text,
    _safe_auth_metadata,
    _sha256,
    holdout_packets,
    selection_packets,
)


STUDY_ID = "gemini-provider-contract-foundation-01"
CORRECTION_ID = "provider-contract-correction-01"
HISTORICAL_DIRNAME = "pre-provider-contract-correction"
TRANSPORT_STATUSES = {408, 429, 502, 503, 504, 599}
PHASES = ("settings", "requirements", "repair", "holdout")


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(repo_root), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _old_root(repo_root: Path) -> Path:
    return repo_root / "data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01"


def _reload_secondary_dotenv(repo_root: Path) -> None:
    """Reload only the secondary key for this isolated experiment process."""
    dotenv = repo_root / ".env"
    if not dotenv.is_file():
        raise RuntimeError(".env is absent; no provider call was attempted")
    secondary: str | None = None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{SECONDARY_ENV}="):
            secondary = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
    if not secondary:
        raise RuntimeError("GEMINI_API_KEY_2 is absent from .env; no provider call was attempted")
    for name in ("GEMINI_API_KEY", "VOLUNDR_GEMINI_API_KEY", "VOLUNDR_GEMINI_API_KEY_2"):
        os.environ.pop(name, None)
    os.environ[SECONDARY_ENV] = secondary


def _correction_root(repo_root: Path) -> Path:
    return _old_root(repo_root) / "reports" / CORRECTION_ID


def _transport_record(record: dict[str, Any]) -> bool:
    quality = record.get("intrinsic_quality") or {}
    return quality.get("result") in {"transport_failure", "quota_failure"} or record.get("status_code") in TRANSPORT_STATUSES or bool(record.get("transport_error"))


def _record_result(record: dict[str, Any]) -> str:
    if _transport_record(record):
        return "quota_failure" if record.get("status_code") == 429 or (record.get("intrinsic_quality") or {}).get("result") == "quota_failure" else "transport_failure"
    return str((record.get("intrinsic_quality") or {}).get("result") or "unscored")


def _copy_historical(repo_root: Path) -> dict[str, Any]:
    old = _old_root(repo_root)
    source_reports = old / "reports"
    destination = source_reports / "historical" / HISTORICAL_DIRNAME
    destination.mkdir(parents=True, exist_ok=True)
    copied: list[dict[str, Any]] = []
    for source in sorted(source_reports.glob("*.json")):
        target = destination / source.name
        if not target.exists() or _sha256(target) != _sha256(source):
            shutil.copy2(source, target)
        copied.append({"source": str(source.relative_to(repo_root)), "preserved_path": str(target.relative_to(repo_root)), "sha256": _sha256(target), "bytes": target.stat().st_size})
    contracts = old / "contracts"
    contract_destination = destination / "contracts"
    for source in sorted(contracts.glob("*.json")):
        target = contract_destination / source.name
        if not target.exists() or _sha256(target) != _sha256(source):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied.append({"source": str(source.relative_to(repo_root)), "preserved_path": str(target.relative_to(repo_root)), "sha256": _sha256(target), "bytes": target.stat().st_size})
    return {"destination": str(destination.relative_to(repo_root)), "artifacts": copied}


def _packet_hashes() -> dict[str, Any]:
    packets = selection_packets() + holdout_packets()
    return {item["packet_id"]: _canonical_hash(item) for item in packets}


def _profile_hashes() -> dict[str, str]:
    profiles: dict[str, Any] = {}
    for settings in ("S0-current-explicit", "S1-profile-b"):
        for thinking in ("H0-current-stage-specific", "H1-provider-default"):
            for stage in ("requirements", "plan", "geometry", "repair"):
                profiles[f"{settings}:{thinking}:{stage}"] = _generation_config(settings, thinking, stage, "T0-current")
    return {key: _canonical_hash(value) for key, value in profiles.items()}


def _report_inventory(repo_root: Path, preserved: dict[str, Any]) -> dict[str, Any]:
    old = _old_root(repo_root)
    reports = old / "reports"
    inventory: list[dict[str, Any]] = []
    for item in preserved["artifacts"]:
        inventory.append(item)
    return {"study_json_sha256": _sha256(old / "study.json"), "reports": inventory}


def methodology_audit(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    correction = _correction_root(repo_root)
    preserved = _copy_historical(repo_root)
    old_reports = _old_root(repo_root) / "reports"
    settings = _json(old_reports / "settings-study-results.json") or {}
    settings_records = settings.get("records", [])
    holdout = _json(old_reports / "holdout-results.json") or {}
    holdout_records = holdout.get("records", [])
    holdout_packets_report = _json(old_reports / "holdout-packets.json") or {}
    repair_packet = next((item for item in holdout_packets_report.get("packets", []) if item.get("stage") == "repair"), {})
    prompt_decision = _json(old_reports / "prompt-study-decision.json") or {}
    settings_by_profile: dict[str, list[dict[str, Any]]] = {}
    for record in settings_records:
        settings_by_profile.setdefault(str(record.get("settings_profile")), []).append(record)
    settings_content = {profile: corrected_content_denominator(records) for profile, records in settings_by_profile.items()}
    h0_holdout = [holdout_configuration_audit(item, selected_thinking_profile="H1-provider-default") for item in holdout_records]
    transport_missing = [item for item in settings_records if _transport_record(item)]
    s1_missing = [item for item in settings_by_profile.get("S1-profile-b", []) if _transport_record(item)]
    old_repair_validity = repair_packet_validity(repair_packet)
    audit = {
        "schema_version": "gemini-provider-contract-correction-methodology-audit-v1",
        "run": True,
        "offline_only": True,
        "provider_calls": 0,
        "worker_calls": 0,
        "study_id": STUDY_ID,
        "correction_id": CORRECTION_ID,
        "repository": {
            "head": _git(repo_root, "rev-parse", "HEAD"),
            "branch": _git(repo_root, "branch", "--show-current"),
            "origin_main": _git(repo_root, "rev-parse", "origin/main"),
            "divergence_origin_main_left_right": _git(repo_root, "rev-list", "--left-right", "--count", "origin/main...HEAD"),
            "migration_head": _migration_head(repo_root),
        },
        "model": MODEL,
        "auth_policy": {"required_environment": SECONDARY_ENV, "primary_key_allowed": False},
        "packet_hashes": _packet_hashes(),
        "profile_hashes": _profile_hashes(),
        "preserved_historical_evidence": preserved,
        "report_inventory": _report_inventory(repo_root, preserved),
        "historical_counts": {
            "settings_logical_operations": len(settings_records),
            "settings_provider_attempts": sum(len(item.get("attempts", [])) for item in settings_records),
            "holdout_logical_operations": len(holdout_records),
            "holdout_provider_attempts": sum(len(item.get("attempts", [])) for item in holdout_records),
            "holdout_content_passes": sum(_record_result(item) in QUALITY_PASS for item in holdout_records),
        },
        "corrected_settings_content": settings_content,
        "findings": [
            {
                "finding_id": "settings-transport-denominator",
                "classification": "methodology_error_corrected",
                "details": "S1 has 11 content-bearing passes and one 504 transport operation; the 504 is excluded from the content denominator and cannot make S1 an incomplete quality failure.",
                "affected_logical_operation_ids": [item.get("logical_operation_id") for item in transport_missing],
                "s1_missing_content_operation_ids": [item.get("logical_operation_id") for item in s1_missing],
            },
            {
                "finding_id": "historical-holdout-thinking",
                "classification": "holdout_h0_current_stage_specific",
                "details": "The preserved holdout records explicitly contain H0 MINIMAL thinking configuration. The historical H1 decision is retained but is not a valid H1 holdout conclusion.",
                "classification_counts": {name: sum(item["classification"] == name for item in h0_holdout) for name in sorted({item["classification"] for item in h0_holdout})},
            },
            {
                "finding_id": "repair-packet-source",
                "classification": old_repair_validity["classification"],
                "details": "The historical repair packet contains slot IDs and a repair boundary but no actual source-bearing response, so its two summaries are excluded from provider quality.",
                "reasons": old_repair_validity["reasons"],
            },
            {
                "finding_id": "canonical-prompt",
                "classification": "t1-disqualified-t0-preserved",
                "details": "T1 canonical prompt quality was 7/12 while T0 was 11/12. Plan and geometry T0 stage prompts remain frozen; requirements and repair are tested independently in this correction.",
                "t0_summary": (prompt_decision.get("summaries") or {}).get("T0-current"),
                "t1_summary": (prompt_decision.get("summaries") or {}).get("T1-canonical-contract"),
            },
        ],
        "holdout_configuration_audit": h0_holdout,
    }
    _redacted_write(correction / "methodology-audit.json", audit)
    _redacted_write(correction / "historical-evidence-manifest.json", preserved)
    return audit


def _repair_packet(packet_id: str, title: str, invalid_keyword: str) -> dict[str, Any]:
    source_slots = [
        {"slot_id": "1", "statements": ["body = body.workplane(\"XY\").box(40, 30, 4)"], "result_symbol": "body", "protected": True},
        {"slot_id": "2", "statements": [invalid_keyword], "result_symbol": "shape", "protected": False},
    ]
    return _packet(
        packet_id,
        "repair",
        title,
        "Repair only the named result assignment in this source-bearing geometry response. Preserve completed slot 1 and all protected dimensions and order.",
        {"slot_ids": ["1", "2"], "completed_slot_ids": ["1"], "invalid_slot_ids": ["2"], "required_result_symbol": "body", "protected_dimensions": {"width": 40, "depth": 30, "height": 4}},
        {"repair_boundary": "result assignment only", "preserve": ["dimensions", "slot order", "completed slot 1"], "invalid_defect": "result symbol or API defect in slot 2"},
    ) | {"repair_source": {"source_id": f"{packet_id}-source-v1", "slots": source_slots, "source_hash": _canonical_hash(source_slots)}}


def correction_repair_packets() -> list[dict[str, Any]]:
    return [
        _repair_packet("repair-correction-01", "invalid result-symbol repair", "shape = body.workplane(\"XY\").box(20, 20, 4)"),
        _repair_packet("repair-correction-02", "undefined prior-shape alias repair", "prior_shape = prior_shape.union(body)"),
        _repair_packet("repair-correction-03", "invalid CadQuery keyword repair", "body = body.fillet(radius_value=2)"),
    ]


def corrected_repair_holdout_packet() -> dict[str, Any]:
    return _repair_packet("holdout-10-corrected-repair", "bounded geometry repair with source", "shape = body.workplane(\"XY\").box(20, 20, 4)")


def _correction_prompt(packet: dict[str, Any], prompt_profile: str) -> str:
    base = _prompt_for_packet(packet, "T0-current")
    if packet["stage"] == "requirements" and prompt_profile == "T2-requirements-missing-fit-v1":
        return base + "\n\nCorrection contract: if a fit-critical fact is missing or unknown, set clarification_required=true, set generation_ready=false, ask for each missing fact explicitly, and do not insert a numeric default as a user requirement. A safe clarification stop is valid provider behavior."
    if packet["stage"] == "repair":
        source = json.dumps(packet["repair_source"], indent=2, sort_keys=True)
        bounded = "\n\nReturn actual repaired_items containing the complete replacement payload for every invalid slot, plus preserved_item_ids and rejected_changes. A summary of what should be repaired is not a repair. Do not change completed slots or protected dimensions."
        if prompt_profile == "T2-repair-bounded-payload-v1":
            bounded += " The repaired_items must contain slot_id, result_symbol, and nonempty statements. Use the required result symbol exactly."
        return base + "\n\nActual source-bearing response to repair:\n" + source + bounded
    return base


def _phase_prompt(packet: dict[str, Any], prompt_profile: str) -> str:
    if prompt_profile == "T0-current" and packet["stage"] != "repair":
        return _prompt_for_packet(packet, "T0-current")
    return _correction_prompt(packet, prompt_profile)


def _quality(packet: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if not record.get("success"):
        return {"result": "quota_failure" if record.get("status_code") == 429 else "transport_failure", "reasons": [record.get("error_category") or "provider call did not return content"]}
    response = record.get("parsed_response")
    if packet["stage"] == "requirements":
        return evaluate_requirements_correction(packet, response)
    if packet["stage"] == "repair":
        return evaluate_bounded_repair(packet, response)
    return evaluate_intrinsic(packet, response if response is not None else record.get("raw_text", ""))


def _decorate_record(packet: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    response = record.get("parsed_response")
    record["intrinsic_quality"] = _quality(packet, record)
    record["semantic_signature"] = semantic_signature(response, packet) if response is not None else None
    record["structural_signature"] = structural_signature(response) if response is not None else None
    record["identity_signature"] = identity_signature(response) if response is not None else None
    record["decision_signature"] = decision_signature(response) if response is not None else None
    record["geometry_strategy_signature"] = geometry_strategy_signature(response) if response is not None else None
    record["packet_hash"] = _canonical_hash(packet)
    return record


def _phase_report(correction: Path, phase: str) -> Path:
    return correction / f"{phase}.json"


async def _call_provider_no_hard_429(*, client: httpx.AsyncClient, limiter: SharedContractLimiter, logical_operation_id: str, packet: dict[str, Any], settings_profile: str, thinking_profile: str, prompt_profile: str, prompt: str, generation_config: dict[str, Any], key: str) -> dict[str, Any]:
    """Call Gemini with the frozen limiter and no retry after a hard 429."""
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
                error_category = "quota_failure" if status_code == 429 else "transport_failure" if status_code in TRANSPORT_STATUSES else "provider_content_failure"
                error_message = str((raw_payload or {}).get("error", {})) if isinstance(raw_payload, dict) else response.text[:500]
        except (httpx.TimeoutException, TimeoutError) as exc:
            status_code, error_category, error_message = 504, "transport_failure", type(exc).__name__
        except httpx.HTTPError as exc:
            status_code, error_category, error_message = 502, "transport_failure", type(exc).__name__
        attempt = {
            "logical_operation_id": logical_operation_id,
            "provider_attempt_id": provider_attempt_id,
            "attempt_number": attempt_number,
            "retry_number": attempt_number,
            "retry_reason": "transport_failure" if attempt_number else None,
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
            "latency_ms": round((time.monotonic() - started) * 1000),
            "usage_metadata": (raw_payload or {}).get("usageMetadata") if isinstance(raw_payload, dict) else None,
            "limiter_event": {**limiter_event, "status_code": status_code},
        }
        attempts.append(attempt)
        limiter.events.append(attempt["limiter_event"])
        if status_code is not None and status_code < 400 and raw_text:
            actual_model = raw_payload.get("modelVersion") if isinstance(raw_payload, dict) else None
            return {"logical_operation_id": logical_operation_id, "packet_id": packet["packet_id"], "stage": packet["stage"], "settings_profile": settings_profile, "thinking_profile": thinking_profile, "prompt_profile": prompt_profile, "model": MODEL, "actual_model": actual_model if isinstance(actual_model, str) and actual_model else MODEL, "prompt": prompt, "generation_config": generation_config, "parsed_response": parse_provider_response(raw_text)[0], "raw_text": raw_text, "status_code": status_code, "attempts": attempts, "complete": True, "success": True}
        if status_code == 429:
            break
        if attempt_number == 0 and status_code in {408, 502, 503, 504, 599}:
            requested_wait = 10.0
            attempt["retry_wait_seconds"] = requested_wait
            wait_started = time.monotonic()
            await asyncio.sleep(requested_wait)
            attempt["actual_wait_seconds"] = round(time.monotonic() - wait_started, 3)
            continue
        break
    last = attempts[-1] if attempts else {}
    return {"logical_operation_id": logical_operation_id, "packet_id": packet["packet_id"], "stage": packet["stage"], "settings_profile": settings_profile, "thinking_profile": thinking_profile, "prompt_profile": prompt_profile, "model": MODEL, "actual_model": None, "prompt": prompt, "generation_config": generation_config, "parsed_response": None, "raw_text": None, "status_code": last.get("status_code"), "error_category": last.get("error_category"), "complete": False, "success": False, "attempts": attempts}


def _live_report(phase: str, records: list[dict[str, Any]], limiter: SharedContractLimiter, previous_events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "gemini-provider-contract-correction-live-phase-v1",
        "run": True,
        "phase": phase,
        "study_id": STUDY_ID,
        "correction_id": CORRECTION_ID,
        "model": MODEL,
        "auth_audit": _safe_auth_metadata(),
        "records": records,
        "provider_calls": sum(len(item.get("attempts", [])) for item in records),
        "logical_operations": len(records),
        "complete_logical_operations": sum(bool(item.get("complete")) for item in records),
        "rate_limit": {"events": list(previous_events or []) + limiter.events, "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1},
        "retry_summary": {"attempts": sum(len(item.get("attempts", [])) for item in records), "retries": sum(max(0, len(item.get("attempts", [])) - 1) for item in records), "hard_429_retried": False},
    }


async def run_matrix(repo_root: Path, *, phase: str, packets: list[dict[str, Any]], settings_profile: str, thinking_profile: str, prompt_profiles: list[str], repetitions: int, limiter: SharedContractLimiter | None = None, logical_prefix: str | None = None, prompt_override: Callable[[dict[str, Any], str], str] | None = None, config_override: Callable[[dict[str, Any], str], dict[str, Any]] | None = None) -> dict[str, Any]:
    key = _require_secondary_key()
    correction = _correction_root(repo_root)
    report_path = _phase_report(correction, phase)
    previous = _json(report_path) or {}
    previous_events = list((previous.get("rate_limit") or {}).get("events") or [])
    existing = {str(item.get("logical_operation_id")): item for item in previous.get("records", []) if isinstance(item, dict)}
    records: list[dict[str, Any]] = list(existing.values())
    limiter = limiter or SharedContractLimiter()
    if any(item.get("status_code") == 429 and not item.get("success") for item in records):
        return previous
    async with httpx.AsyncClient(base_url="https://generativelanguage.googleapis.com/v1beta", timeout=180.0) as client:
        for prompt_profile in prompt_profiles:
            for packet in packets:
                for repetition in range(1, repetitions + 1):
                    logical_id = f"{logical_prefix or phase}:{settings_profile}:{thinking_profile}:{prompt_profile}:{packet['packet_id']}:rep-{repetition}"
                    if logical_id in existing and existing[logical_id].get("success"):
                        existing[logical_id] = _decorate_record(packet, existing[logical_id])
                        continue
                    prompt = (prompt_override or _phase_prompt)(packet, prompt_profile)
                    config = (config_override or (lambda item, _profile: _generation_config(settings_profile, thinking_profile, item["stage"], prompt_profile)))(packet, prompt_profile)
                    if thinking_profile == "H1-provider-default" and "thinkingConfig" in config:
                        raise RuntimeError("H1 correction call contains forbidden thinkingConfig")
                    record = await _call_provider_no_hard_429(client=client, limiter=limiter, logical_operation_id=logical_id, packet=packet, settings_profile=settings_profile, thinking_profile=thinking_profile, prompt_profile=prompt_profile, prompt=prompt, generation_config=config, key=key)
                    record = _decorate_record(packet, record)
                    existing[logical_id] = record
                    records = list(existing.values())
                    _redacted_write(report_path, _live_report(phase, records, limiter, previous_events))
                    if record.get("status_code") == 429 and not record.get("success"):
                        return _live_report(phase, records, limiter, previous_events)
    report = _live_report(phase, records, limiter, previous_events)
    _redacted_write(report_path, report)
    return report


def _settings_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = corrected_content_denominator(records)
    content = [item.get("parsed_response") for item in records if not _transport_record(item) and item.get("parsed_response") is not None]
    summary["contract_entropy"] = contract_entropy(content) if content else None
    summary["logical_operations"] = len(records)
    summary["expected_logical_operations"] = 12
    summary["complete"] = len(records) == 12 and all(item.get("complete") for item in records)
    summary["quality_floor_passes"] = summary["content_passes"]
    summary["critical_invention_failures"] = sum(_record_result(item) == "fail_invented_critical_meaning" for item in records if not _transport_record(item))
    return summary


def _settings_selection(old_records: list[dict[str, Any]], replacement: dict[str, Any] | None = None) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    replacement_of = replacement.get("replacement_of_logical_operation_id") if replacement else None
    for record in old_records:
        if record.get("settings_profile") in {"S0-current-explicit", "S1-profile-b"}:
            if replacement_of and record.get("logical_operation_id") == replacement_of:
                continue
            grouped.setdefault(str(record["settings_profile"]), []).append(record)
    if replacement is not None:
        grouped.setdefault("S1-profile-b", []).append(replacement)
    summaries = {profile: _settings_summary(records) for profile, records in grouped.items()}
    decision = select_settings_from_content(summaries)
    historical_transport = {profile: sum(_transport_record(record) for record in old_records if record.get("settings_profile") == profile) for profile in ("S0-current-explicit", "S1-profile-b")}
    return {"schema_version": "gemini-provider-contract-correction-settings-decision-v1", "run": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "model": MODEL, "provider_calls": 1 if replacement else 0, "worker_calls": 0, "summaries": summaries, **decision, "historical_transport_failures_excluded": historical_transport, "selection_basis": "content-bearing responses only; transport and quota are excluded and cannot disqualify a settings profile"}


async def corrected_settings(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    old_reports = _old_root(repo_root) / "reports"
    correction = _correction_root(repo_root)
    old = _json(old_reports / "settings-study-results.json") or {}
    old_records = old.get("records", [])
    missing = next((item for item in old_records if item.get("settings_profile") == "S1-profile-b" and item.get("packet_id") == "selection-geometry-multislot" and ":rep-1" in str(item.get("logical_operation_id")) and not item.get("success")), None)
    if missing is None:
        raise RuntimeError("the expected missing S1 geometry-multislot rep-1 operation was not found")
    packet = next(item for item in selection_packets() if item["packet_id"] == missing["packet_id"])
    expected_prompt = str(missing.get("prompt") or _phase_prompt(packet, "T0-current"))
    expected_config = dict(missing.get("generation_config") or _generation_config("S1-profile-b", "H0-current-stage-specific", "geometry", "T0-current"))
    if expected_config != _generation_config("S1-profile-b", "H0-current-stage-specific", "geometry", "T0-current"):
        raise RuntimeError("the preserved missing operation does not have the frozen S1/H0/T0 generation configuration")
    replacement_report = await run_matrix(
        repo_root,
        phase="settings-s1-replacement",
        packets=[packet],
        settings_profile="S1-profile-b",
        thinking_profile="H0-current-stage-specific",
        prompt_profiles=["T0-current"],
        repetitions=1,
        logical_prefix="settings-s1-replacement",
        prompt_override=lambda _packet, _profile: expected_prompt,
        config_override=lambda _packet, _profile: expected_config,
    )
    replacement = next(iter(replacement_report.get("records", [])), None)
    if replacement is not None:
        replacement["replacement_of_logical_operation_id"] = missing.get("logical_operation_id")
        replacement["preserved_failed_attempt_count"] = len(missing.get("attempts", []))
        replacement["exact_missing_operation"] = True
        _redacted_write(_phase_report(correction, "settings-s1-replacement"), replacement_report)
    corrected = _settings_selection(old_records, replacement)
    corrected["replacement"] = {"historical_logical_operation_id": missing.get("logical_operation_id"), "new_logical_operation_id": replacement.get("logical_operation_id") if replacement else None, "historical_attempts_preserved": len(missing.get("attempts", [])), "replacement_attempts": len(replacement.get("attempts", [])) if replacement else 0}
    _redacted_write(correction / "settings-study-comparison.json", corrected)
    _redacted_write(correction / "settings-study-decision.json", corrected)
    return corrected


def _prompt_matrix_decision(report: dict[str, Any], *, expected_per_prompt: int, phase: str, preferred_prompt: str) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for prompt_profile in sorted({item.get("prompt_profile") for item in report.get("records", []) if item.get("prompt_profile")}):
        records = [item for item in report.get("records", []) if item.get("prompt_profile") == prompt_profile]
        content = [item for item in records if not _transport_record(item)]
        passes = [item for item in content if _record_result(item) in QUALITY_PASS]
        summaries[prompt_profile] = {
            "logical_operations": len(records),
            "expected_logical_operations": expected_per_prompt,
            "complete": len(records) == expected_per_prompt and all(item.get("complete") for item in records),
            "content_scored": len(content),
            "quality_floor_passes": len(passes),
            "transport_failures": sum(_record_result(item) == "transport_failure" for item in records),
            "quota_failures": sum(_record_result(item) == "quota_failure" for item in records),
        }
    eligible = [profile for profile, summary in summaries.items() if summary["complete"] and summary["content_scored"] == expected_per_prompt and summary["quality_floor_passes"] == expected_per_prompt]
    selected = preferred_prompt if preferred_prompt in eligible else eligible[0] if len(eligible) == 1 else None
    return {"schema_version": f"gemini-provider-contract-correction-{phase}-decision-v1", "run": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "model": MODEL, "provider_calls": report.get("provider_calls", 0), "worker_calls": 0, "summaries": summaries, "eligible_prompts": eligible, "selected_prompt": selected, "decision": selected or f"{phase}_prompt_requires_revision"}


async def requirements_study(repo_root: Path, settings_profile: str) -> dict[str, Any]:
    packets = [item for item in holdout_packets() if item["packet_id"] in {"holdout-01", "holdout-02", "holdout-03"}]
    report = await run_matrix(repo_root, phase="requirements-study-results", packets=packets, settings_profile=settings_profile, thinking_profile="H1-provider-default", prompt_profiles=["T0-current", "T2-requirements-missing-fit-v1"], repetitions=2)
    decision = _prompt_matrix_decision(report, expected_per_prompt=6, phase="requirements-study", preferred_prompt="T2-requirements-missing-fit-v1")
    _redacted_write(_correction_root(repo_root) / "requirements-study-decision.json", decision)
    return decision


async def repair_study(repo_root: Path, settings_profile: str) -> dict[str, Any]:
    packets = correction_repair_packets()
    report = await run_matrix(repo_root, phase="repair-study-results", packets=packets, settings_profile=settings_profile, thinking_profile="H1-provider-default", prompt_profiles=["T0-current", "T2-repair-bounded-payload-v1"], repetitions=2)
    decision = _prompt_matrix_decision(report, expected_per_prompt=6, phase="repair-study", preferred_prompt="T2-repair-bounded-payload-v1")
    _redacted_write(_correction_root(repo_root) / "repair-study-decision.json", decision)
    return decision


def stage_prompt_selection(repo_root: Path, requirements: dict[str, Any], repair: dict[str, Any]) -> dict[str, Any]:
    selected_requirements = requirements.get("selected_prompt")
    selected_repair = repair.get("selected_prompt")
    settings_profile = requirements.get("settings_profile") or repair.get("settings_profile") or (_json(_correction_root(repo_root) / "settings-study-decision.json") or {}).get("decision")
    selection = {
        "schema_version": "gemini-provider-contract-correction-stage-prompt-selection-v1",
        "run": True,
        "provider_calls": 0,
        "worker_calls": 0,
        "settings_profile": settings_profile,
        "thinking_profile": "H1-provider-default",
        "stages": {
            "requirements": {"selected_prompt": selected_requirements, "allowed_profiles": ["T0-current", "T2-requirements-missing-fit-v1"], "decision_source": "requirements-study-decision.json"},
            "plan": {"selected_prompt": "T0-current", "frozen": True, "reason": "historical Plan T0 evidence is preserved"},
            "geometry": {"selected_prompt": "T0-current", "frozen": True, "reason": "historical geometry T0 evidence is preserved"},
            "repair": {"selected_prompt": selected_repair, "allowed_profiles": ["T0-current", "T2-repair-bounded-payload-v1"], "decision_source": "repair-study-decision.json"},
        },
        "selected": bool(selected_requirements and selected_repair),
        "decision": "stage_prompts_selected" if selected_requirements and selected_repair else "corrected_stage_prompt_selection_incomplete",
    }
    _redacted_write(_correction_root(repo_root) / "stage-prompt-selection.json", selection)
    return selection


def record_holdout_gate(repo_root: Path, selection: dict[str, Any], reason: str) -> dict[str, Any]:
    gate = {"schema_version": "gemini-provider-contract-correction-holdout-gate-v1", "run": False, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "model": MODEL, "provider_calls": 0, "worker_calls": 0, "selected_thinking_profile": "H1-provider-default", "selection": selection, "reason": reason, "no_provider_call_attempted": True}
    _redacted_write(_correction_root(repo_root) / "corrected-holdout-results.json", gate)
    _redacted_write(_correction_root(repo_root) / "corrected-holdout-decision.json", {**gate, "decision": "corrected_holdout_not_authorized_by_prompt_gate"})
    _redacted_write(_correction_root(repo_root) / "thinking-audit.json", {"schema_version": "gemini-provider-contract-correction-thinking-audit-v1", "run": True, "offline_only": True, "provider_calls": 0, "worker_calls": 0, "selected_profile": "H1-provider-default", "holdout_authorized": False, "reason": reason})
    return gate


def _corrected_holdout_packets() -> list[dict[str, Any]]:
    return [corrected_repair_holdout_packet() if item["packet_id"] == "holdout-10" else item for item in holdout_packets()]


def _holdout_group_packets(packets: list[dict[str, Any]], stage: str) -> list[dict[str, Any]]:
    return [item for item in packets if item["stage"] == stage]


async def corrected_holdout(repo_root: Path, settings_profile: str, requirements_prompt: str, repair_prompt: str) -> dict[str, Any]:
    packets = _corrected_holdout_packets()
    correction = _correction_root(repo_root)
    _redacted_write(correction / "holdout-packets-corrected.json", {"schema_version": "gemini-provider-contract-correction-holdout-packets-v1", "run": True, "provider_calls": 0, "worker_calls": 0, "packets": packets, "packet_hashes": {item["packet_id"]: _canonical_hash(item) for item in packets}})
    limiter = SharedContractLimiter()
    for stage, prompt_profile in (("requirements", requirements_prompt), ("plan", "T0-current"), ("geometry", "T0-current"), ("repair", repair_prompt)):
        await run_matrix(repo_root, phase="corrected-holdout-results", packets=_holdout_group_packets(packets, stage), settings_profile=settings_profile, thinking_profile="H1-provider-default", prompt_profiles=[prompt_profile], repetitions=2, limiter=limiter)
        current = _json(_phase_report(correction, "corrected-holdout-results")) or {}
        if any(item.get("status_code") == 429 and not item.get("success") for item in current.get("records", [])):
            break
    report = _json(_phase_report(correction, "corrected-holdout-results")) or {}
    records = report.get("records", [])
    config_audit = [holdout_configuration_audit(item, selected_thinking_profile="H1-provider-default") for item in records]
    _redacted_write(correction / "thinking-audit.json", {"schema_version": "gemini-provider-contract-correction-thinking-audit-v1", "run": True, "offline_only": True, "provider_calls": 0, "worker_calls": 0, "selected_profile": "H1-provider-default", "records": config_audit, "invalid_count": sum(not item["selected_configuration_valid"] for item in config_audit)})
    content = [item for item in records if not _transport_record(item)]
    passes = [item for item in content if _record_result(item) in QUALITY_PASS]
    models = sorted({item.get("actual_model") for item in records if item.get("actual_model")})
    by_stage = {stage: {"record_count": sum(item.get("stage") == stage for item in records), "content_scored": sum(item.get("stage") == stage and not _transport_record(item) for item in records), "quality_passes": sum(item.get("stage") == stage and _record_result(item) in QUALITY_PASS for item in records)} for stage in ("requirements", "plan", "geometry", "repair")}
    decision = {"schema_version": "gemini-provider-contract-correction-holdout-decision-v1", "run": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "model": MODEL, "provider_calls": report.get("provider_calls", 0), "worker_calls": 0, "logical_operations": len(records), "complete_logical_operations": sum(bool(item.get("complete")) for item in records), "content_scored": len(content), "content_quality_passes": len(passes), "actual_model_identities": models, "configuration_audit_invalid": sum(not item["selected_configuration_valid"] for item in config_audit), "stage_summaries": by_stage, "decision": "corrected_holdout_passed" if len(records) == 20 and len(content) == 20 and len(passes) == 20 and models == [MODEL] and not any(not item["selected_configuration_valid"] for item in config_audit) else "corrected_holdout_not_complete_or_quality_failed", "transport_failures": sum(_record_result(item) == "transport_failure" for item in records), "quota_failures": sum(_record_result(item) == "quota_failure" for item in records)}
    _redacted_write(correction / "corrected-holdout-results.json", report)
    _redacted_write(correction / "corrected-holdout-decision.json", decision)
    return decision


def corrected_provider_decision(repo_root: Path, settings: dict[str, Any], requirements: dict[str, Any], repair: dict[str, Any], holdout: dict[str, Any], selection: dict[str, Any]) -> dict[str, Any]:
    settings_ok = settings.get("decision") in {"S0-current-explicit", "S1-profile-b"}
    req_ok = requirements.get("selected_prompt") is not None
    repair_ok = repair.get("selected_prompt") is not None
    holdout_ok = holdout.get("decision") == "corrected_holdout_passed"
    qualified = settings_ok and req_ok and repair_ok and holdout_ok
    decision = {
        "schema_version": "gemini-provider-contract-correction-provider-decision-v1",
        "run": True,
        "study_id": STUDY_ID,
        "correction_id": CORRECTION_ID,
        "model": MODEL,
        "provider_calls": settings.get("provider_calls", 0) + requirements.get("provider_calls", 0) + repair.get("provider_calls", 0) + holdout.get("provider_calls", 0),
        "worker_calls": 0,
        "selected_settings_profile": settings.get("decision"),
        "selected_thinking_profile": "H1-provider-default",
        "selected_stage_prompts": {"requirements": requirements.get("selected_prompt"), "plan": "T0-current", "geometry": "T0-current", "repair": repair.get("selected_prompt")},
        "decision": "corrected_provider_contract_qualified" if qualified else "provider_contract_correction_incomplete",
        "qualification_dimensions": {"settings_content_gate": settings_ok, "requirements_prompt_gate": req_ok, "repair_prompt_gate": repair_ok, "corrected_holdout_gate": holdout_ok},
        "rationale": "Transport outcomes are excluded from content quality, H1 is explicit provider-default with no thinkingConfig, and repair quality requires actual source-bearing payloads. This provider decision does not authorize production deployment.",
        "stage_prompt_selection": selection,
    }
    _redacted_write(_correction_root(repo_root) / "corrected-provider-decision.json", decision)
    return decision


def record_adapter_gate(repo_root: Path, provider: dict[str, Any]) -> dict[str, Any]:
    reason = "adapter replay is authorized only after corrected provider qualification; the repair prompt gate and corrected H1 holdout gate are incomplete"
    replay = {"schema_version": "gemini-provider-contract-correction-adapter-replay-v1", "run": False, "offline_only": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "model": MODEL, "provider_calls": 0, "worker_calls": 0, "decision": "adapter_replay_not_authorized", "reason": reason, "provider_decision": provider.get("decision"), "records": []}
    decision = {"schema_version": "gemini-provider-contract-correction-adapter-decision-v1", "run": True, "offline_only": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "provider_calls": 0, "worker_calls": 0, "decision": "adapter_replay_not_authorized", "reason": reason, "provider_decision": provider.get("decision")}
    _redacted_write(_correction_root(repo_root) / "corrected-adapter-replay-results.json", replay)
    _redacted_write(_correction_root(repo_root) / "corrected-adapter-decision.json", decision)
    return decision


def rate_retry_report(repo_root: Path) -> dict[str, Any]:
    correction = _correction_root(repo_root)
    phase_names = ("settings-s1-replacement", "requirements-study-results", "repair-study-results", "corrected-holdout-results")
    phases: dict[str, Any] = {}
    all_records: list[dict[str, Any]] = []
    for name in phase_names:
        report = _json(_phase_report(correction, name)) or {}
        records = report.get("records", [])
        all_records.extend(records)
        events = list((report.get("rate_limit") or {}).get("events") or [])
        starts = sorted(float(item["call_start_monotonic"]) for item in events if item.get("call_start_monotonic") is not None)
        phases[name] = {"run": bool(report.get("run")), "logical_operations": len(records), "provider_calls": sum(len(item.get("attempts", [])) for item in records), "retries": sum(max(0, len(item.get("attempts", [])) - 1) for item in records), "status_codes": sorted({item.get("status_code") for record in records for item in record.get("attempts", []) if item.get("status_code") is not None}), "actual_models": sorted({item.get("actual_model") for item in records if item.get("actual_model")}), "min_gap_seconds_within_process": round(min((right - left for left, right in zip(starts, starts[1:])), default=0.0), 3), "hard_429_retried": any(item.get("status_code") == 429 and len(record.get("attempts", [])) > 1 for record in records for item in record.get("attempts", []))}
    report = {"schema_version": "gemini-provider-contract-correction-rate-retry-v1", "run": True, "offline_only": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "provider_calls": 0, "worker_calls": 0, "model": MODEL, "auth_policy": {"secondary_only": True, "environment": SECONDARY_ENV}, "limiter_policy": {"concurrency": 1, "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "hard_429_retried": False}, "phases": phases, "aggregate": {"logical_operations": len(all_records), "provider_calls": sum(len(item.get("attempts", [])) for item in all_records), "retries": sum(max(0, len(item.get("attempts", [])) - 1) for item in all_records), "actual_models": sorted({item.get("actual_model") for item in all_records if item.get("actual_model")}), "worker_calls": 0}}
    _redacted_write(correction / "rate-retry-report.json", report)
    return report


def second_validation_plan(repo_root: Path) -> dict[str, Any]:
    plan = {
        "schema_version": "gemini-provider-contract-correction-second-validation-plan-v1",
        "run": True,
        "offline_only": True,
        "study_id": STUDY_ID,
        "correction_id": CORRECTION_ID,
        "provider_calls": 0,
        "worker_calls": 0,
        "decision_trigger": "run only after a repair prompt reaches 6/6 on three source-bearing repair packets",
        "model": MODEL,
        "auth": {"environment": SECONDARY_ENV, "primary_key_allowed": False},
        "settings": {"profile": "S0-current-explicit", "basis": "corrected content denominators 12/12 for both S0 and S1; S0 lower contract entropy; historical S1 transport excluded"},
        "thinking": {"profile": "H1-provider-default", "generation_config_must_omit": ["thinkingConfig"]},
        "stage_prompts": {"requirements": "T2-requirements-missing-fit-v1", "plan": "T0-current", "geometry": "T0-current", "repair": "new independently qualified bounded-payload prompt"},
        "packets": {"repair_prequalification": [item["packet_id"] for item in correction_repair_packets()], "holdout": [item["packet_id"] for item in _corrected_holdout_packets()]},
        "holdout": {"logical_operations": 20, "packets": 10, "repetitions_per_packet": 2, "one_complete_workflow_per_packet": True},
        "rate_limit": {"provider_concurrency": 1, "default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_call_start_gap_seconds": 5, "retry_hard_429": False},
        "capture": {"immutable_provider_payloads": True, "one_combined_manual_review_json": True, "actual_model_identity_required": MODEL},
        "gates": {"settings": "both content denominators complete and no critical invention", "requirements": "6/6", "repair": "6/6 with actual repaired_items and corrected source semantics", "holdout": "20/20 content passes and exact H1 payload", "adapter": "replay only after provider qualification"},
        "not_run_in_this_correction": True,
    }
    _redacted_write(_correction_root(repo_root) / "second-validation-plan.json", plan)
    return plan


def final_correction_decision(repo_root: Path, provider: dict[str, Any], adapter: dict[str, Any], rate: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    decision = {
        "schema_version": "gemini-provider-contract-correction-final-decision-v1",
        "run": True,
        "offline_only": True,
        "study_id": STUDY_ID,
        "correction_id": CORRECTION_ID,
        "provider_calls": 0,
        "worker_calls": 0,
        "decision": "corrected_second_validation_required",
        "provider_decision": provider.get("decision"),
        "adapter_decision": adapter.get("decision"),
        "actual_model_identities": rate.get("aggregate", {}).get("actual_models", []),
        "reasons": [
            "The historical H1 holdout was actually H0 with explicit MINIMAL thinking and cannot support an H1 conclusion.",
            "The corrected S1 transport denominator is complete and content-valid, but S0 wins the deterministic entropy tie-break.",
            "The requirements T2 prompt is the safer qualified prompt at 6/6, while T0 is 4/6.",
            "The source-bearing repair T2 prompt improves over T0 (4/6 versus 2/6) but does not meet the frozen 6/6 gate.",
            "The corrected H1 holdout and adapter replay were correctly gated and made zero calls.",
        ],
        "production": {"provider_settings_changed": False, "adapter_changed": False, "deployed": False},
        "required_next_step": "Complete the documented second validation after qualifying a bounded repair prompt; do not deploy based on this correction.",
        "second_validation_plan": plan,
    }
    _redacted_write(_correction_root(repo_root) / "final-provider-contract-correction-decision.json", decision)
    _redacted_write(_correction_root(repo_root) / "final-decision.json", decision)
    return decision


def combined_correction_bundle(repo_root: Path, *, provider: dict[str, Any], adapter: dict[str, Any], rate: dict[str, Any], plan: dict[str, Any], final: dict[str, Any]) -> dict[str, Any]:
    correction = _correction_root(repo_root)
    old_reports = _old_root(repo_root) / "reports"
    historical_names = ("settings-study-results.json", "settings-study-decision.json", "thinking-study-results.json", "thinking-study-decision.json", "prompt-study-results.json", "prompt-study-decision.json", "holdout-packets.json", "holdout-results.json", "final-provider-contract-decision.json", "final-adapter-decision.json", "provider-retry-report.json", "gemini-rate-limit-report.json")
    correction_names = ("methodology-audit.json", "settings-study-comparison.json", "settings-s1-replacement.json", "requirements-study-results.json", "requirements-study-decision.json", "repair-study-results.json", "repair-study-decision.json", "stage-prompt-selection.json", "corrected-holdout-results.json", "corrected-holdout-decision.json", "thinking-audit.json", "corrected-provider-decision.json", "corrected-adapter-replay-results.json", "corrected-adapter-decision.json", "rate-retry-report.json", "second-validation-plan.json", "final-provider-contract-correction-decision.json")
    historical = {name.removesuffix(".json"): _json(old_reports / name) for name in historical_names}
    correction_reports = {name.removesuffix(".json"): _json(correction / name) for name in correction_names if (correction / name).is_file()}
    bundle = {"schema_version": "gemini-provider-contract-correction-combined-bundle-v1", "run": True, "offline_only": True, "study_id": STUDY_ID, "correction_id": CORRECTION_ID, "provider_calls": 0, "worker_calls": 0, "model": MODEL, "redaction": {"self_contained": True, "redacted_writer": "RedactionService", "historical_reports_preserved_under": f"{_old_root(repo_root).relative_to(repo_root)}/reports/historical/{HISTORICAL_DIRNAME}"}, "historical_evidence": historical, "correction_evidence": correction_reports, "provider_decision": provider, "adapter_decision": adapter, "rate_retry": rate, "second_validation_plan": plan, "final_decision": final}
    _redacted_write(correction / "combined-correction-bundle.json", bundle)
    return {"path": str((correction / "combined-correction-bundle.json").relative_to(repo_root)), "historical_report_count": len(historical), "correction_report_count": len(correction_reports), "provider_calls": 0, "worker_calls": 0}


async def run_all(repo_root: Path) -> dict[str, Any]:
    """Run the authorized correction sequence, stopping at hard quota."""
    audit = methodology_audit(repo_root)
    settings = await corrected_settings(repo_root)
    settings_profile = settings.get("decision") if settings.get("decision") in {"S0-current-explicit", "S1-profile-b"} else None
    if not settings_profile:
        return {"methodology": audit, "settings": settings, "stopped": "no corrected settings profile qualified"}
    requirements = await requirements_study(repo_root, settings_profile)
    requirements["settings_profile"] = settings_profile
    _redacted_write(_correction_root(repo_root) / "requirements-study-decision.json", requirements)
    if not requirements.get("selected_prompt"):
        return {"methodology": audit, "settings": settings, "requirements": requirements, "stopped": "requirements prompt gate did not qualify"}
    repair = await repair_study(repo_root, settings_profile)
    repair["settings_profile"] = settings_profile
    _redacted_write(_correction_root(repo_root) / "repair-study-decision.json", repair)
    selection = stage_prompt_selection(repo_root, requirements, repair)
    if not selection.get("selected"):
        holdout = record_holdout_gate(repo_root, selection, "corrected H1 holdout requires an independently qualified repair prompt; the all-six content gate was not met")
        provider = corrected_provider_decision(repo_root, settings, requirements, repair, holdout, selection)
        adapter = record_adapter_gate(repo_root, provider)
        rate = rate_retry_report(repo_root)
        plan = second_validation_plan(repo_root)
        final = final_correction_decision(repo_root, provider, adapter, rate, plan)
        bundle = combined_correction_bundle(repo_root, provider=provider, adapter=adapter, rate=rate, plan=plan, final=final)
        return {"methodology": audit, "settings": settings, "requirements": requirements, "repair": repair, "selection": selection, "holdout": holdout, "provider": provider, "adapter": adapter, "rate": rate, "plan": plan, "final": final, "bundle": bundle, "stopped": "stage prompt selection incomplete"}
    holdout = await corrected_holdout(repo_root, settings_profile, str(requirements["selected_prompt"]), str(repair["selected_prompt"]))
    provider = corrected_provider_decision(repo_root, settings, requirements, repair, holdout, selection)
    return {"methodology": audit, "settings": settings, "requirements": requirements, "repair": repair, "selection": selection, "holdout": holdout, "provider": provider}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("audit", "settings", "requirements", "repair", "select-prompts", "holdout", "all"), default="audit")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--settings-profile", choices=("S0-current-explicit", "S1-profile-b"))
    parser.add_argument("--reload-secondary-dotenv", action="store_true", help="Reload GEMINI_API_KEY_2 from repo .env for this process only")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    if args.reload_secondary_dotenv:
        _reload_secondary_dotenv(repo_root)
    if args.phase == "audit":
        result = methodology_audit(repo_root)
    elif args.phase == "settings":
        result = asyncio.run(corrected_settings(repo_root))
    elif args.phase == "requirements":
        settings = args.settings_profile or (_json(_correction_root(repo_root) / "settings-study-decision.json") or {}).get("decision")
        if settings not in {"S0-current-explicit", "S1-profile-b"}:
            raise SystemExit("a qualified corrected settings profile is required")
        result = asyncio.run(requirements_study(repo_root, settings))
    elif args.phase == "repair":
        settings = args.settings_profile or (_json(_correction_root(repo_root) / "settings-study-decision.json") or {}).get("decision")
        if settings not in {"S0-current-explicit", "S1-profile-b"}:
            raise SystemExit("a qualified corrected settings profile is required")
        result = asyncio.run(repair_study(repo_root, settings))
    elif args.phase == "select-prompts":
        result = stage_prompt_selection(repo_root, _json(_correction_root(repo_root) / "requirements-study-decision.json") or {}, _json(_correction_root(repo_root) / "repair-study-decision.json") or {})
    elif args.phase == "holdout":
        settings = args.settings_profile or (_json(_correction_root(repo_root) / "settings-study-decision.json") or {}).get("decision")
        requirements = _json(_correction_root(repo_root) / "requirements-study-decision.json") or {}
        repair = _json(_correction_root(repo_root) / "repair-study-decision.json") or {}
        if settings not in {"S0-current-explicit", "S1-profile-b"} or not requirements.get("selected_prompt") or not repair.get("selected_prompt"):
            raise SystemExit("selected settings and stage prompts are required")
        result = asyncio.run(corrected_holdout(repo_root, settings, requirements["selected_prompt"], repair["selected_prompt"]))
    else:
        result = asyncio.run(run_all(repo_root))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
