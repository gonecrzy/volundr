from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.workflow.redaction import RedactionService


SCHEMA_VERSION = "volundr-provider-contract-integration-v1"


class IntegrationEvidenceStore:
    def __init__(self, root: Path, *, study_id: str) -> None:
        self.root = Path(root)
        self.study_id = study_id
        self.captures_root = self.root / "captures"
        self.captures_root.mkdir(parents=True, exist_ok=True)
        self.redactor = RedactionService()

    def _path(self, category: str, identity: str) -> Path:
        safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in identity)
        return self.captures_root / category / f"{safe}.json"

    def _write_idempotent(self, category: str, identity: str, value: dict[str, Any]) -> dict[str, Any]:
        path = self._path(category, identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        redacted = self.redactor.redact_mapping(value, artifact_type="integration_evidence")
        redacted["study_id"] = self.study_id
        path.write_text(json.dumps(redacted, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return redacted

    def record_provider_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        attempt_id = str(attempt.get("attempt_id") or "")
        if not attempt_id:
            raise ValueError("provider attempt needs an attempt_id")
        return self._write_idempotent("provider-attempts", attempt_id, attempt)

    def record_boundary(self, boundary: dict[str, Any]) -> dict[str, Any]:
        identity = str(boundary.get("boundary_id") or boundary.get("operation_id") or "")
        if not identity:
            raise ValueError("boundary evidence needs a boundary_id or operation_id")
        return self._write_idempotent("boundaries", identity, boundary)

    def provider_attempts(self) -> list[dict[str, Any]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.captures_root / "provider-attempts").glob("*.json"))
        ]

    def boundaries(self) -> list[dict[str, Any]]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.captures_root / "boundaries").glob("*.json"))
        ]


def build_combined_bundle(store: IntegrationEvidenceStore, **sections: Any) -> dict[str, Any]:
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "study": {"study_id": store.study_id},
        "repository": sections.get("repository", {}),
        "provider_profile": sections.get("provider_profile", {}),
        "projects": sections.get("projects", []),
        "provider_attempts": store.provider_attempts(),
        "worker_jobs": sections.get("worker_jobs", []),
        "project_outcomes": sections.get("project_outcomes", []),
        "issues": sections.get("issues", []),
        "causal_graph": sections.get("causal_graph", {}),
        "counterfactuals": sections.get("counterfactuals", []),
        "differential_replays": sections.get("differential_replays", []),
        "ownership_summary": sections.get("ownership_summary", {}),
        "priority_ranking": sections.get("priority_ranking", []),
        "next_action": sections.get("next_action", {}),
        "rate_limit": sections.get("rate_limit", {}),
        "retry_summary": sections.get("retry_summary", {}),
        "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"},
        "boundaries": store.boundaries(),
    }
    return bundle


__all__ = ["IntegrationEvidenceStore", "SCHEMA_VERSION", "build_combined_bundle"]

