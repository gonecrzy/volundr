from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ModelGenerationRequest:
    project_name: str
    original_intent: str
    user_instruction: str
    current_source: str | None = None
    compiler_diagnostics: str | None = None
    generation_contract_version: str = "v1"


@dataclass(frozen=True)
class ModelGenerationResult:
    raw_output: str
    provider: str
    provider_model: str | None = None


class AiProvider(Protocol):
    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        ...
