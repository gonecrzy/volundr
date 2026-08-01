import pytest

from app.services.ai.model_policy import (
    GEMINI_ROUTING_POLICY_VERSION,
    GeminiModelPolicy,
    PromptMode,
)


def test_stage_specific_models_override_general_model() -> None:
    policy = GeminiModelPolicy(
        general_model="fast-general",
        requirements_model="fast-requirements",
        design_plan_model="fast-plan",
        geometry_model="strong-geometry",
        geometry_repair_model="strong-repair",
        revision_planning_model=None,
        component_revision_model="strong-component",
    )

    decision = policy.resolve(PromptMode.CADQUERY_GEOMETRY_BODIES)

    assert decision.selected_model == "strong-geometry"
    assert decision.fallback_chain == ["strong-geometry", "fast-general"]
    assert decision.routing_reason == "stage_specific_model"
    assert decision.policy_version == GEMINI_ROUTING_POLICY_VERSION


def test_unset_stage_model_uses_general_fallback() -> None:
    policy = GeminiModelPolicy(general_model="fast-general")

    decision = policy.resolve(PromptMode.REVISION_PLANNING)

    assert decision.selected_model == "fast-general"
    assert decision.fallback_chain == ["fast-general"]
    assert decision.routing_reason == "general_model_fallback"


def test_geometry_repair_and_component_revision_have_distinct_stage_models() -> None:
    policy = GeminiModelPolicy(
        general_model="fast-general",
        geometry_model="strong-geometry",
        geometry_repair_model="strong-repair",
        component_revision_model="strong-component",
    )

    assert policy.resolve(PromptMode.CADQUERY_GEOMETRY_BODY_REPAIR).selected_model == "strong-repair"
    assert policy.resolve(PromptMode.CADQUERY_COMPONENT_REVISION).selected_model == "strong-component"


def test_model_identifiers_are_validated() -> None:
    with pytest.raises(ValueError, match="model identifier"):
        GeminiModelPolicy(general_model="")

    with pytest.raises(ValueError, match="model identifier"):
        GeminiModelPolicy(general_model="fast model")


@pytest.mark.parametrize(
    "message",
    [
        "Gemini API request timed out after 120 seconds",
        "503 UNAVAILABLE service unavailable",
        "429 RESOURCE_EXHAUSTED quota exceeded",
    ],
)
def test_operational_provider_failure_may_use_fallback(message: str) -> None:
    assert GeminiModelPolicy.is_operational_failure(message)


@pytest.mark.parametrize(
    "message",
    [
        "structured geometry body missing required function",
        "mounting_screw_count has no verified geometry effect",
    ],
)
def test_content_failure_is_not_operational_fallback(message: str) -> None:
    assert not GeminiModelPolicy.is_operational_failure(message)
