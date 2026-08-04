"""Offline, buildability-first reanalysis for the frozen Gemini profile ablation.

This module consumes only the frozen packet files, immutable provider captures,
and existing Phase 1 result files.  It never owns a provider client and never
changes production routing or the historical reports.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable, Iterable

from app.services.workflow.redaction import RedactionService


MAX_ROLLING_REQUESTS = 15
DEFAULT_REQUESTS_PER_MINUTE = 12
DEFAULT_MIN_INTERVAL_SECONDS = 5.0
QUALITY_FLOOR_RESULTS = (
    "pass",
    "pass_with_safe_normalization",
    "fail_incomplete",
    "fail_conflicting",
    "fail_invented_critical_meaning",
    "fail_structurally_empty",
    "fail_identity_integrity",
    "fail_source_contract",
    "provider_failure",
)

_PROFILE_IDS = (
    "profile-a-current",
    "profile-b-sampling",
    "profile-c-concise-prompt",
    "profile-d-structured-output",
    "profile-e-recommended-combined",
)
_QUALITY_PASS = {"pass", "pass_with_safe_normalization"}
_WEIGHTS = {
    "semantic_stability": 0.25,
    "structural_stability": 0.15,
    "identity_stability": 0.10,
    "clarification_stability": 0.10,
    "geometry_contract_stability": 0.15,
    "failure_predictability": 0.10,
    "repairability": 0.10,
    "efficiency": 0.05,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, (int, float, bool)):
        return str(value).casefold()
    if isinstance(value, dict):
        return " ".join(f"{_text(k)} {_text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return " ".join(_text(item) for item in value)
    return ""


def _objects(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _meaningful(item: Any, fields: Iterable[str]) -> bool:
    return isinstance(item, dict) and any(item.get(field) not in (None, "", [], {}) for field in fields)


def _parse_json(raw_text: str) -> Any:
    candidate = raw_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return None


def authoritative_packet_expectations() -> dict[str, dict[str, Any]]:
    """Return expectations authored from the frozen product packets, not outputs."""

    return {
        "packet-01": {
            "packet_id": "packet-01",
            "stage": "requirements",
            "functional_intents": {"portrait", "landscape", "charging_access"},
            "requires_clarification_for": {"phone_width", "phone_thickness", "phone_fit"},
            "forbidden_invented_critical_facts": {"phone_width", "phone_thickness", "fit_clearance", "viewing_angle"},
            "expected_requirement_ids": ["req_portrait_orientation", "req_landscape_orientation", "req_charging_port_access"],
        },
        "packet-02": {
            "packet_id": "packet-02",
            "stage": "design_plan",
            "capacity": 2,
            "tray_dimensions_mm": {"width": 276, "depth": 184, "thickness": 44},
            "loading_orientation": "vertical_top",
            "required_features": {"carrying_handle", "bottom_drainage", "two_retention_strap_slots", "mostly_open_side_walls"},
            "required_requirement_ids": [
                "tray_width", "tray_depth", "tray_thickness", "tray_capacity", "loading_orientation",
                "carrying_handle", "drainage_openings", "retention_strap_slots", "open_side_walls",
            ],
            "requires_one_printed_component": True,
        },
        "packet-03": {
            "packet_id": "packet-03",
            "stage": "cadquery_geometry_bodies",
            "expected_slot_ids": ["1", "2", "3", "4"],
            "slot_responsibilities": {
                "1": "rectangular-end flange",
                "2": "hollow rectangular-to-round transition",
                "3": "circular-end flange",
                "4": "unobstructed internal flow path / hollowing",
            },
            "dimensions": {"rect_width": 100, "rect_height": 60, "circle_diameter": 70, "transition_length": 85, "wall": 3, "rect_flange": 12, "circle_flange": 12},
            "requires_one_connected_adapter": True,
        },
    }


def _ids(parsed: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            key_text = str(key).casefold()
            if (key_text == "id" or key_text.endswith("_id")) and isinstance(value, (str, int)):
                found.add(str(value))
            if key_text.endswith("_ids") and isinstance(value, list):
                found.update(str(item) for item in value if isinstance(item, (str, int)))
            found.update(_ids(value))
    elif isinstance(parsed, list):
        for value in parsed:
            found.update(_ids(value))
    return found


def _nonempty_array_findings(parsed: dict[str, Any], fields: dict[str, tuple[str, ...]]) -> list[str]:
    findings: list[str] = []
    for field, meaningful_fields in fields.items():
        value = parsed.get(field)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not _meaningful(item, meaningful_fields):
                findings.append(f"{field}[{index}] has no meaning-bearing fields")
    return findings


def _geometry_dimension_present(text: str, name: str, value: int) -> bool:
    if str(value) in text:
        return True
    if name == "circle_diameter" and re.search(r"circle\s*\(\s*35(?:\.0+)?\s*\)", text):
        return True
    if name == "wall":
        if re.search(r"rect\s*\(\s*100\s*,\s*60\s*\).*rect\s*\(\s*94\s*,\s*54\s*\)", text):
            return True
        if re.search(r"circle\s*\(\s*35\s*\).*circle\s*\(\s*32\s*\)", text):
            return True
    return False


def _quality_result(result: str, *, missing: list[str], conflicts: list[str], invented: list[str], empty: list[str], identity: list[str], source: list[str], safe_normalization: bool = False) -> dict[str, Any]:
    return {
        "result": result,
        "missing_meaning": missing,
        "conflicting_meaning": conflicts,
        "invented_critical_meaning": invented,
        "structural_emptiness_findings": empty,
        "identity_findings": identity,
        "source_contract_findings": source,
        "safe_normalization": safe_normalization,
    }


def evaluate_quality_floor(packet_id: str, parsed: Any) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        return _quality_result("provider_failure", missing=["valid JSON object"], conflicts=[], invented=[], empty=[], identity=[], source=["response did not parse as an object"])

    common_empty = _nonempty_array_findings(
        parsed,
        {
            "requirements": ("id", "kind", "description", "subject", "value", "operator"),
            "critical_dimensions": ("id", "kind", "value", "operator", "subject"),
            "functional_requirements": ("id", "kind", "description", "subject", "value", "operator"),
            "components": ("component_id", "id", "name", "label", "object_type"),
            "features": ("feature_id", "id", "description", "object_type", "semantic_role"),
            "relationships": ("relationship_id", "id", "source_id", "target_id", "relationship_type"),
            "printable_outputs": ("output_id", "id", "component_id", "name", "description"),
            "validation_targets": ("target_id", "id", "component_id", "measurement", "value"),
            "slots": ("slot_id", "statements", "result_symbol"),
        },
    )
    if common_empty:
        return _quality_result("fail_structurally_empty", missing=[], conflicts=[], invented=[], empty=common_empty, identity=[], source=[])

    expected = authoritative_packet_expectations()[packet_id]
    text = _text(parsed)
    missing: list[str] = []
    conflicts: list[str] = []
    invented: list[str] = []
    identity: list[str] = []
    source: list[str] = []

    if packet_id == "packet-01":
        intents = {
            "portrait": "portrait" in text,
            "landscape": "landscape" in text,
            "charging_access": "charging" in text and ("access" in text or "port" in text),
        }
        missing.extend(intent for intent, present in intents.items() if not present)
        clarification = parsed.get("clarification_required") is True or bool(_objects(parsed.get("clarification_questions")))
        ready = parsed.get("generation_ready") is True or str(parsed.get("outcome", "")).casefold() in {"ready", "generation_ready"}
        if ready and not clarification:
            invented.append("generation-ready output omitted required phone fit facts and clarification")
        for dimension in _objects(parsed.get("critical_dimensions")):
            dim_text = _text(dimension)
            if any(marker in dim_text for marker in expected["forbidden_invented_critical_facts"]) and dimension.get("source") in {"user", "clarification"}:
                invented.append(f"critical phone-fit fact promoted as {dimension.get('source')} input")
        if any(str(item.get("operator", "")).casefold() in {"conflict", "contradictory"} for item in _objects(parsed.get("conflicts"))):
            conflicts.append("provider marked user meaning as conflicting")
        if missing:
            result = "fail_incomplete"
        elif invented:
            result = "fail_invented_critical_meaning"
        elif not clarification:
            result = "fail_invented_critical_meaning"
        else:
            result = "pass"
        return _quality_result(result, missing=missing, conflicts=conflicts, invented=invented, empty=[], identity=identity, source=source)

    if packet_id == "packet-02":
        components = _objects(parsed.get("components"))
        outputs = _objects(parsed.get("printable_outputs"))
        features = _objects(parsed.get("features"))
        if parsed.get("plan_ready") is True and (not components or not outputs):
            return _quality_result("fail_structurally_empty", missing=["meaningful component and printable output"], conflicts=[], invented=[], empty=["plan_ready requires component and printable output"], identity=[], source=[])
        if len(components) != 1:
            conflicts.append("expected one connected printed holder component")
        component_ids = {str(item.get("component_id") or item.get("id")) for item in components}
        for item in features + outputs:
            reference = item.get("component_id")
            if reference is not None and str(reference) not in component_ids:
                identity.append(f"reference to nonexistent component: {reference}")
        if identity:
            return _quality_result("fail_identity_integrity", missing=[], conflicts=conflicts, invented=[], empty=[], identity=identity, source=[])
        for feature_name in expected["required_features"]:
            aliases = {
                "carrying_handle": ("handle", "carrying_handle"),
                "bottom_drainage": ("drain", "drainage", "bottom"),
                "two_retention_strap_slots": ("strap", "retention", "slot"),
                "mostly_open_side_walls": ("open side", "open_side", "skeleton", "window", "rib"),
            }[feature_name]
            if not all(alias in text for alias in aliases) if feature_name == "bottom_drainage" else not any(alias in text for alias in aliases):
                missing.append(feature_name)
        for key, value in expected["tray_dimensions_mm"].items():
            if str(value) not in text:
                missing.append(f"tray_{key}={value}mm")
        if "two" not in text and not re.search(r"\b2\b", text):
            missing.append("capacity=2")
        if "vertical" not in text or "top" not in text:
            missing.append("vertical top loading")
        if "printable" not in text and not outputs:
            missing.append("printable holder output")
        if missing:
            return _quality_result("fail_incomplete", missing=sorted(set(missing)), conflicts=conflicts, invented=[], empty=[], identity=[], source=[])
        return _quality_result("pass", missing=[], conflicts=conflicts, invented=[], empty=[], identity=[], source=[])

    slots = _objects(parsed.get("slots"))
    expected_ids = set(expected["expected_slot_ids"])
    returned_ids = {str(item.get("slot_id")) for item in slots if item.get("slot_id") is not None}
    if returned_ids != expected_ids:
        missing.extend(f"slot {slot_id}" for slot_id in sorted(expected_ids - returned_ids))
        conflicts.extend(f"unknown slot {slot_id}" for slot_id in sorted(returned_ids - expected_ids))
    for slot in slots:
        slot_id = str(slot.get("slot_id"))
        statements = slot.get("statements") if isinstance(slot.get("statements"), list) else []
        if not statements or not slot.get("result_symbol"):
            return _quality_result("fail_structurally_empty", missing=[], conflicts=[], invented=[], empty=[f"slot {slot_id} has no statement/result symbol"], identity=[], source=[])
        slot_text = _text(slot)
        if slot_id == "1" and not ("rect" in slot_text and "flange" in slot_text):
            missing.append("slot 1 rectangular-end flange")
        if slot_id == "2" and not ("transition" in slot_text or "loft" in slot_text):
            missing.append("slot 2 rectangular-to-round transition")
        if slot_id == "3" and not ("circle" in slot_text and "flange" in slot_text):
            missing.append("slot 3 circular-end flange")
        if slot_id == "4" and not ("hollow" in slot_text or "inner" in slot_text or "cut" in slot_text):
            missing.append("slot 4 unobstructed hollowing")
        if re.search(r"\b(import|from|def|class)\b", slot_text):
            source.append(f"slot {slot_id} contains unsupported source construct")
    for name, value in expected["dimensions"].items():
        if not _geometry_dimension_present(text, name, value):
            missing.append(f"{name}={value}")
    result_symbols = {str(item.get("result_symbol")) for item in slots if item.get("result_symbol")}
    if "union" not in text and "connected" not in text and len(result_symbols) != 1:
        missing.append("one connected adapter")
    if "cut" not in text and "hollow" not in text:
        missing.append("unobstructed flow path")
    if source:
        return _quality_result("fail_source_contract", missing=missing, conflicts=conflicts, invented=[], empty=[], identity=[], source=source)
    if conflicts:
        return _quality_result("fail_conflicting", missing=missing, conflicts=conflicts, invented=[], empty=[], identity=[], source=[])
    if missing:
        return _quality_result("fail_incomplete", missing=sorted(set(missing)), conflicts=[], invented=[], empty=[], identity=[], source=[])
    return _quality_result("pass", missing=[], conflicts=[], invented=[], empty=[], identity=[], source=[])


def _response_ids(packet_id: str, parsed: Any) -> tuple[list[str], list[str]]:
    expected = authoritative_packet_expectations()[packet_id]
    expected_ids = expected.get("expected_requirement_ids") or expected.get("required_requirement_ids") or expected.get("expected_slot_ids") or []
    returned = _ids(parsed)
    if packet_id == "packet-01" and "req_charging_access" in returned:
        returned.remove("req_charging_access")
        returned.add("req_charging_port_access")
    return list(expected_ids), sorted(returned)


def _corrected_score(packet_id: str, parsed: Any, floor: dict[str, Any]) -> dict[str, Any]:
    expected_ids, returned_ids = _response_ids(packet_id, parsed)
    expected = set(expected_ids)
    returned = set(returned_ids)
    matched = len(expected & returned)
    if packet_id == "packet-01" and isinstance(parsed, dict):
        text = _text(parsed)
        matched = sum(marker in text for marker in ("portrait", "landscape", "charging"))
    if packet_id == "packet-02" and isinstance(parsed, dict):
        text = _text(parsed)
        matched = sum(str(value) in text for value in (276, 184, 44, 2)) + sum(marker in text for marker in ("vertical", "top", "handle", "drain", "strap", "open side"))
        matched = min(9, matched)
    if packet_id == "packet-03" and isinstance(parsed, dict):
        matched = len({str(item.get("slot_id")) for item in _objects(parsed.get("slots"))} & set(expected_ids))
    return {
        "semantic_quality": round(matched / len(expected_ids), 4) if expected_ids else 0.0,
        "expected_ids": expected_ids,
        "returned_ids": returned_ids,
        "missing_ids": sorted(expected - returned),
        "unknown_ids": sorted(returned - expected),
        "quality_floor": floor,
    }


def repeatability_metrics(records: list[dict[str, Any]]) -> dict[str, int]:
    by_packet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_packet[str(record.get("packet_id"))].append(record)
    semantic = byte = eligible = 0
    for items in by_packet.values():
        if len(items) != 2:
            continue
        eligible += 1
        if items[0].get("semantic_key") == items[1].get("semantic_key"):
            semantic += 1
        if items[0].get("raw_hash") == items[1].get("raw_hash"):
            byte += 1
    return {"semantic_consistent_packets": semantic, "byte_identical_packets": byte, "eligible_packets": eligible}


def buildability_scorecard(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {key: 0.0 for key in _WEIGHTS} | {"buildability_score": 0.0}
    pairs = repeatability_metrics(records)
    eligible = max(1, pairs["eligible_packets"])
    floor_passes = sum(record.get("quality_floor", {}).get("result") in _QUALITY_PASS for record in records)
    clarification_keys = [str(record.get("normalized_response", {}).get("clarification_required")) for record in records if record.get("packet_id") == "packet-01"]
    geometry_stable = all(record.get("packet_id") != "packet-03" or set(record.get("returned_slot_ids", [])) == {"1", "2", "3", "4"} for record in records)
    failures = [record.get("quality_floor", {}).get("result") for record in records if record.get("quality_floor", {}).get("result") not in _QUALITY_PASS]
    dimensions = {
        "semantic_stability": pairs["semantic_consistent_packets"] / eligible,
        "structural_stability": pairs["semantic_consistent_packets"] / eligible,
        "identity_stability": sum(
            (len(set(record.get("corrected_score", {}).get("expected_ids", [])) & set(record.get("corrected_score", {}).get("returned_ids", []))) / len(record.get("corrected_score", {}).get("expected_ids", [])))
            if record.get("corrected_score", {}).get("expected_ids") else 0.0
            for record in records
        ) / len(records),
        "clarification_stability": 1.0 if not clarification_keys or len(set(clarification_keys)) == 1 else 0.0,
        "geometry_contract_stability": 1.0 if geometry_stable else 0.0,
        "failure_predictability": 1.0 if not failures or len(set(failures)) <= max(1, len(failures) // 2) else 0.5,
        "repairability": sum(record.get("quality_floor", {}).get("result") in _QUALITY_PASS for record in records) / len(records),
        "efficiency": 1.0 / (1.0 + (sum(int(record.get("total_tokens") or 0) for record in records) / len(records)) / 10000.0 + (sum(int(record.get("latency_ms") or 0) for record in records) / len(records)) / 60000.0),
    }
    dimensions = {key: round(max(0.0, min(1.0, value)), 4) for key, value in dimensions.items()}
    return {
        **dimensions,
        "buildability_score": round(sum(dimensions[key] * weight for key, weight in _WEIGHTS.items()), 4),
        "quality_floor_passes": floor_passes,
        "runs": len(records),
        "semantic_consistency_packets": pairs["semantic_consistent_packets"],
        "byte_identical_packets": pairs["byte_identical_packets"],
        "accepted_runs": sum(bool(record.get("accepted")) for record in records),
        "invented_critical_meaning_runs": sum(bool(record.get("quality_floor", {}).get("invented_critical_meaning")) for record in records),
        "tokens": sum(int(record.get("total_tokens") or 0) for record in records),
        "latency_ms": sum(int(record.get("latency_ms") or 0) for record in records),
    }


def qualify_stable_foundation(profile_summaries: dict[str, dict[str, Any]], *, baseline_profile_id: str) -> dict[str, Any]:
    baseline = profile_summaries.get(baseline_profile_id, {})
    qualifying: list[str] = []
    criteria: dict[str, dict[str, Any]] = {}
    for profile_id, summary in profile_summaries.items():
        if profile_id == baseline_profile_id:
            continue
        floor = int(summary.get("quality_floor_passes", 0)) >= 6
        semantic_noninferior = float(summary.get("semantic_quality", summary.get("semantic_fidelity", 0.0))) >= float(baseline.get("semantic_quality", baseline.get("semantic_fidelity", 0.0))) - 0.02
        acceptance_noninferior = int(summary.get("quality_floor_passes", 0)) >= int(baseline.get("quality_floor_passes", 0))
        consistency_improved = int(summary.get("semantic_consistency_packets", 0)) >= int(baseline.get("semantic_consistency_packets", 0)) + 2
        no_integrity_regression = not summary.get("integrity_regression") and int(summary.get("invented_critical_meaning_runs", 0)) <= int(baseline.get("invented_critical_meaning_runs", 0))
        criteria[profile_id] = {
            "quality_floor_cleared": floor,
            "semantic_noninferior": semantic_noninferior,
            "acceptance_noninferior": acceptance_noninferior,
            "repeatability_materially_improved": consistency_improved,
            "no_integrity_regression": no_integrity_regression,
        }
        if all(criteria[profile_id].values()):
            qualifying.append(profile_id)
    decision = "profile_b_stable_foundation_candidate" if qualifying == ["profile-b-sampling"] else "another_profile_stable_foundation_candidate" if qualifying else "no_profile_clears_quality_floor"
    return {"decision": decision, "qualifying_profiles": qualifying, "criteria": criteria, "baseline_profile_id": baseline_profile_id, "semantic_noninferiority_margin": 0.02, "consistency_improvement_threshold": 2}


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _record_path(root: Path, path: Path) -> tuple[str, str, int]:
    return path.parts[-3], path.parts[-2], int(path.stem.split("-")[-1])


def rescore_phase1_records(output_root: Path) -> dict[str, Any]:
    """Rescore frozen captures offline.  This function intentionally has no client argument."""

    packet_files = {path.parent.name: _load_json(path) for path in output_root.glob("phase-1/packet-*/packet.json")}
    result_paths = sorted(output_root.glob("phase-1/packet-*/profile-*/repetition-*.json"))
    records: list[dict[str, Any]] = []
    for result_path in result_paths:
        original = _load_json(result_path)
        packet_id, profile_id, repetition = _record_path(output_root, result_path)
        capture_path = output_root / str(original.get("provider_call_path"))
        capture = _load_json(capture_path)
        response = capture.get("response") if isinstance(capture.get("response"), dict) else {}
        raw_text = str(response.get("raw_text") or "")
        parsed = _parse_json(raw_text)
        floor = evaluate_quality_floor(packet_id, parsed)
        corrected = _corrected_score(packet_id, parsed, floor)
        expected = authoritative_packet_expectations()[packet_id]
        request = capture.get("request") if isinstance(capture.get("request"), dict) else {}
        normalized = parsed
        records.append({
            "profile_id": profile_id,
            "packet_id": packet_id,
            "repetition": repetition,
            "model_identity": capture.get("actual_model") or response.get("actual_model"),
            "rendered_request": request.get("user_prompt") or request.get("provider_payload"),
            "generation_configuration": request.get("generation_settings") or {},
            "response_schema": request.get("structured_schema"),
            "raw_response_text": raw_text,
            "raw_response": response.get("raw_provider_payload"),
            "parsed_response": parsed,
            "normalized_response": normalized,
            "provider_metadata": response.get("provider_metadata") or {},
            "finish_reason": response.get("finish_reason"),
            "token_counts": {"prompt": response.get("prompt_tokens"), "output": response.get("output_tokens"), "total": response.get("total_tokens")},
            "latency_ms": response.get("latency_ms", original.get("latency_ms", 0)),
            "original_score": {key: original.get(key) for key in ("accepted", "semantic_fidelity", "schema_pass", "provenance_pass", "slot_completeness", "source_contract_pass", "invented_content")},
            "corrected_score": corrected,
            "quality_floor": floor,
            "expected_ids": corrected["expected_ids"],
            "returned_ids": corrected["returned_ids"],
            "returned_slot_ids": sorted({str(item.get("slot_id")) for item in _objects((parsed or {}).get("slots")) if item.get("slot_id") is not None}) if isinstance(parsed, dict) else [],
            "repeatability_keys": {"semantic": original.get("semantic_key"), "byte": original.get("raw_hash")},
            "semantic_key": original.get("semantic_key"),
            "raw_hash": original.get("raw_hash"),
            "buildability_findings": {"expected_packet_stage": expected["stage"], "quality_floor_result": floor["result"]},
            "response_hashes": {"raw": original.get("raw_hash"), "capture": capture.get("request_hash")},
            "source_provider_call_path": original.get("provider_call_path"),
            "status_code": response.get("status_code", original.get("status_code")),
            "error_category": response.get("error_category", original.get("error_category")),
            "accepted": floor["result"] in _QUALITY_PASS,
            "total_tokens": response.get("total_tokens", original.get("total_tokens", 0)),
        })
    by_profile: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_profile[record["profile_id"]].append(record)
    summaries: dict[str, dict[str, Any]] = {}
    for profile_id in _PROFILE_IDS:
        items = by_profile[profile_id]
        score = buildability_scorecard(items)
        score["semantic_quality"] = round(sum(float(item["corrected_score"]["semantic_quality"]) for item in items) / len(items), 4) if items else 0.0
        score["semantic_fidelity_original"] = round(sum(float(item["original_score"].get("semantic_fidelity") or 0) for item in items) / len(items), 4) if items else 0.0
        summaries[profile_id] = score
    decision = qualify_stable_foundation(summaries, baseline_profile_id="profile-a-current")
    return {"records": records, "profile_summaries": summaries, "comparisons": profile_comparisons(summaries), "decision": decision, "quality_floor_results": sorted({record["quality_floor"]["result"] for record in records}), "provider_calls": 0}


def profile_comparisons(summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = summaries.get("profile-a-current", {})
    return [
        {
            "baseline": "profile-a-current",
            "candidate": profile_id,
            "isolated_change": change,
            "semantic_quality_delta": round(float(summaries.get(profile_id, {}).get("semantic_quality", 0)) - float(baseline.get("semantic_quality", 0)), 4),
            "buildability_score_delta": round(float(summaries.get(profile_id, {}).get("buildability_score", 0)) - float(baseline.get("buildability_score", 0)), 4),
            "consistency_packet_delta": int(summaries.get(profile_id, {}).get("semantic_consistency_packets", 0)) - int(baseline.get("semantic_consistency_packets", 0)),
            "interpretation": "descriptive offline comparison; no isolated-cause claim for the combined profile",
        }
        for profile_id, change in {
            "profile-b-sampling": "sampling and fixed seed",
            "profile-c-concise-prompt": "prompt concision",
            "profile-d-structured-output": "native structured outputs",
            "profile-e-recommended-combined": "combined recommended profile",
        }.items()
    ]


def preserve_historical_reports(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.glob("*.json")):
        target = destination / path.name
        if target.exists():
            shutil.copy2(path, destination / f"{path.name}.copy")
        else:
            shutil.copy2(path, target)


def _redact_paths(value: Any) -> Any:
    if isinstance(value, str):
        value = re.sub(r"/(?:tmp|var/tmp|private/tmp)/[^\s\"']+", "[REDACTED_PATH]", value)
        return value
    if isinstance(value, list):
        return [_redact_paths(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_paths(item) for key, item in value.items()}
    return value


def write_manual_review_bundle(output: Path, *, study: dict[str, Any], repository: dict[str, Any], packets: list[dict[str, Any]], profiles: list[dict[str, Any]], phase1: dict[str, Any], phase2: dict[str, Any], historical_decision: dict[str, Any], final_recommendation: dict[str, Any], rate_limit_policy: dict[str, Any] | None = None) -> None:
    redactor = RedactionService()
    document = {
        "schema_version": "gemini-profile-ablation-manual-review-v1",
        "study": study,
        "repository": repository,
        "rate_limit_policy": rate_limit_policy or {"default_requests_per_minute": DEFAULT_REQUESTS_PER_MINUTE, "hard_max_requests_per_rolling_window": MAX_ROLLING_REQUESTS, "min_interval_seconds": DEFAULT_MIN_INTERVAL_SECONDS, "concurrency": 1},
        "packets": packets,
        "profiles": profiles,
        "phase_1": phase1,
        "phase_2": phase2,
        "final_recommendation": final_recommendation,
        "historical_decision": historical_decision,
        "redaction": {"api_keys": "removed", "authorization_headers": "removed", "cookies": "removed", "private_absolute_paths": "removed"},
    }
    safe, _ = redactor.redact_evidence_value(_redact_paths(document), data_root=output.parent.parent.parent, evidence_root=output.parent)
    redactor.assert_json_redacted(safe)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


class RollingWindowRateLimiter:
    """Single-process limiter with a hard rolling-window ceiling."""

    def __init__(self, *, max_requests: int = MAX_ROLLING_REQUESTS, interval_seconds: float = 60.0, min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        if max_requests > MAX_ROLLING_REQUESTS:
            raise ValueError("experiment limiter cannot exceed 15 requests per rolling minute")
        self.max_requests = max_requests
        self.interval_seconds = interval_seconds
        self.min_interval_seconds = min_interval_seconds
        self.clock = clock
        self.sleep = sleep
        self.starts: deque[float] = deque()
        self.last_start: float | None = None
        self.events: list[dict[str, Any]] = []

    def acquire(self) -> dict[str, Any]:
        slept = 0.0
        while True:
            now = self.clock()
            while self.starts and now - self.starts[0] >= self.interval_seconds:
                self.starts.popleft()
            spacing = self.min_interval_seconds - (now - self.last_start) if self.last_start is not None else 0.0
            window_wait = self.interval_seconds - (now - self.starts[0]) if len(self.starts) >= self.max_requests else 0.0
            delay = max(0.0, spacing, window_wait)
            if delay <= 0.0:
                break
            self.sleep(delay)
            slept += delay
        started = self.clock()
        prior_count = len(self.starts)
        self.starts.append(started)
        self.last_start = started
        event = {"call_start_monotonic": started, "prior_rolling_window_count": prior_count, "sleep_seconds": round(slept, 4), "limiter_decision": "allow", "effective_requests_per_minute": len(self.starts) / max(1.0, min(self.interval_seconds, max(1.0, started - self.starts[0] + 0.001))) * 60.0}
        self.events.append(event)
        return event

    def report(self) -> dict[str, Any]:
        return {"max_requests_per_rolling_window": self.max_requests, "default_requests_per_minute": DEFAULT_REQUESTS_PER_MINUTE, "min_interval_seconds": self.min_interval_seconds, "concurrency": 1, "events": self.events}


__all__ = [
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "DEFAULT_REQUESTS_PER_MINUTE",
    "MAX_ROLLING_REQUESTS",
    "QUALITY_FLOOR_RESULTS",
    "RollingWindowRateLimiter",
    "authoritative_packet_expectations",
    "buildability_scorecard",
    "evaluate_quality_floor",
    "preserve_historical_reports",
    "profile_comparisons",
    "qualify_stable_foundation",
    "repeatability_metrics",
    "rescore_phase1_records",
    "write_manual_review_bundle",
]
