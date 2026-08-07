import json
from pathlib import Path

import pytest

from app.api.dependencies import build_ai_provider, build_validated_ai_provider
from app.core.config import Settings
from app.services.ai.codex_proxy import ValidatedGeometryProviderRouter
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.ollama import OllamaProvider
from app.services.gemini_consistency.interaction_capture import StudyContext


def test_build_ai_provider_selects_ollama() -> None:
    settings = Settings(
        ai_provider="ollama",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="qwen3.5:9b",
    )

    provider = build_ai_provider(settings)

    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.model == "qwen3.5:9b"


def test_build_ai_provider_accepts_developer_ollama_provider_and_model_override() -> None:
    configured = Settings(
        ai_provider="gemini_api",
        gemini_primary_api_key="secret-key",
        ollama_base_url="http://ollama.remote:11434",
        ollama_model="configured-model",
    )

    provider = build_ai_provider(
        configured,
        benchmark_provider="ollama",
        benchmark_model="procad:Q4_K_M",
        benchmark_seed=202,
    )

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "procad:Q4_K_M"
    assert provider.base_url == "http://ollama.remote:11434"
    assert provider.seed == 202


def test_build_ai_provider_rejects_benchmark_model_without_supported_provider() -> None:
    with pytest.raises(ValueError, match="benchmark provider"):
        build_ai_provider(Settings(ai_provider="unknown"), benchmark_model="model")


def test_build_ai_provider_selects_gemini_cli() -> None:
    settings = Settings(
        ai_provider="gemini_cli",
        gemini_binary="gemini",
        gemini_model="gemini-3.5-flash-lite",
    )

    provider = build_ai_provider(settings)

    assert isinstance(provider, GeminiCliProvider)
    assert provider.model == "gemini-3.5-flash-lite"


def test_build_ai_provider_selects_gemini_api() -> None:
    settings = Settings(
        ai_provider="gemini_api",
        gemini_primary_api_key="secret-key",
        gemini_api_base_url="https://generativelanguage.googleapis.test/v1beta",
        gemini_model="gemini-3.5-flash-lite",
    )

    provider = build_ai_provider(settings)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    assert provider.api_key == "secret-key"
    assert provider.thinking_level == "minimal"


def test_build_ai_provider_can_attach_study_interaction_capture(tmp_path: Path) -> None:
    configured = Settings(
        ai_provider="gemini_api",
        gemini_primary_api_key="secret-key",
        gemini_model="gemini-3.5-flash-lite",
    )

    provider = build_ai_provider(
        configured,
        benchmark_model="gemini-3.5-flash-lite",
        study_context=StudyContext("study", "baseline", 1, "case-001", "project", "operation"),
        study_evidence_root=tmp_path,
    )

    assert isinstance(provider, GeminiApiProvider)
    assert provider._interaction_recorder is not None


def test_minimal_gemini_api_example_builds_without_advanced_settings() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    configured = Settings(_env_file=repository_root / ".env.example")

    provider = build_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta"


def test_missing_gemini_key_is_deferred_until_live_request() -> None:
    configured = Settings(_env_file=None, ai_provider="gemini_api", gemini_primary_api_key=None)

    provider = build_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert not provider.api_key


def test_settings_loads_gemini_api_key_from_parent_env_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (tmp_path / ".env").write_text(
        "VOLUNDR_GEMINI_PRIMARY_API_KEY=parent-env-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(backend_dir)

    settings = Settings()

    assert settings.gemini_primary_api_key.get_secret_value() == "parent-env-key"


def test_build_ai_provider_rejects_unknown_provider() -> None:
    settings = Settings(ai_provider="unknown")

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        build_ai_provider(settings)


def test_validated_geometry_provider_defaults_to_gemini() -> None:
    configured = Settings(
        _env_file=None,
        ai_provider="gemini_api",
        gemini_primary_api_key="gemini-secret",
    )

    provider = build_validated_ai_provider(configured)

    assert type(provider).__name__ == "GeminiApiProvider"
    assert configured.validated_geometry_provider == "gemini_api"


def test_codex_validated_geometry_routing_keeps_gemini_upstream() -> None:
    configured = Settings(
        _env_file=None,
        ai_provider="gemini_api",
        gemini_primary_api_key="gemini-secret",
        gemini_fallback_api_key="gemini-secondary-secret",
        validated_geometry_provider="codex_proxy",
        codex_api_base_url="https://codex.test/backend-api/codex",
        codex_api_key="codex-secret",
        codex_model="gpt-5.6-luna",
        codex_api_mode="responses",
    )

    provider = build_validated_ai_provider(configured)

    assert isinstance(provider, ValidatedGeometryProviderRouter)
    assert type(provider.primary_provider).__name__ == "GeminiApiProvider"
    assert provider.primary_provider.primary_api_key == "gemini-secret"
    assert provider.geometry_provider.api_key == "codex-secret"
    assert provider.geometry_provider.model == "gpt-5.6-luna"
    assert provider.provider_id == "codex_proxy"
    assert "codex-secret" not in json.dumps(provider.primary_provider.provider_settings())
