from pathlib import Path

from app.core.config import Settings, settings
from app.services.ai.provider import AiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.ollama import OllamaProvider
from app.services.cad.runner import OpenScadCliRunner


def get_data_dir() -> Path:
    return settings.data_dir


def get_cad_runner() -> OpenScadCliRunner:
    return OpenScadCliRunner()


def build_ai_provider(config: Settings) -> AiProvider:
    provider = config.ai_provider.strip().lower()
    if provider in {"ollama", "local_ollama"}:
        return OllamaProvider(
            base_url=config.ollama_base_url,
            model=config.ollama_model,
            timeout_seconds=config.ollama_timeout_seconds,
        )
    if provider in {"gemini", "gemini_cli"}:
        return GeminiCliProvider(
            binary=config.gemini_binary,
            model=config.gemini_model,
            timeout_seconds=config.gemini_timeout_seconds,
            policy_path=config.gemini_policy_path,
        )
    raise ValueError(f"Unsupported AI provider: {config.ai_provider}")


def get_ai_provider() -> AiProvider:
    return build_ai_provider(settings)
