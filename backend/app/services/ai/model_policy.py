from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ ships tomllib.
    tomllib = None  # type: ignore[assignment]


GEMINI_ROUTING_POLICY_VERSION = "gemini-stage-routing-v1"
BUILTIN_GEMINI_MODEL = "gemini-3.5-flash-lite"
BUILTIN_GEMINI_TEMPERATURE = 0.2
BUILTIN_GEMINI_MAX_OUTPUT_TOKENS = 8192
BUILTIN_GEMINI_THINKING_LEVEL = "minimal"
BUILTIN_GEMINI_MAX_RETRIES = 2
BUILTIN_GEMINI_MAX_RETRY_SLEEP_SECONDS = 60.0
_MODEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")

_LEGACY_POLICY_FIELDS = {
    "gemini_requirements_model": "requirements_model",
    "gemini_design_plan_model": "design_plan_model",
    "gemini_geometry_model": "geometry_model",
    "gemini_geometry_repair_model": "geometry_repair_model",
    "gemini_revision_planning_model": "revision_planning_model",
    "gemini_component_revision_model": "component_revision_model",
    "gemini_api_temperature": "temperature",
    "gemini_api_max_output_tokens": "max_output_tokens",
    "gemini_api_thinking_level": "thinking_level",
    "gemini_api_max_retries": "max_retries",
    "gemini_api_max_retry_sleep_seconds": "max_retry_sleep_seconds",
}


class PromptMode(StrEnum):
    REQUIREMENTS = "requirements"
    DESIGN_PLAN = "design_plan"
    CADQUERY_GEOMETRY_BODIES = "cadquery_geometry_bodies"
    CADQUERY_GEOMETRY_BODY_REPAIR = "cadquery_geometry_body_repair"
    REVISION_PLANNING = "revision_planning"
    CADQUERY_COMPONENT_REVISION = "cadquery_component_revision"


@dataclass(frozen=True)
class ModelRoutingDecision:
    prompt_mode: PromptMode
    provider: str
    selected_model: str
    policy_version: str
    routing_reason: str
    fallback_chain: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_mode": self.prompt_mode.value,
            "provider": self.provider,
            "selected_model": self.selected_model,
            "policy_version": self.policy_version,
            "routing_reason": self.routing_reason,
            "fallback_chain": list(self.fallback_chain),
        }


@dataclass(frozen=True)
class GeminiModelPolicy:
    general_model: str
    requirements_model: str | None = None
    design_plan_model: str | None = None
    geometry_model: str | None = None
    geometry_repair_model: str | None = None
    revision_planning_model: str | None = None
    component_revision_model: str | None = None
    temperature: float = BUILTIN_GEMINI_TEMPERATURE
    max_output_tokens: int = BUILTIN_GEMINI_MAX_OUTPUT_TOKENS
    thinking_level: str | None = BUILTIN_GEMINI_THINKING_LEVEL
    max_retries: int = BUILTIN_GEMINI_MAX_RETRIES
    max_retry_sleep_seconds: float = BUILTIN_GEMINI_MAX_RETRY_SLEEP_SECONDS
    provider: str = "gemini_api"
    policy_version: str = GEMINI_ROUTING_POLICY_VERSION

    def __post_init__(self) -> None:
        self._validate_model(self.general_model)
        for model in (
            self.requirements_model,
            self.design_plan_model,
            self.geometry_model,
            self.geometry_repair_model,
            self.revision_planning_model,
            self.component_revision_model,
        ):
            if model is not None:
                self._validate_model(model)
        if not isinstance(self.temperature, (int, float)):
            raise ValueError("Gemini temperature must be numeric")
        if self.temperature < 0:
            raise ValueError("Gemini temperature must not be negative")
        if not isinstance(self.max_output_tokens, int):
            raise ValueError("Gemini max output tokens must be an integer")
        if self.max_output_tokens <= 0:
            raise ValueError("Gemini max output tokens must be positive")
        if not isinstance(self.max_retries, int):
            raise ValueError("Gemini max retries must be an integer")
        if not isinstance(self.max_retry_sleep_seconds, (int, float)):
            raise ValueError("Gemini retry sleep limit must be numeric")
        if self.max_retries < 0:
            raise ValueError("Gemini max retries must not be negative")
        if self.max_retry_sleep_seconds < 0:
            raise ValueError("Gemini retry sleep limit must not be negative")

    @classmethod
    def from_settings(cls, configured: Any, *, general_model: str | None = None) -> GeminiModelPolicy:
        values: dict[str, Any] = {
            "general_model": general_model or configured.gemini_model or BUILTIN_GEMINI_MODEL,
            "requirements_model": None,
            "design_plan_model": None,
            "geometry_model": None,
            "geometry_repair_model": None,
            "revision_planning_model": None,
            "component_revision_model": None,
            "temperature": BUILTIN_GEMINI_TEMPERATURE,
            "max_output_tokens": BUILTIN_GEMINI_MAX_OUTPUT_TOKENS,
            "thinking_level": BUILTIN_GEMINI_THINKING_LEVEL,
            "max_retries": BUILTIN_GEMINI_MAX_RETRIES,
            "max_retry_sleep_seconds": BUILTIN_GEMINI_MAX_RETRY_SLEEP_SECONDS,
        }

        policy_path = getattr(configured, "gemini_policy_path", None)
        file_values = cls._load_policy_file(policy_path)
        values.update(file_values)

        for settings_field, policy_field in _LEGACY_POLICY_FIELDS.items():
            legacy_value = getattr(configured, settings_field, None)
            if legacy_value is None:
                continue
            builtin_value = {
                "temperature": BUILTIN_GEMINI_TEMPERATURE,
                "max_output_tokens": BUILTIN_GEMINI_MAX_OUTPUT_TOKENS,
                "thinking_level": BUILTIN_GEMINI_THINKING_LEVEL,
                "max_retries": BUILTIN_GEMINI_MAX_RETRIES,
                "max_retry_sleep_seconds": BUILTIN_GEMINI_MAX_RETRY_SLEEP_SECONDS,
            }.get(policy_field)
            if policy_field in {
                "requirements_model",
                "design_plan_model",
                "geometry_model",
                "geometry_repair_model",
                "revision_planning_model",
                "component_revision_model",
            }:
                legacy_is_non_default = True
            else:
                legacy_is_non_default = legacy_value != builtin_value
            if not legacy_is_non_default:
                continue
            warnings.warn(
                f"{settings_field} is a deprecated Gemini policy compatibility override; "
                "use VOLUNDR_GEMINI_POLICY_PATH instead",
                DeprecationWarning,
                stacklevel=2,
            )
            if policy_field in file_values:
                continue
            values[policy_field] = legacy_value

        return cls(**values)

    @classmethod
    def for_benchmark(cls, configured: Any, model: str) -> GeminiModelPolicy:
        """Use one explicitly selected model for every benchmark workflow stage."""

        base = cls.from_settings(configured, general_model=model)
        return cls(
            general_model=model,
            requirements_model=model,
            design_plan_model=model,
            geometry_model=model,
            geometry_repair_model=model,
            revision_planning_model=model,
            component_revision_model=model,
            temperature=base.temperature,
            max_output_tokens=base.max_output_tokens,
            thinking_level=base.thinking_level,
            max_retries=base.max_retries,
            max_retry_sleep_seconds=base.max_retry_sleep_seconds,
            provider=base.provider,
            policy_version=base.policy_version,
        )

    @classmethod
    def _load_policy_file(cls, policy_path: str | Path | None) -> dict[str, Any]:
        if not policy_path:
            return {}
        path = Path(policy_path)
        if not path.is_file():
            raise ValueError(f"Gemini policy file does not exist: {path}")
        if tomllib is None:  # pragma: no cover
            raise RuntimeError("TOML policy files require Python 3.11 or newer")
        with path.open("rb") as stream:
            document = tomllib.load(stream)
        section = document.get("model_policy", document)
        if not isinstance(section, dict):
            raise ValueError("Gemini model policy must be a TOML table")
        models = section.get("models", {})
        generation = section.get("generation", {})
        if not isinstance(models, dict) or not isinstance(generation, dict):
            raise ValueError("Gemini model policy models and generation must be TOML tables")
        aliases = {
            "general": "general_model",
            "requirements": "requirements_model",
            "design_plan": "design_plan_model",
            "geometry": "geometry_model",
            "geometry_repair": "geometry_repair_model",
            "revision_planning": "revision_planning_model",
            "component_revision": "component_revision_model",
        }
        generation_aliases = {
            "temperature": "temperature",
            "max_output_tokens": "max_output_tokens",
            "thinking_level": "thinking_level",
            "max_retries": "max_retries",
            "max_retry_sleep_seconds": "max_retry_sleep_seconds",
        }
        values: dict[str, Any] = {}
        for source_key, target_key in aliases.items():
            if source_key in models:
                values[target_key] = models[source_key]
        for source_key, target_key in generation_aliases.items():
            if source_key in generation:
                values[target_key] = generation[source_key]
        if "policy_version" in section:
            values["policy_version"] = section["policy_version"]
        return values

    def resolve(self, prompt_mode: PromptMode) -> ModelRoutingDecision:
        stage_model = {
            PromptMode.REQUIREMENTS: self.requirements_model,
            PromptMode.DESIGN_PLAN: self.design_plan_model,
            PromptMode.CADQUERY_GEOMETRY_BODIES: self.geometry_model,
            PromptMode.CADQUERY_GEOMETRY_BODY_REPAIR: self.geometry_repair_model,
            PromptMode.REVISION_PLANNING: self.revision_planning_model,
            PromptMode.CADQUERY_COMPONENT_REVISION: self.component_revision_model,
        }[prompt_mode]
        selected_model = stage_model or self.general_model
        reason = "stage_specific_model" if stage_model else "general_model_fallback"
        fallback_chain = [selected_model]
        if selected_model != self.general_model:
            fallback_chain.append(self.general_model)
        return ModelRoutingDecision(
            prompt_mode=prompt_mode,
            provider=self.provider,
            selected_model=selected_model,
            policy_version=self.policy_version,
            routing_reason=reason,
            fallback_chain=fallback_chain,
        )

    @staticmethod
    def _validate_model(model: str) -> None:
        if not isinstance(model, str) or not model or not _MODEL_IDENTIFIER.fullmatch(model):
            raise ValueError("model identifier must be a non-empty safe model identifier")

    @staticmethod
    def is_operational_failure(message: str) -> bool:
        lowered = message.lower()
        operational_markers = (
            "timed out",
            "timeout",
            "rate limit",
            "resource_exhausted",
            "quota exceeded",
            "service unavailable",
            "temporarily unavailable",
            "503",
            "502",
            "429",
            "connection refused",
            "connection reset",
        )
        return any(marker in lowered for marker in operational_markers)
