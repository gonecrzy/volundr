from app.api.dependencies import build_executable_ai_provider
from app.api.validated_cadquery import _service
from app.core.config import Settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService


def test_executable_provider_uses_explicit_primary_and_disabled_fallback_slots() -> None:
    configured = Settings(
        _env_file=None,
        ai_provider="gemini_api",
        gemini_api_key="approved-primary-secret",
        gemini_api_key_2="invalid-secondary-secret",
        gemini_primary_credential_env="GEMINI_API_KEY",
        gemini_fallback_credential_env="",
    )

    provider = build_executable_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.api_key == "approved-primary-secret"
    assert provider.primary_api_key == "approved-primary-secret"
    assert provider.fallback_api_key is None
    metadata = provider.provider_settings()
    assert metadata["primary_credential"]["environment_variable"] == "GEMINI_API_KEY"
    assert metadata["fallback_credential"]["environment_variable"] is None
    assert "approved-primary-secret" not in str(metadata)
    assert "invalid-secondary-secret" not in str(metadata)


def test_executable_flow_is_disabled_by_default_and_gemini_remains_default() -> None:
    configured = Settings(_env_file=None)

    assert configured.executable_cadquery_flow_enabled is False
    assert configured.ai_provider == "gemini_api"
    assert configured.validated_cadquery_flow_enabled is False


def test_executable_provider_ignores_codex_geometry_selection() -> None:
    configured = Settings(
        _env_file=None,
        ai_provider="gemini_api",
        gemini_api_key="fixture-key",
        gemini_api_key_2="fixture-key-2",
        validated_geometry_provider="codex_proxy",
        codex_api_key="must-not-be-used",
        codex_api_base_url="https://codex.invalid",
        codex_model="codex-test",
    )

    provider = build_executable_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.provider_id == "gemini_api"
    assert provider.validated_transport is True


def test_executable_prompt_requires_one_complete_raw_source_module() -> None:
    request = ModelGenerationRequest(
        project_name="Mounting bracket",
        original_intent="fixture",
        user_instruction="fixture",
        executable_design_contract={
            "schema_version": "executable-cadquery-design-contract-v1",
            "outputs": [{"output_id": "mounting_bracket", "required": True}],
        },
    )
    provider = GeminiCliProvider(model="gemini-test")

    prompt = provider.build_cadquery_prompt(request)

    assert "executable-cadquery-complete-source-v3" in prompt
    assert "exactly one complete executable raw Python module" in prompt
    assert "Return raw Python source only" in prompt
    assert "Do not return JSON" in prompt
    assert "source fragments" not in prompt
    assert "cadquery-v1-source-dialect" in prompt
    assert "Canonical cadquery-v1 source skeleton" in prompt
    assert "top_level_if_forbidden" not in prompt


def test_l0_prompt_contains_exact_prior_response_and_normalized_error() -> None:
    prior_response = "Here is the module:\n```python\npass\n```"
    normalized_error = "response_empty_or_extraction_failure: prose outside the module"
    request = ModelGenerationRequest(
        project_name="Mounting bracket",
        original_intent="fixture",
        user_instruction="fixture",
        executable_design_contract={
            "schema_version": "executable-cadquery-design-contract-v1",
            "outputs": [{"output_id": "mounting_bracket", "required": True}],
        },
        executable_repair_envelope={
            "schema_version": "executable-cadquery-repair-envelope-v1",
            "repair_level": "L0",
            "prior_provider_response": prior_response,
            "prior_normalized_error": normalized_error,
        },
    )

    prompt = GeminiCliProvider(model="gemini-test").build_cadquery_prompt(request)

    assert prior_response in prompt
    assert normalized_error in prompt


def test_executable_flag_selects_experimental_workflow_service(monkeypatch, tmp_path) -> None:
    from app.api import validated_cadquery

    monkeypatch.setattr(validated_cadquery.settings, "executable_cadquery_flow_enabled", True)

    service = _service(db=None, data_dir=tmp_path)

    assert isinstance(service, ExecutableCadQueryWorkflowService)
