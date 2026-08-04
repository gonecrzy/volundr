"""Immutable, redacted evidence for individual Gemini provider attempts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.workflow.redaction import RedactionService


FIXTURE_VERSION = "gemini-live-response-v1"


@dataclass(frozen=True)
class StudyContext:
    study_id: str
    round: str
    repetition: int
    case_id: str
    project_id: str
    user_operation_id: str
    workflow_id: str | None = None
    provider: str = "gemini_api"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class ImmutableInteractionCapture:
    """Write-once provider-call records under a private study evidence root."""

    def __init__(self, root: Path, context: StudyContext) -> None:
        self.root = root
        self.context = context
        self.redactor = RedactionService()
        self.calls_root = (
            root
            / context.round
            / f"repetition-{context.repetition:02d}"
            / "projects"
            / context.case_id
            / context.project_id
            / "provider-calls"
        )
        self.calls_root.mkdir(parents=True, exist_ok=True)

    def _path(self, provider_call_id: str) -> Path:
        return self.calls_root / f"{provider_call_id}.json"

    def write_existing(self, provider_call_id: str, payload: dict[str, Any]) -> bool:
        """Attempt a write without ever replacing an existing call record."""

        path = self._path(provider_call_id)
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
        except FileExistsError:
            return False
        return True

    def record_call(
        self,
        *,
        stage: str,
        prompt_mode: str,
        requested_model: str,
        actual_model: str | None,
        rendered_prompt: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | None,
        raw_text: str | None,
        status_code: int | None,
        provider_metadata: dict[str, Any] | None,
        usage_metadata: dict[str, Any] | None,
        latency_ms: int,
        finish_reason: str | None = None,
        transport_retries: int = 0,
        error_category: str | None = None,
        prompt_version: str = "unknown",
        configuration_hash: str = "unknown",
    ) -> tuple[str, Path]:
        provider_call_id = str(uuid4())
        safe_request, request_findings = self.redactor.redact_evidence_value(
            request_payload,
            data_root=self.root,
            evidence_root=self.root,
        )
        safe_prompt, prompt_findings = self.redactor.normalize_evidence_text(
            rendered_prompt,
            data_root=self.root,
            evidence_root=self.root,
        )
        safe_response, response_findings = self.redactor.redact_evidence_value(
            response_payload or {},
            data_root=self.root,
            evidence_root=self.root,
        )
        safe_raw, raw_findings = self.redactor.normalize_evidence_text(
            raw_text or "",
            data_root=self.root,
            evidence_root=self.root,
        )
        findings = [*request_findings, *prompt_findings, *response_findings, *raw_findings]
        generation_config = safe_request.get("generationConfig", {}) if isinstance(safe_request, dict) else {}
        accepted = status_code is not None and status_code < 400 and bool(safe_raw)
        record = {
            "fixture_version": FIXTURE_VERSION,
            **asdict(self.context),
            "stage": stage,
            "stage_attempt": transport_retries + 1,
            "provider_call_id": provider_call_id,
            "provider": self.context.provider,
            "requested_model": requested_model,
            "actual_model": actual_model,
            "prompt_mode": prompt_mode,
            "prompt_version": prompt_version,
            "configuration_hash": configuration_hash,
            "request_hash": _sha256(safe_request),
            "request": {
                "requested_model": requested_model,
                "system_prompt": safe_prompt,
                "user_prompt": safe_prompt,
                "structured_schema": safe_request.get("responseSchema") if isinstance(safe_request, dict) else None,
                "generation_settings": generation_config,
                "provider_payload": safe_request,
                "context_artifact_ids": [],
                "authorized_parameters": [],
                "protected_identities": [],
            },
            "response": {
                "raw_text": safe_raw,
                "raw_provider_payload": safe_response,
                "finish_reason": finish_reason,
                "provider_metadata": provider_metadata or {},
                "prompt_tokens": (usage_metadata or {}).get("promptTokenCount", 0),
                "output_tokens": (usage_metadata or {}).get("candidatesTokenCount", 0),
                "total_tokens": (usage_metadata or {}).get("totalTokenCount", 0),
                "usage_metadata": usage_metadata or {},
                "latency_ms": latency_ms,
                "transport_retries": transport_retries,
                "status_code": status_code,
                "error_category": error_category,
            },
            "processing": {
                "parse_classification": "provider_failure" if error_category else "captured_raw_response",
                "syntax_repair": None,
                "normalized_response": None,
                "normalization_rules": [],
                "findings_before_normalization": [],
                "findings_after_normalization": [],
                "repair_eligibility": False,
                "accepted": accepted,
            },
            "downstream": {
                "source_assembled": False,
                "source_valid": False,
                "worker_reached": False,
                "worker_result": None,
                "topology_result": None,
                "verification_result": None,
                "candidate_state": None,
                "final_blocker": "provider_failure" if error_category else None,
            },
            "redaction": {
                "status": "passed" if not findings else "normalized",
                "rules_version": self.redactor.version,
                "finding_count": len(findings),
            },
        }
        safe_record, record_findings = self.redactor.redact_evidence_value(
            record,
            data_root=self.root,
            evidence_root=self.root,
        )
        self.redactor.assert_json_redacted(safe_record)
        self.write_existing(provider_call_id, safe_record)
        return provider_call_id, self._path(provider_call_id)
