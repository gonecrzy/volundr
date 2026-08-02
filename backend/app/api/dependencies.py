from pathlib import Path

from app.core.config import Settings, settings
from app.services.ai.provider import AiProvider
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.ollama import OllamaProvider
from app.services.cad.worker_client import FilesystemCadWorkerRunner


def get_data_dir() -> Path:
    return settings.data_dir


def get_cad_runner() -> FilesystemCadWorkerRunner:
    return FilesystemCadWorkerRunner()


def build_ai_provider(config: Settings) -> AiProvider:
    provider = config.ai_provider.strip().lower()
    if provider in {"ollama", "local_ollama"}:
        return OllamaProvider(
            base_url=config.ollama_base_url,
            model=config.ollama_model,
            timeout_seconds=config.ollama_timeout_seconds,
        )
    if provider in {"gemini_api", "google_gemini_api"}:
        model_policy = GeminiModelPolicy.from_settings(config)
        return GeminiApiProvider(
            # An explicit empty value prevents the module-level default from
            # leaking into a separately constructed Settings instance.
            api_key=config.gemini_api_key if config.gemini_api_key is not None else "",
            base_url=config.gemini_api_base_url,
            model=config.gemini_model,
            timeout_seconds=config.gemini_timeout_seconds,
            model_policy=model_policy,
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
