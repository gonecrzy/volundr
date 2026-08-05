from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


INTEGRATION_PROFILE_ID = "gemini_flash_lite_contract_v1"
MODEL = "gemini-3.5-flash-lite"
SECONDARY_CREDENTIAL_ENV = "GEMINI_API_KEY_2"
STAGE_PROMPT_VERSIONS = {
    "requirements": "T2-requirements-missing-fit-v1",
    "plan": "T0-current",
    "geometry": "T0-current",
}
STAGE_OUTPUT_TOKENS = {
    "requirements": 8192,
    "plan": 8192,
    "geometry": 8192,
}


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def require_integration_profile(profile_id: str) -> str:
    """Reject normal provider names before any integration side effect."""

    if profile_id != INTEGRATION_PROFILE_ID:
        raise ValueError(
            "an integration profile is required; expected "
            f"{INTEGRATION_PROFILE_ID!r}"
        )
    return profile_id


@dataclass(frozen=True)
class GeminiFlashLiteContractV1:
    profile_id: str
    model: str
    settings: dict[str, Any]
    thinking_configuration: None
    stage_prompt_versions: dict[str, str]
    stage_output_tokens: dict[str, int]
    source_hashes: dict[str, str]
    settings_hash: str

    @classmethod
    def from_repository(cls, repository_root: Path) -> "GeminiFlashLiteContractV1":
        repository_root = repository_root.resolve()
        source = repository_root / "backend/app/services/ai/gemini_cli.py"
        source_hashes = {
            "backend/app/services/ai/gemini_cli.py": hashlib.sha256(source.read_bytes()).hexdigest()
        }
        settings = {
            "temperature": 0.2,
            "topP": 0.95,
            "topK": 40,
            "candidateCount": 1,
        }
        return cls(
            profile_id=INTEGRATION_PROFILE_ID,
            model=MODEL,
            settings=settings,
            thinking_configuration=None,
            stage_prompt_versions=dict(STAGE_PROMPT_VERSIONS),
            stage_output_tokens=dict(STAGE_OUTPUT_TOKENS),
            source_hashes=source_hashes,
            settings_hash=_hash({"model": MODEL, "settings": settings}),
        )

    def __post_init__(self) -> None:
        require_integration_profile(self.profile_id)
        if self.model != MODEL:
            raise ValueError(f"integration profile is frozen to {MODEL}")
        if self.thinking_configuration is not None:
            raise ValueError("H1 provider-default must omit thinkingConfig")
        if self.settings != {
            "temperature": 0.2,
            "topP": 0.95,
            "topK": 40,
            "candidateCount": 1,
        }:
            raise ValueError("integration settings do not match S0-current-explicit")

    def request_configuration(self, stage: str) -> dict[str, Any]:
        if stage not in self.stage_output_tokens:
            raise ValueError(f"unsupported integration stage: {stage}")
        generation_config = {
            **self.settings,
            "maxOutputTokens": self.stage_output_tokens[stage],
        }
        return {"model": self.model, "generationConfig": generation_config}

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model": self.model,
            "settings": dict(self.settings),
            "thinking_configuration": self.thinking_configuration,
            "stage_prompt_versions": dict(self.stage_prompt_versions),
            "stage_output_tokens": dict(self.stage_output_tokens),
            "source_hashes": dict(self.source_hashes),
            "settings_hash": self.settings_hash,
            "credential_policy": {
                "environment_variable": SECONDARY_CREDENTIAL_ENV,
                "credential_slot": "secondary",
                "primary_fallback": False,
            },
        }

