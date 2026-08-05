from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1


@dataclass(frozen=True)
class RenderedIntegrationPrompt:
    stage: str
    prompt_version: str
    prompt: str
    prompt_hash: str


_REQUIREMENTS_T2_APPENDIX = (
    "\n\nCorrection contract: if a fit-critical fact is missing or unknown, "
    "set clarification_required=true, set generation_ready=false, ask for "
    "each missing fact explicitly, and do not insert a numeric default as a "
    "user requirement. A safe clarification stop is valid provider behavior."
)


def render_integration_prompt(
    profile: GeminiFlashLiteContractV1,
    stage: str,
    request: Any,
) -> RenderedIntegrationPrompt:
    version = profile.stage_prompt_versions.get(stage)
    if version is None:
        raise ValueError(f"unsupported integration stage: {stage}")
    provider = GeminiCliProvider(model=profile.model)
    if stage == "requirements":
        prompt = provider.build_requirement_prompt(request) + _REQUIREMENTS_T2_APPENDIX
    elif stage == "plan":
        prompt = provider.build_design_plan_prompt(request)
    elif stage == "geometry":
        if request.geometry_slot_manifest or request.geometry_contract == "volundr-geometry-slots-v1":
            prompt = provider.build_geometry_slots_prompt(request)
        else:
            prompt = provider.build_scaffold_geometry_prompt(request)
    else:
        raise ValueError(f"unsupported integration stage: {stage}")
    return RenderedIntegrationPrompt(
        stage=stage,
        prompt_version=version,
        prompt=prompt,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


__all__ = ["RenderedIntegrationPrompt", "render_integration_prompt"]
