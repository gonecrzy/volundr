from pathlib import Path

from fastapi import HTTPException

from app.core.config import Settings, settings
from app.services.ai.provider import AiProvider
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.ollama import OllamaProvider
from app.services.cad.worker_client import FilesystemCadWorkerRunner


def get_data_dir() -> Path:
    return settings.data_dir


def require_developer_tools() -> None:
    if not settings.developer_tools_enabled:
        raise HTTPException(status_code=403, detail="developer tools are disabled")


def get_cad_runner() -> FilesystemCadWorkerRunner:
    return FilesystemCadWorkerRunner()


def build_ai_provider(
    config: Settings,
    *,
    benchmark_provider: str | None = None,
    benchmark_model: str | None = None,
    benchmark_seed: int | None = None,
) -> AiProvider:
    provider = (benchmark_provider or config.ai_provider).strip().lower()
    if benchmark_model and provider not in {"ollama", "local_ollama", "gemini_api", "google_gemini_api", "gemini", "gemini_cli"}:
        raise ValueError("benchmark provider is unsupported for model override")
    if provider in {"ollama", "local_ollama"}:
        return OllamaProvider(
            base_url=config.ollama_base_url,
            model=benchmark_model or config.ollama_model,
            timeout_seconds=config.ollama_timeout_seconds,
            connect_timeout_seconds=config.ollama_connect_timeout_seconds,
            first_token_timeout_seconds=config.ollama_first_token_timeout_seconds,
            generation_idle_timeout_seconds=config.ollama_generation_idle_timeout_seconds,
            total_generation_timeout_seconds=config.ollama_total_generation_timeout_seconds,
            stream=config.ollama_stream,
            seed=benchmark_seed,
        )
    if provider in {"gemini_api", "google_gemini_api"}:
        model_policy = (
            GeminiModelPolicy.for_benchmark(config, benchmark_model)
            if benchmark_model
            else GeminiModelPolicy.from_settings(config)
        )
        return GeminiApiProvider(
            # An explicit empty value prevents the module-level default from
            # leaking into a separately constructed Settings instance.
            api_key=config.gemini_api_key if config.gemini_api_key is not None else "",
            base_url=config.gemini_api_base_url,
            model=benchmark_model or config.gemini_model,
            timeout_seconds=config.gemini_timeout_seconds,
            model_policy=model_policy,
        )
    if provider in {"gemini", "gemini_cli"}:
        model_policy = (
            GeminiModelPolicy.for_benchmark(config, benchmark_model)
            if benchmark_model
            else None
        )
        return GeminiCliProvider(
            binary=config.gemini_binary,
            model=benchmark_model or config.gemini_model,
            timeout_seconds=config.gemini_timeout_seconds,
            policy_path=config.gemini_policy_path,
            model_policy=model_policy,
        )
    raise ValueError(f"Unsupported AI provider: {config.ai_provider}")


def get_ai_provider() -> AiProvider:
    return build_ai_provider(settings)
