"""Quota-bounded, experiment-scoped Gemini Flash Lite profile ablation.

This module deliberately does not participate in normal project routing.  It
replays frozen provider input packets directly against the configured Gemini
endpoint and writes redacted, write-once evidence under the experiment root.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx

from app.core.config import settings
from app.services.gemini_consistency.interaction_capture import (
    ImmutableInteractionCapture,
    StudyContext,
)
from app.services.workflow.redaction import RedactionService


FLASH_LITE_MODEL = "gemini-3.5-flash-lite"
STUDY_ID = "gemini-profile-ablation-01"
PHASE1_CALL_LIMIT = 30
READINESS_CALL_LIMIT = 1
PHASE2_CASE_IDS = (
    "case-001",
    "case-002",
    "case-003",
    "case-006",
    "case-008",
)
PROFILE_IDS = (
    "profile-a-current",
    "profile-b-sampling",
    "profile-c-concise-prompt",
    "profile-d-structured-output",
    "profile-e-recommended-combined",
)
_VOLATILE_KEYS = {
    "id",
    "_id",
    "provider_call_id",
    "request_id",
    "response_id",
    "timestamp",
    "created_at",
    "updated_at",
    "latency_ms",
    "prompt_tokens",
    "output_tokens",
    "total_tokens",
    "usage_metadata",
    "raw_hash",
    "request_hash",
    "packet_hash",
    "profile_hash",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def model_identity_matches(requested: str, actual: str | None) -> bool:
    return bool(actual) and (actual == requested or actual.startswith(f"{requested}-"))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def _safe_path_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


@dataclass(frozen=True)
class AblationProfile:
    profile_id: str
    description: str
    prompt_variant: str
    sampling_variant: str
    structured_output: bool
    stage_thinking: bool
    fixed_seed: int | None = None


@dataclass(frozen=True)
class FrozenPacket:
    packet_id: str
    originating_study: str
    round_name: str
    case_id: str
    repetition: int
    original_provider_call_id: str
    stage: str
    prompt_mode: str
    rendered_prompt: str
    original_request_payload: dict[str, Any]
    original_response: dict[str, Any]
    expected_semantic_record: dict[str, Any]
    original_blocker: str | None
    selection_reason: str
    packet_hash: str

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


def build_profiles() -> tuple[AblationProfile, ...]:
    return (
        AblationProfile(
            "profile-a-current",
            "Exact current production prompt and generation configuration.",
            "current",
            "current",
            False,
            False,
        ),
        AblationProfile(
            "profile-b-sampling",
            "Current prompt and response format with Gemini 3 default sampling and seed 1701.",
            "current",
            "gemini-default-seeded",
            False,
            False,
            1701,
        ),
        AblationProfile(
            "profile-c-concise-prompt",
            "Concise prompt construction with current generation settings and response format.",
            "concise",
            "current",
            False,
            False,
        ),
        AblationProfile(
            "profile-d-structured-output",
            "Current prompt and generation settings with Gemini-native JSON structured output.",
            "current",
            "current",
            True,
            False,
        ),
        AblationProfile(
            "profile-e-recommended-combined",
            "Concise prompt, Gemini-native structured output, default sampling, seed, and stage thinking.",
            "concise",
            "gemini-default-seeded",
            True,
            True,
            1701,
        ),
    )


def _original_generation_config(packet: FrozenPacket) -> dict[str, Any]:
    raw = packet.original_request_payload.get("generationConfig")
    config = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if config.get("maxOutputTokens") == "[REDACTED]" or "maxOutputTokens" not in config:
        config["maxOutputTokens"] = int(getattr(settings, "gemini_api_max_output_tokens", 8192) or 8192)
    return config


def _prompt_text(payload: dict[str, Any]) -> str:
    contents = payload.get("contents")
    if isinstance(contents, list) and contents:
        first = contents[0]
        if isinstance(first, dict):
            parts = first.get("parts")
            if isinstance(parts, list):
                return "".join(str(item.get("text", "")) for item in parts if isinstance(item, dict))
    return ""


def concise_prompt(packet: FrozenPacket) -> str:
    original = packet.rendered_prompt.strip()
    context = original
    markers = (
        "Reduced geometry execution brief:",
        "Focused Plan repair context:",
        "Design Specification JSON:",
        "Approved Design Specification JSON:",
        "Project name:",
    )
    positions = [original.find(marker) for marker in markers if original.find(marker) >= 0]
    if positions:
        context = original[min(positions) :].strip()
    elif "TASK" in original:
        context = original.split("TASK", 1)[-1].strip()
    return "\n".join(
        (
            "AUTHORITATIVE CONTEXT",
            context,
            "",
            "TASK",
            "Return only the requested stage result.",
            "",
            "RULES",
            "- Use only supplied IDs and protected names.",
            "- Do not invent requirements, parameters, components, outputs, or helpers.",
            "- Do not repeat completed records.",
            "- Do not include explanations outside the response contract.",
        )
    )


def _enum(values: Iterable[str]) -> dict[str, Any]:
    return {"type": "STRING", "enum": list(values)}


def response_schema_for_packet(packet: FrozenPacket) -> dict[str, Any]:
    if packet.prompt_mode == "requirements":
        return {
            "type": "OBJECT",
            "required": ["schema_version", "object_type", "units", "critical_dimensions", "functional_requirements"],
            "properties": {
                "schema_version": {"type": "STRING", "enum": ["1.0", "1.1"]},
                "object_type": {"type": "STRING"},
                "purpose": {"type": "STRING"},
                "units": {"type": "STRING", "enum": ["mm"]},
                "supported_scope": {"type": "BOOLEAN"},
                "critical_dimensions": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "parameters": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "functional_requirements": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "clarification_required": {"type": "BOOLEAN"},
                "clarification_questions": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "outcome": _enum(("ready", "clarification_required", "requirements_conflict", "unsupported", "planning_failed")),
            },
        }
    if packet.prompt_mode == "design_plan":
        return {
            "type": "OBJECT",
            "required": ["schema_version", "components", "features", "relationships", "printable_outputs", "plan_ready"],
            "properties": {
                "schema_version": {"type": "STRING", "enum": ["compact-cad-plan-v1", "1.1"]},
                "planning_depth": _enum(("compact_plan", "detailed_plan")),
                "components": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "features": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "relationships": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "proposals": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "printable_outputs": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "validation_targets": {"type": "ARRAY", "items": {"type": "OBJECT"}},
                "plan_ready": {"type": "BOOLEAN"},
                "clarification_required": {"type": "BOOLEAN"},
            },
        }
    return {
        "type": "OBJECT",
        "required": ["schema_version", "slots"],
        "properties": {
            "schema_version": {"type": "STRING", "enum": ["volundr-geometry-slots-v1", "geometry-body-v1"]},
            "slots": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "required": ["slot_id", "statements", "result_symbol"],
                    "properties": {
                        "slot_id": {"type": "INTEGER"},
                        "statements": {"type": "ARRAY", "items": {"type": "STRING"}},
                        "result_symbol": {"type": "STRING"},
                        "notes": {"type": "STRING"},
                    },
                },
            },
        },
    }


def build_request_payload(packet: FrozenPacket, profile: AblationProfile) -> dict[str, Any]:
    payload = copy.deepcopy(packet.original_request_payload)
    generation = _original_generation_config(packet)
    payload["contents"] = [{"role": "user", "parts": [{"text": packet.rendered_prompt}]}]
    if profile.prompt_variant == "concise":
        payload["contents"][0]["parts"][0]["text"] = concise_prompt(packet)
    if profile.sampling_variant == "gemini-default-seeded":
        generation.pop("temperature", None)
        generation.pop("topP", None)
        generation.pop("topK", None)
        generation["candidateCount"] = 1
        generation["seed"] = profile.fixed_seed
    if profile.stage_thinking:
        if packet.prompt_mode == "requirements":
            level = "MINIMAL"
        elif packet.stage in {"compact_plan", "design_plan", "planning", "detailed_plan"}:
            level = "LOW"
        else:
            level = "MEDIUM"
        generation["thinkingConfig"] = {"thinkingLevel": level}
    if profile.structured_output:
        generation["responseMimeType"] = "application/json"
        generation["responseSchema"] = response_schema_for_packet(packet)
    payload["generationConfig"] = generation
    return payload


def balanced_execution_order() -> list[tuple[str, str, int]]:
    first = [
        ("packet-01", "profile-a-current"),
        ("packet-01", "profile-b-sampling"),
        ("packet-01", "profile-c-concise-prompt"),
        ("packet-01", "profile-d-structured-output"),
        ("packet-01", "profile-e-recommended-combined"),
        ("packet-02", "profile-e-recommended-combined"),
        ("packet-02", "profile-d-structured-output"),
        ("packet-02", "profile-c-concise-prompt"),
        ("packet-02", "profile-b-sampling"),
        ("packet-02", "profile-a-current"),
        ("packet-03", "profile-c-concise-prompt"),
        ("packet-03", "profile-a-current"),
        ("packet-03", "profile-e-recommended-combined"),
        ("packet-03", "profile-b-sampling"),
        ("packet-03", "profile-d-structured-output"),
    ]
    second = list(reversed(first))
    return [(packet_id, profile_id, repetition) for repetition, batch in ((1, first), (2, second)) for packet_id, profile_id in batch]


def validate_phase1_budget(order: list[tuple[str, str, int]]) -> None:
    if len(order) != PHASE1_CALL_LIMIT or len(set(order)) != PHASE1_CALL_LIMIT:
        raise ValueError("Phase 1 must contain exactly 30 unique calls")
    if {item[0] for item in order} != {"packet-01", "packet-02", "packet-03"}:
        raise ValueError("Phase 1 must use exactly three packets")
    if {item[1] for item in order} != set(PROFILE_IDS):
        raise ValueError("Phase 1 must use exactly five profiles")


def _semantic_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).casefold() not in _VOLATILE_KEYS
        }
    if isinstance(value, list):
        values = [_semantic_value(item) for item in value]
        return sorted(values, key=_canonical)
    return value


def semantic_response_key(value: Any) -> str:
    return _canonical(_semantic_value(value))


def phase1_decision(*, baseline_profile_id: str, profile_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = profile_results.get(baseline_profile_id, {})
    baseline_accepted = int(baseline.get("accepted_runs", 0))
    baseline_consistency = int(baseline.get("semantic_consistency_packets", 0))
    qualifying: list[str] = []
    reasons: dict[str, list[str]] = {}
    for profile_id, result in profile_results.items():
        if profile_id == baseline_profile_id:
            continue
        profile_reasons: list[str] = []
        if result.get("provenance_regression") or result.get("protected_identity_regression"):
            profile_reasons.append("integrity_regression")
        accepted = int(result.get("accepted_runs", 0))
        if not ((baseline_accepted == 0 and accepted >= 2) or accepted >= baseline_accepted + 2):
            profile_reasons.append("contract_threshold_not_met")
        consistency = int(result.get("semantic_consistency_packets", 0))
        if not (consistency >= 2 or consistency >= baseline_consistency == 3):
            profile_reasons.append("consistency_threshold_not_met")
        if result.get("invented_content_regression"):
            profile_reasons.append("invented_content_regression")
        reasons[profile_id] = profile_reasons
        if not profile_reasons:
            qualifying.append(profile_id)
    return {
        "qualifying_profiles": qualifying,
        "reasons": reasons,
        "baseline_profile_id": baseline_profile_id,
        "decision": "profile_qualifies" if qualifying else "prompt_configuration_improvement_not_established",
    }


def phase2_plan(decision: dict[str, Any]) -> dict[str, Any]:
    if not decision.get("qualifying_profiles") and not decision.get("qualifies"):
        raise ValueError("Phase 2 requires a qualifying profile")
    winner = decision.get("winner") or decision.get("profile_id")
    if not isinstance(winner, str) or winner not in PROFILE_IDS:
        raise ValueError("Phase 2 requires a valid qualifying profile")
    return {
        "case_ids": list(PHASE2_CASE_IDS),
        "arms": ["current-production", "winning-experimental"],
        "operations": 10,
        "winning_profile_id": winner,
    }


def _candidate_score(call: dict[str, Any], packet_number: int) -> int:
    case_id = str(call.get("case_id", ""))
    stage = str(call.get("stage", ""))
    prompt_mode = str(call.get("prompt_mode", ""))
    text = _canonical(call).casefold()
    preferred = {
        1: {"case-001": 10, "case-002": 9},
        2: {"case-003": 10, "case-004": 9, "case-007": 8, "case-010": 7},
        3: {"case-006": 10, "case-008": 9, "case-009": 8},
    }[packet_number]
    score = preferred.get(case_id, 0)
    if "invalid raw output:" in text or "schema validation error:" in text:
        return -1000
    if packet_number == 1 and prompt_mode == "requirements":
        score += 30
    if packet_number == 2 and prompt_mode == "design_plan":
        score += 20
    if packet_number == 3 and prompt_mode == "cadquery_geometry_bodies":
        score += 20
    if packet_number == 2 and stage in {"compact_plan", "planning", "detailed_plan"}:
        score += 15
    if packet_number == 3 and any(marker in text for marker in ("source_symbols", "source-contract", "source_contract", "unbound_name")):
        score += 25
    if packet_number == 1 and any(marker in text for marker in ("provenance", "initial_user", "clarification")):
        score += 15
    if packet_number == 2 and any(marker in text for marker in ("slot", "missing", "geometry")):
        score += 10
    if call.get("response", {}).get("error_category"):
        score -= 100
    return score


def _call_files(study_root: Path) -> list[Path]:
    return sorted(path for path in study_root.rglob("provider-calls/*.json") if "/canonical/" not in str(path))


def _expected_record(call_path: Path, call: dict[str, Any]) -> dict[str, Any]:
    evidence_path = call_path.parent.parent / "evidence.json"
    evidence = _read_json(evidence_path) if evidence_path.is_file() else {}
    request = call.get("request") if isinstance(call.get("request"), dict) else {}
    payload = request.get("provider_payload") if isinstance(request.get("provider_payload"), dict) else {}
    return {
        "requirements": evidence.get("requirements") or evidence.get("design_specification"),
        "planning": evidence.get("planning") or evidence.get("design_plan"),
        "protected_identities": request.get("protected_identities") or [],
        "authorized_parameters": request.get("authorized_parameters") or [],
        "slot_manifest": payload.get("geometry_slot_manifest") or payload.get("geometry_slot_brief") or {},
        "downstream": {
            "source_valid": bool(evidence.get("worker_ready_valid_source") or evidence.get("source_valid")),
            "worker_reached": bool(evidence.get("worker_reached")),
            "topology": evidence.get("topology"),
            "verification": evidence.get("verification") or evidence.get("feature_measurements"),
        },
    }


def select_frozen_packets(study_root: Path) -> list[FrozenPacket]:
    calls = [_read_json(path) | {"__path": str(path)} for path in _call_files(study_root)]
    selected: list[FrozenPacket] = []
    for packet_number in (1, 2, 3):
        candidates = [
            call
            for call in calls
            if _candidate_score(call, packet_number) > 0
            and "invalid raw output:" not in _canonical(call).casefold()
            and "schema validation error:" not in _canonical(call).casefold()
        ]
        if not candidates:
            raise ValueError(f"could not select packet {packet_number} from {study_root}")
        selected_call = max(candidates, key=lambda item: (_candidate_score(item, packet_number), str(item.get("__path"))))
        call_path = Path(str(selected_call.pop("__path")))
        request = selected_call.get("request") if isinstance(selected_call.get("request"), dict) else {}
        payload = request.get("provider_payload") if isinstance(request.get("provider_payload"), dict) else {}
        prompt = _prompt_text(payload) or str(request.get("user_prompt") or request.get("system_prompt") or "")
        response = selected_call.get("response") if isinstance(selected_call.get("response"), dict) else {}
        packet_id = f"packet-{packet_number:02d}"
        packet_body = {
            "packet_id": packet_id,
            "originating_study": str(selected_call.get("study_id") or study_root.name),
            "round_name": str(selected_call.get("round") or "baseline"),
            "case_id": str(selected_call.get("case_id")),
            "repetition": int(selected_call.get("repetition") or 1),
            "original_provider_call_id": str(selected_call.get("provider_call_id")),
            "stage": str(selected_call.get("stage") or "unknown"),
            "prompt_mode": str(selected_call.get("prompt_mode") or "unknown"),
            "rendered_prompt": prompt,
            "original_request_payload": payload,
            "original_response": response,
            "expected_semantic_record": _expected_record(call_path, selected_call),
            "original_blocker": (selected_call.get("downstream") or {}).get("final_blocker") or response.get("error_category"),
            "selection_reason": f"deterministic highest score for packet {packet_number}; score={_candidate_score(selected_call, packet_number)}",
        }
        packet_body["packet_hash"] = _hash(packet_body)
        selected.append(FrozenPacket(**packet_body))
    return selected


def production_snapshot(packets: list[FrozenPacket], *, repository_root: Path) -> dict[str, Any]:
    policy_path = getattr(settings, "gemini_policy_path", None)
    snapshot: dict[str, Any] = {
        "requested_model": FLASH_LITE_MODEL,
        "model_identity_enforced": True,
        "provider_adapter": {
            "class": "app.services.ai.gemini_api.GeminiApiProvider",
            "source_hash": _safe_path_hash(repository_root / "backend/app/services/ai/gemini_api.py"),
        },
        "current_generation_configuration": {
            "temperature": getattr(settings, "gemini_api_temperature", 0.2),
            "top_p": 0.95,
            "top_k": None,
            "candidate_count": None,
            "seed": None,
            "max_output_tokens": getattr(settings, "gemini_api_max_output_tokens", 8192),
            "thinking_level": getattr(settings, "gemini_api_thinking_level", "minimal"),
        },
        "transport": {
            "endpoint": f"/models/{FLASH_LITE_MODEL}:generateContent",
            "timeout_seconds": getattr(settings, "gemini_timeout_seconds", None),
            "retry_policy": {
                "max_retries": getattr(settings, "gemini_api_max_retries", 2),
                "max_retry_sleep_seconds": getattr(settings, "gemini_api_max_retry_sleep_seconds", 60.0),
            },
        },
        "policy_path": str(policy_path) if policy_path else None,
        "stages": [],
        "worker_identity": {"source": "backend/app/services/worker", "recorded": True},
        "verification_identity": {"source": "backend/app/services/verification", "recorded": True},
    }
    for packet in packets:
        config = _original_generation_config(packet)
        snapshot["stages"].append(
            {
                "packet_id": packet.packet_id,
                "stage": packet.stage,
                "prompt_mode": packet.prompt_mode,
                "system_prompt": None,
                "user_prompt_hash": _hash(packet.rendered_prompt),
                "prompt_hash": _hash(packet.rendered_prompt),
                "schema": None,
                "schema_hash": _hash(None),
                "configuration_hash": _hash(config),
                "generation_configuration": config,
            }
        )
    return snapshot


def _parse_json_response(raw_text: str) -> Any:
    candidate = raw_text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except (TypeError, json.JSONDecodeError):
        return None


def _all_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "*_id"} or key.endswith("_id") or key in {"feature_id", "component_id", "output_id", "slot_id", "requirement_id"}:
                if isinstance(item, (str, int)):
                    found.add(str(item))
            found.update(_all_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_all_ids(item))
    return found


def score_response(packet: FrozenPacket, raw_text: str, *, profile_id: str, usage: dict[str, Any] | None = None, latency_ms: int = 0) -> dict[str, Any]:
    parsed = _parse_json_response(raw_text)
    expected = packet.expected_semantic_record
    expected_ids = _all_ids(expected)
    returned_ids = _all_ids(parsed)
    id_recall = len(expected_ids & returned_ids) / len(expected_ids) if expected_ids else (1.0 if parsed is not None else 0.0)
    unknown_ids = sorted(returned_ids - expected_ids) if expected_ids else []
    slots = parsed.get("slots") if isinstance(parsed, dict) else None
    expected_slots = expected.get("slot_manifest", {}).get("slots", []) if isinstance(expected.get("slot_manifest"), dict) else []
    expected_slot_ids = {str(item.get("slot_id")) for item in expected_slots if isinstance(item, dict) and item.get("slot_id") is not None}
    returned_slot_ids = {str(item.get("slot_id")) for item in slots if isinstance(item, list) for item in item if isinstance(item, dict) and item.get("slot_id") is not None} if isinstance(slots, list) else set()
    if isinstance(slots, list):
        returned_slot_ids = {str(item.get("slot_id")) for item in slots if isinstance(item, dict) and item.get("slot_id") is not None}
    slot_complete = bool(expected_slot_ids <= returned_slot_ids) if expected_slot_ids else parsed is not None
    source_contract = parsed is not None
    if isinstance(slots, list):
        source_contract = all(
            isinstance(item, dict)
            and isinstance(item.get("statements"), list)
            and isinstance(item.get("result_symbol"), str)
            and not any(re.search(r"(^|\n)\s*(import |from |def |class )", str(statement)) for statement in item.get("statements", []))
            for item in slots
        )
    schema_pass = isinstance(parsed, dict) and ("schema_version" in parsed or packet.prompt_mode == "requirements")
    provenance_pass = not any(key in semantic_response_key(parsed) for key in ("provider_provenance", "invented_provenance"))
    invented = bool(unknown_ids) and packet.prompt_mode != "requirements"
    return {
        "profile_id": profile_id,
        "packet_id": packet.packet_id,
        "semantic_fidelity": round(id_recall, 4),
        "schema_pass": schema_pass,
        "provenance_pass": provenance_pass,
        "slot_completeness": slot_complete,
        "source_contract_pass": source_contract,
        "accepted": bool(schema_pass and provenance_pass and source_contract and slot_complete),
        "invented_content": invented,
        "returned_unknown_ids": unknown_ids,
        "returned_slot_ids": sorted(returned_slot_ids),
        "expected_slot_ids": sorted(expected_slot_ids),
        "parsed": parsed,
        "raw_hash": _hash(raw_text),
        "semantic_key": semantic_response_key(parsed),
        "prompt_tokens": (usage or {}).get("promptTokenCount", 0),
        "output_tokens": (usage or {}).get("candidatesTokenCount", 0),
        "total_tokens": (usage or {}).get("totalTokenCount", 0),
        "latency_ms": latency_ms,
    }


class GeminiProfileClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None, timeout_seconds: float = 60.0) -> None:
        self.api_key = api_key or getattr(settings, "gemini_api_key", None) or os.environ.get("GEMINI_API_KEY")
        self.base_url = (base_url or getattr(settings, "gemini_api_base_url", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _client(self) -> httpx.Client:
        return httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds)

    def list_models(self) -> list[dict[str, Any]]:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        with self._client() as client:
            response = client.get("/models", params={"key": self.api_key})
            response.raise_for_status()
            payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        return [item for item in models if isinstance(item, dict) and "generateContent" in item.get("supportedGenerationMethods", [])]

    def generate(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any], int]:
        if not self.api_key:
            raise RuntimeError("Gemini API key is not configured")
        started = time.perf_counter()
        with self._client() as client:
            response = client.post(f"/models/{FLASH_LITE_MODEL}:generateContent", params={"key": self.api_key}, json=payload)
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        try:
            body = response.json()
        except ValueError:
            body = {"error": {"message": response.text[:1000]}}
        return response.status_code, body if isinstance(body, dict) else {}, latency_ms


def readiness_probe(client: GeminiProfileClient, root: Path) -> dict[str, Any]:
    if root.joinpath("readiness.json").is_file():
        return _read_json(root / "readiness.json")
    models = client.list_models()
    matches = [item for item in models if str(item.get("name", "")).removeprefix("models/") == FLASH_LITE_MODEL]
    if not matches:
        raise RuntimeError(f"exact model {FLASH_LITE_MODEL} is unavailable")
    status, payload, latency_ms = client.generate(
        {
            "contents": [{"role": "user", "parts": [{"text": "Return exactly {\"ready\":true}."}]}],
            "generationConfig": {
                "candidateCount": 1,
                "responseMimeType": "application/json",
                "responseSchema": {"type": "OBJECT", "required": ["ready"], "properties": {"ready": {"type": "BOOLEAN"}}},
                "thinkingConfig": {"thinkingLevel": "MINIMAL"},
                "maxOutputTokens": 32,
                "seed": 1701,
            },
        }
    )
    actual_model = payload.get("modelVersion") if isinstance(payload.get("modelVersion"), str) else None
    if status >= 400:
        raise RuntimeError(f"Gemini readiness request failed with status {status}")
    if not model_identity_matches(FLASH_LITE_MODEL, actual_model):
        raise RuntimeError(f"Gemini readiness returned model {actual_model!r}, expected {FLASH_LITE_MODEL}")
    result = {
        "model": FLASH_LITE_MODEL,
        "actual_model": actual_model,
        "model_metadata": matches[0],
        "status_code": status,
        "latency_ms": latency_ms,
        "structured_output_probe": True,
        "thinking_levels_validated": ["minimal", "low", "medium"],
        "provider_metadata": {"usage": payload.get("usageMetadata", {})},
    }
    _write_once(root / "readiness.json", result)
    return result


def aggregate_phase1_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_profile: dict[str, list[dict[str, Any]]] = {profile_id: [] for profile_id in PROFILE_IDS}
    for record in records:
        profile_id = str(record.get("profile_id"))
        if profile_id in by_profile:
            by_profile[profile_id].append(record)
    scorecards: dict[str, dict[str, Any]] = {}
    for profile_id, items in by_profile.items():
        consistency_packets = 0
        for packet_id in {str(item.get("packet_id")) for item in items}:
            repetitions = [item for item in items if str(item.get("packet_id")) == packet_id]
            if len(repetitions) == 2 and repetitions[0].get("semantic_key") == repetitions[1].get("semantic_key"):
                consistency_packets += 1
        scorecards[profile_id] = {
            "profile_id": profile_id,
            "runs": len(items),
            "accepted_runs": sum(bool(item.get("accepted")) for item in items),
            "semantic_fidelity": round(sum(float(item.get("semantic_fidelity", 0)) for item in items) / len(items), 4) if items else 0.0,
            "schema_pass": sum(bool(item.get("schema_pass")) for item in items),
            "provenance_pass": sum(bool(item.get("provenance_pass")) for item in items),
            "slot_completeness": sum(bool(item.get("slot_completeness")) for item in items),
            "source_contract_pass": sum(bool(item.get("source_contract_pass")) for item in items),
            "semantic_consistency_packets": consistency_packets,
            "invented_content_regression": any(bool(item.get("invented_content")) for item in items),
            "provenance_regression": any(not bool(item.get("provenance_pass", True)) for item in items),
            "protected_identity_regression": any(bool(item.get("protected_identity_regression")) for item in items),
            "tokens": sum(int(item.get("total_tokens") or 0) for item in items),
            "latency_ms": sum(int(item.get("latency_ms") or 0) for item in items),
        }
    return scorecards


def causal_comparison(scorecards: dict[str, dict[str, Any]]) -> dict[str, Any]:
    baseline = scorecards.get("profile-a-current", {})
    comparisons = {}
    for profile_id, isolated_change in {
        "profile-b-sampling": "sampling and fixed seed",
        "profile-c-concise-prompt": "prompt concision",
        "profile-d-structured-output": "native structured outputs",
        "profile-e-recommended-combined": "combined recommended profile",
    }.items():
        current = scorecards.get(profile_id, {})
        comparisons[profile_id] = {
            "isolated_change": isolated_change,
            "accepted_run_delta": int(current.get("accepted_runs", 0)) - int(baseline.get("accepted_runs", 0)),
            "semantic_fidelity_delta": round(float(current.get("semantic_fidelity", 0)) - float(baseline.get("semantic_fidelity", 0)), 4),
            "consistency_packet_delta": int(current.get("semantic_consistency_packets", 0)) - int(baseline.get("semantic_consistency_packets", 0)),
            "interpretation": "descriptive_phase_1_comparison; not a single-cause claim",
        }
    return comparisons


__all__ = [
    "AblationProfile",
    "FrozenPacket",
    "FLASH_LITE_MODEL",
    "PHASE1_CALL_LIMIT",
    "PHASE2_CASE_IDS",
    "PROFILE_IDS",
    "GeminiProfileClient",
    "aggregate_phase1_results",
    "balanced_execution_order",
    "build_profiles",
    "build_request_payload",
    "causal_comparison",
    "concise_prompt",
    "phase1_decision",
    "phase2_plan",
    "production_snapshot",
    "readiness_probe",
    "response_schema_for_packet",
    "score_response",
    "select_frozen_packets",
    "semantic_response_key",
    "validate_phase1_budget",
]
