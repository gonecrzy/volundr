from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


GEMINI_ROUTING_POLICY_VERSION = "gemini-stage-routing-v1"
_MODEL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")


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

    @classmethod
    def from_settings(cls, configured: Any, *, general_model: str | None = None) -> GeminiModelPolicy:
        return cls(
            general_model=general_model or configured.gemini_model,
            requirements_model=configured.gemini_requirements_model,
            design_plan_model=configured.gemini_design_plan_model,
            geometry_model=configured.gemini_geometry_model,
            geometry_repair_model=configured.gemini_geometry_repair_model,
            revision_planning_model=configured.gemini_revision_planning_model,
            component_revision_model=configured.gemini_component_revision_model,
        )

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
