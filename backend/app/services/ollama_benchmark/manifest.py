from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_FIELDS = {
    "model_id",
    "display_name",
    "priority",
    "purpose",
    "source_kind",
    "source_repository",
    "source_revision",
    "source_filename",
    "source_checksum",
    "license",
    "installation_method",
    "ollama_name",
    "ollama_digest",
    "parameter_size",
    "quantization",
    "file_size_bytes",
    "target_context",
    "installation_status",
    "verification_status",
    "exclusion_reason",
}

ALLOWED_INSTALLATION_STATUSES = frozenset(
    {"pending", "downloading", "downloaded", "importing", "installed", "verified", "failed", "excluded"}
)
ALLOWED_VERIFICATION_STATUSES = frozenset(
    {"not_tested", "identity_verified", "load_verified", "sustained_generation_verified", "slot_compatible", "native_only", "admitted", "rejected"}
)


def load_model_manifest(path: Path) -> dict[str, Any]:
    """Load the JSON-compatible YAML manifest without adding a YAML dependency."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_model_manifest(payload)
    return payload


def validate_model_manifest(payload: dict[str, Any]) -> None:
    if payload.get("version") != "ollama-models-v1":
        raise ValueError("model manifest version must be ollama-models-v1")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError("model manifest must contain models")
    seen: set[str] = set()
    for item in models:
        if not isinstance(item, dict) or not REQUIRED_FIELDS <= set(item):
            raise ValueError("each model manifest entry must contain every required field")
        model_id = item["model_id"]
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            raise ValueError("model manifest model_id values must be unique and non-empty")
        seen.add(model_id)
        if item["installation_status"] not in ALLOWED_INSTALLATION_STATUSES:
            raise ValueError(f"invalid installation status for {model_id}")
        if item["verification_status"] not in ALLOWED_VERIFICATION_STATUSES:
            raise ValueError(f"invalid verification status for {model_id}")

