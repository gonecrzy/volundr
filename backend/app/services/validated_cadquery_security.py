"""Small security primitives for the product-facing validated workflow."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import unquote


def canonical_idempotency_hash(operation_type: str, idempotency_key: str, payload: object) -> str:
    canonical = json.dumps(
        {"operation": operation_type, "key": idempotency_key, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_relative_artifact_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise ValueError("artifact path is invalid")
    decoded = relative
    for _ in range(3):
        next_value = unquote(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    if "\x00" in decoded:
        raise ValueError("artifact path is invalid")
    normalized = decoded.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        raise ValueError("artifact path must be relative")
    parts = tuple(part for part in normalized.split("/") if part not in {"", "."})
    if any(part == ".." for part in parts):
        raise ValueError("artifact path traversal is not allowed")
    root_resolved = root.resolve()
    candidate = (root_resolved.joinpath(*parts)).resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError("artifact path escapes durable storage")
    # A registered artifact may not rely on a symlink at any path component.
    current = root_resolved
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink artifacts are not allowed")
    return candidate


def redact_sensitive_text(value: str) -> str:
    return value.replace("GEMINI_API_KEY_2", "[credential-env]").replace("GEMINI_API_KEY", "[credential-env]")


def redact_sensitive_payload(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        rendered = value
        for secret in secrets:
            if secret:
                rendered = rendered.replace(secret, "[redacted]")
        return rendered
    if isinstance(value, list):
        return [redact_sensitive_payload(item, secrets) for item in value]
    if isinstance(value, dict):
        return {str(key): redact_sensitive_payload(item, secrets) for key, item in value.items()}
    return value
