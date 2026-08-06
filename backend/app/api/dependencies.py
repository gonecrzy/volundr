from pathlib import Path

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, settings
from app.services.ai.provider import AiProvider
from app.services.ai.gemini_api import GeminiApiProvider
from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.model_policy import GeminiModelPolicy
from app.services.ai.ollama import OllamaProvider
from app.services.cad.worker_client import FilesystemCadWorkerRunner
from app.services.gemini_consistency.interaction_capture import ImmutableInteractionCapture, StudyContext
from app.services.gemini_consistency.system_boundary_methods import METHOD_IDS, process_provider_text


VALIDATED_SINGLE_USER_ACTOR_ID = "volundr-single-user"


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
    study_context: StudyContext | None = None,
    study_evidence_root: Path | None = None,
    benchmark_processing: str | None = None,
    validated_transport: bool = False,
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
        if benchmark_processing is not None and benchmark_processing not in METHOD_IDS:
            raise ValueError("benchmark processing method is unsupported")
        model_policy = (
            GeminiModelPolicy.for_benchmark(config, benchmark_model)
            if benchmark_model
            else GeminiModelPolicy.from_settings(config)
        )
        interaction_recorder = None
        if study_context is not None and study_evidence_root is not None:
            capture = ImmutableInteractionCapture(study_evidence_root, study_context)

            def interaction_recorder(**payload):
                rendered_prompt = str(payload.pop("prompt", ""))
                capture.record_call(rendered_prompt=rendered_prompt, **payload)

        return GeminiApiProvider(
            # An explicit empty value prevents the module-level default from
            # leaking into a separately constructed Settings instance.
            api_key=config.gemini_api_key if config.gemini_api_key is not None else "",
            base_url=config.gemini_api_base_url,
            model=benchmark_model or config.gemini_model,
            timeout_seconds=config.gemini_timeout_seconds,
            model_policy=model_policy,
            interaction_recorder=interaction_recorder,
            response_processor=(
                lambda raw, *, stage, context: process_provider_text(
                    benchmark_processing,
                    raw,
                    stage=stage,
                    context=context,
                )
            ) if benchmark_processing is not None else None,
            validated_transport=validated_transport,
            primary_api_key=config.gemini_api_key_2,
            fallback_api_key=config.gemini_api_key,
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


def get_validated_ai_provider(provider: AiProvider = Depends(get_ai_provider)) -> AiProvider:
    """Use the existing provider boundary with the validated transport policy."""

    if not isinstance(provider, GeminiApiProvider):
        return provider
    return build_ai_provider(settings, validated_transport=True)


def get_validated_actor_id(
    x_volundr_internal_actor: str | None = Header(default=None, alias="X-Volundr-Internal-Actor"),
    x_volundr_actor_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_volundr_direct_access: str | None = Header(default=None, alias="X-Volundr-Direct-Access"),
) -> str:
    """Return the server-owned actor for the internal nginx boundary.

    Client-selected identity headers and bearer strings are never converted
    into actor IDs. The direct-access header is an explicit local-development
    override and still resolves to the same fixed single-user actor.
    """

    if x_volundr_internal_actor == VALIDATED_SINGLE_USER_ACTOR_ID:
        return VALIDATED_SINGLE_USER_ACTOR_ID
    if not settings.validated_cadquery_flow_enabled:
        return "anonymous"
    if settings.validated_api_direct_access_enabled and x_volundr_direct_access == "true":
        return VALIDATED_SINGLE_USER_ACTOR_ID
    raise HTTPException(status_code=401, detail="authentication is required")
