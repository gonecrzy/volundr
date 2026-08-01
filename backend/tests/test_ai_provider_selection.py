from pathlib import Path

import pytest

from app.api.dependencies import build_ai_provider
from app.core.config import Settings
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.ollama import OllamaProvider


def test_build_ai_provider_selects_ollama() -> None:
    settings = Settings(
        ai_provider="ollama",
        ollama_base_url="http://10.1.20.25:11434",
        ollama_model="qwen3.5:9b",
    )

    provider = build_ai_provider(settings)

    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://10.1.20.25:11434"
    assert provider.model == "qwen3.5:9b"


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
        gemini_api_key="secret-key",
        gemini_api_base_url="https://generativelanguage.googleapis.test/v1beta",
        gemini_model="gemini-3.5-flash-lite",
    )

    provider = build_ai_provider(settings)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    assert provider.api_key == "secret-key"
    assert provider.thinking_level == "minimal"


def test_minimal_gemini_api_example_builds_without_advanced_settings() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    configured = Settings(_env_file=repository_root / ".env.example")

    provider = build_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert provider.model == "gemini-3.5-flash-lite"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta"


def test_missing_gemini_key_is_deferred_until_live_request() -> None:
    configured = Settings(_env_file=None, ai_provider="gemini_api", gemini_api_key=None)

    provider = build_ai_provider(configured)

    assert isinstance(provider, GeminiApiProvider)
    assert not provider.api_key


def test_settings_loads_gemini_api_key_from_parent_env_file(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (tmp_path / ".env").write_text("GEMINI_API_KEY=parent-env-key\n", encoding="utf-8")
    monkeypatch.chdir(backend_dir)

    settings = Settings()

    assert settings.gemini_api_key == "parent-env-key"


def test_build_ai_provider_rejects_unknown_provider() -> None:
    settings = Settings(ai_provider="unknown")

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        build_ai_provider(settings)
