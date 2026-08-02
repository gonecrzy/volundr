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


def test_builtin_generation_policy_loads_without_a_policy_file() -> None:
    from app.core.config import Settings

    policy = GeminiModelPolicy.from_settings(Settings(_env_file=None))

    assert policy.general_model == "gemini-3.5-flash-lite"
    assert policy.temperature == 0.2
    assert policy.max_output_tokens == 8192
    assert policy.thinking_level == "minimal"
    assert policy.max_retries == 2
    assert policy.max_retry_sleep_seconds == 60.0


def test_policy_file_overrides_builtin_generation_policy(tmp_path) -> None:
    from app.core.config import Settings

    policy_file = tmp_path / "gemini-policy.toml"
    policy_file.write_text(
        """
[model_policy.models]
geometry = "geometry-model-from-file"

[model_policy.generation]
temperature = 0.05
max_output_tokens = 4096
thinking_level = "low"
max_retries = 4
max_retry_sleep_seconds = 12
""".strip(),
        encoding="utf-8",
    )

    policy = GeminiModelPolicy.from_settings(
        Settings(_env_file=None, gemini_policy_path=policy_file)
    )

    assert policy.geometry_model == "geometry-model-from-file"
    assert policy.temperature == 0.05
    assert policy.max_output_tokens == 4096
    assert policy.thinking_level == "low"
    assert policy.max_retries == 4
    assert policy.max_retry_sleep_seconds == 12.0


def test_legacy_policy_environment_values_are_compatibility_overrides(tmp_path) -> None:
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VOLUNDR_GEMINI_GEOMETRY_MODEL=legacy-geometry",
                "VOLUNDR_GEMINI_API_TEMPERATURE=0.15",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="compatibility"):
        policy = GeminiModelPolicy.from_settings(Settings(_env_file=env_file))

    assert policy.geometry_model == "legacy-geometry"
    assert policy.temperature == 0.15


def test_policy_file_wins_over_legacy_policy_environment(tmp_path) -> None:
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text(
        "VOLUNDR_GEMINI_GEOMETRY_MODEL=legacy-geometry\n",
        encoding="utf-8",
    )
    policy_file = tmp_path / "gemini-policy.toml"
    policy_file.write_text(
        "[model_policy.models]\ngeometry = 'file-geometry'\n",
        encoding="utf-8",
    )

    with pytest.warns(DeprecationWarning, match="compatibility"):
        policy = GeminiModelPolicy.from_settings(
            Settings(_env_file=env_file, gemini_policy_path=policy_file)
        )

    assert policy.geometry_model == "file-geometry"
