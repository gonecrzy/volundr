from pathlib import Path

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest


SNAPSHOT_DIR = Path(__file__).parent / "fixtures" / "prompt_snapshots"


def read_snapshot(name: str) -> str:
    return (SNAPSHOT_DIR / name).read_text(encoding="utf-8").rstrip("\n")


def test_legacy_initial_prompt_matches_snapshot() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_prompt(
        ModelGenerationRequest(
            project_name="Generated cube",
            original_intent="Create a calibration cube.",
            user_instruction="Create a 10mm cube with named parameters.",
        )
    )

    assert provider.prompt_template_version_for(
        ModelGenerationRequest(
            project_name="Generated cube",
            original_intent="Create a calibration cube.",
            user_instruction="Create a 10mm cube with named parameters.",
        )
    ) == "legacy-initial-v1"
    assert provider.gemini_ruleset_version == "gemini-ruleset-v1"
    assert prompt.rstrip("\n") == read_snapshot("legacy_initial.txt")


def test_legacy_revision_prompt_matches_snapshot() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Resize generated part",
        original_intent="Create a configurable block.",
        user_instruction="Make it 20 mm wide while preserving the other dimensions.",
        current_source="module main_model() {\n  cube([10, 10, 10]);\n}\nmain_model();\n",
    )

    assert provider.prompt_template_version_for(request) == "legacy-revision-v1"
    assert provider.build_prompt(request).rstrip("\n") == read_snapshot("legacy_revision.txt")


def test_legacy_repair_prompt_matches_snapshot() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Repairable output",
        original_intent="Create a generated part.",
        user_instruction="Create a cube.",
        current_source="module main_model() {\n  broken(\n}\nmain_model();\n",
        compiler_diagnostics="Parser error: syntax error",
    )

    assert provider.prompt_template_version_for(request) == "legacy-compile-repair-v1"
    assert provider.build_prompt(request).rstrip("\n") == read_snapshot("legacy_repair.txt")
