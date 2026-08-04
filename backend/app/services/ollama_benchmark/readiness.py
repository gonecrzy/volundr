from __future__ import annotations

from collections.abc import Iterable
import json
import re
from typing import Any


def classify_installation_path(
    *,
    source_kind: str,
    server_supports_pull: bool,
    host_access: bool,
) -> str:
    if source_kind == "ollama_registry" and server_supports_pull:
        return "api_registry_install"
    if source_kind == "huggingface_gguf" and server_supports_pull:
        return "api_huggingface_gguf_install"
    if host_access:
        return "host_import_available"
    return "host_import_required"


def evaluate_sustained_generation(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    observations = list(runs)
    failures = [item for item in observations if item.get("status") != "success" or not item.get("stream_complete")]
    generated_tokens = [item.get("generated_tokens") for item in observations if isinstance(item.get("generated_tokens"), (int, float))]
    verified = len(observations) >= 3 and not failures and all(int(value) > 0 for value in generated_tokens)
    return {
        "verification_status": "sustained_generation_verified" if verified else "rejected",
        "accepted_slow_model": verified,
        "run_count": len(observations),
        "failure_count": len(failures),
        "generated_tokens": generated_tokens,
    }


def evaluate_installation_gate(models: Iterable[dict[str, Any]]) -> dict[str, Any]:
    model_list = list(models)
    admitted = [item for item in model_list if item.get("verification_status") == "admitted"]
    specialist = [item for item in admitted if "specialist" in str(item.get("purpose", "")).casefold()]
    generic = [item for item in admitted if "generic coding baseline" in str(item.get("purpose", "")).casefold()]
    if not specialist:
        raise ValueError("formal benchmark requires at least one admitted CAD specialist")
    if not generic:
        raise ValueError("formal benchmark requires the admitted generic Qwen baseline")
    return {
        "required_models": len(model_list),
        "installed": len(admitted),
        "specialist_count": len(specialist),
        "generic_baseline_count": len(generic),
        "formal_benchmark_authorized": True,
    }


def classify_structured_output(text: str) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return "malformed_json"
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return "malformed_json"
        return "prose_wrapped_json" if _is_structured_success(payload) else "valid_json_wrong_schema"
    return "native_schema_success" if _is_structured_success(payload) else "valid_json_wrong_schema"


def _is_structured_success(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("status") == "ok" and payload.get("items") == [1, 2, 3]


def classify_production_slot_output(text: str, *, expected_slot_ids: list[str]) -> str:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return "production_slot_invalid"
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), list):
        return "production_slot_invalid"
    slots = payload["slots"]
    if {item.get("slot_id") for item in slots if isinstance(item, dict)} != set(expected_slot_ids):
        return "production_slot_invalid"
    for slot in slots:
        if not isinstance(slot, dict) or not isinstance(slot.get("statements"), list) or not isinstance(slot.get("result_symbol"), str):
            return "production_slot_invalid"
        body = "\n".join(str(statement) for statement in slot["statements"])
        if re.search(r"\b(import|def|return|class|exec|eval)\b|subprocess|open\s*\(", body):
            return "production_slot_invalid"
    return "production_slot_compatible"


def classify_native_cad_output(text: str) -> str:
    if "import cadquery as cq" not in text or not re.search(r"\bresult\s*=", text):
        return "native_cad_invalid"
    if "```" in text or re.search(r"(?:subprocess|socket|requests|urllib|os\.system|open\s*\()", text):
        return "native_cad_invalid"
    return "native_cad_capable"
