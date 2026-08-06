from app.api.dependencies import build_executable_ai_provider
from app.api.validated_cadquery import _service
from app.core.config import Settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService


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


def test_executable_prompt_requires_complete_source_envelope() -> None:
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

    assert "executable-cadquery-response-v1" in prompt
    assert "complete executable source" in prompt
    assert "Return JSON only" in prompt
    assert "source fragments" not in prompt


def test_executable_flag_selects_experimental_workflow_service(monkeypatch, tmp_path) -> None:
    from app.api import validated_cadquery

    monkeypatch.setattr(validated_cadquery.settings, "executable_cadquery_flow_enabled", True)

    service = _service(db=None, data_dir=tmp_path)

    assert isinstance(service, ExecutableCadQueryWorkflowService)
