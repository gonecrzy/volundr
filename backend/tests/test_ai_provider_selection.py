import pytest

from app.api.dependencies import build_ai_provider
from app.core.config import Settings
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


def test_build_ai_provider_rejects_unknown_provider() -> None:
    settings = Settings(ai_provider="unknown")

    with pytest.raises(ValueError, match="Unsupported AI provider"):
        build_ai_provider(settings)
