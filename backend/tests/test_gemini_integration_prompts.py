from pathlib import Path

from app.services.ai.provider import (
    DesignPlanRequest,
    ModelGenerationRequest,
    RequirementExtractionRequest,
)
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.prompts import render_integration_prompt


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_stage_prompt_selection_uses_the_frozen_provider_contract_versions() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)

    requirement = render_integration_prompt(
        profile,
        "requirements",
        RequirementExtractionRequest(
            project_name="project-001",
            original_intent="a dimensional plate",
            user_instruction="Create a 100 mm plate.",
        ),
    )
    plan = render_integration_prompt(
        profile,
        "plan",
        DesignPlanRequest(
            project_name="project-001",
            original_intent="a dimensional plate",
            user_instruction="Create a 100 mm plate.",
            design_specification={"requirements": []},
        ),
    )
    geometry = render_integration_prompt(
        profile,
        "geometry",
        ModelGenerationRequest(
            project_name="project-001",
            original_intent="a dimensional plate",
            user_instruction="Create a 100 mm plate.",
        ),
    )

    assert "clarification_required" in requirement.prompt
    assert "Create a Design Plan for Volundr" in plan.prompt
    assert "structured CadQuery geometry bodies" in geometry.prompt
    assert requirement.prompt_version == "T2-requirements-missing-fit-v1"


def test_rendered_prompt_hashes_are_recorded_per_stage() -> None:
    profile = GeminiFlashLiteContractV1.from_repository(REPO_ROOT)
    request = RequirementExtractionRequest(
        project_name="project-002",
        original_intent="an underspecified cable guide",
        user_instruction="Create a wall-mounted cable guide.",
    )

    first = render_integration_prompt(profile, "requirements", request)
    second = render_integration_prompt(profile, "requirements", request)

    assert first.prompt == second.prompt
    assert len(first.prompt_hash) == 64
    assert first.stage == "requirements"
    assert first.prompt_version == "T2-requirements-missing-fit-v1"
