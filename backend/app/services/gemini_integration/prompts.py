from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1, require_integration_profile


@dataclass(frozen=True)
class RenderedIntegrationPrompt:
    stage: str
    prompt_version: str
    prompt: str
    prompt_hash: str


GEOMETRY_T5_PROMPT_VERSION = "T5-geometry-exact-slot-contract-v1"
GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION = "T5-geometry-exact-slot-contract-v2-parameter-map"


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


def render_geometry_prompt_v2(
    profile: GeminiFlashLiteContractV1,
    request: Any,
) -> RenderedIntegrationPrompt:
    """Render the isolated T5 geometry contract without changing production routing."""

    require_integration_profile(profile.profile_id)
    if not request.geometry_slot_manifest and request.geometry_contract != "volundr-geometry-slots-v1":
        raise ValueError("T5 geometry validation requires an authoritative slot manifest")
    provider = GeminiCliProvider(model=profile.model)
    base_prompt = provider.build_geometry_slots_prompt(request)
    manifest = request.geometry_slot_manifest or {}
    contract_slots = []
    for slot in manifest.get("slots", []) or []:
        if not isinstance(slot, dict):
            continue
        contract_slots.append({
            "slot_id": slot.get("slot_id"),
            "result_symbol": str(slot.get("required_result") or ""),
            "allowed_input_symbols": [str(item) for item in slot.get("signature", []) or []],
            "required_inputs": [str(item) for item in slot.get("required_inputs", []) or []],
            "authorized_parameter_ids": [str(item) for item in slot.get("authorized_parameter_ids", []) or []],
            "required_feature_ids": [str(item) for item in slot.get("required_feature_ids", []) or []],
        })
    appendix = (
        "\n\nGEOMETRY CONTRACT REVISION: T5-geometry-exact-slot-contract-v1\n"
        "Return exactly one JSON object with schema_version and slots. Do not use Markdown or code fences.\n"
        "The following manifest identity table is authoritative:\n"
        f"{json.dumps(contract_slots, indent=2, sort_keys=True)}\n"
        "Protocol rules:\n"
        "1. Return exactly one slot for every supplied manifest slot.\n"
        "2. Copy every slot_id exactly, including its type and value.\n"
        "3. Copy every required result_symbol exactly.\n"
        "4. Do not add or omit slots.\n"
        "5. Return statements only for the assigned responsibility of that slot.\n"
        "6. Use only the authoritative input symbols in that slot signature, the listed authorized parameter IDs through params, approved helpers, and symbols defined earlier in the same slot.\n"
        "7. Every statement must be executable Python using a valid CadQuery API available to the Volundr runtime.\n"
        "8. The final geometry-changing statement must assign the required result symbol; later statements must read the updated result when applicable.\n"
        "9. Do not use generic result, shape, output, or model targets unless that exact name is authoritative for the slot.\n"
        "10. Do not return a source file, imports, functions, Markdown, prose, placeholders, ellipses, or work for another slot.\n"
        "11. Preserve protected numeric values and Boolean intent exactly. Do not repair, redesign, or supplement another slot.\n"
        "Before returning, verify every slot ID, result symbol, referenced name, Python statement, CadQuery call, assigned responsibility, and final result symbol against the authoritative manifest.\n"
        "Local variable names, intermediate solids, statement counts, workplanes, orientations, and valid construction strategies remain provider-owned."
    )
    prompt = base_prompt + appendix
    return RenderedIntegrationPrompt(
        stage="geometry",
        prompt_version=GEOMETRY_T5_PROMPT_VERSION,
        prompt=prompt,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


def render_geometry_prompt_parameter_access_v1(
    profile: GeminiFlashLiteContractV1,
    request: Any,
) -> RenderedIntegrationPrompt:
    """Render the single candidate T5 revision for the params accessor only."""

    base = render_geometry_prompt_v2(profile, request)
    appendix = (
        "\n\nPARAMETER ACCESS CLARIFICATION: T5-geometry-exact-slot-contract-v2-parameter-map\n"
        "params is a mapping supplied to every slot.\n"
        "For an authorized parameter ID, read its value only with the exact bracket form "
        '`params["<authorized_parameter_id>"]`.\n'
        "Attribute access such as `params.fact_0` is invalid and must not be emitted.\n"
        "Do not access unauthorized parameter IDs, infer missing values, or change parameter names.\n"
        "This clarification changes only parameter accessor syntax. Do not otherwise constrain geometry strategy."
    )
    prompt = base.prompt + appendix
    return RenderedIntegrationPrompt(
        stage="geometry",
        prompt_version=GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION,
        prompt=prompt,
        prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    )


__all__ = [
    "GEOMETRY_T5_PROMPT_VERSION",
    "GEOMETRY_T5_PARAMETER_ACCESS_PROMPT_VERSION",
    "RenderedIntegrationPrompt",
    "render_geometry_prompt_parameter_access_v1",
    "render_geometry_prompt_v2",
    "render_integration_prompt",
]
