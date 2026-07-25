from pathlib import Path

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import ModelGenerationRequest, RequirementExtractionRequest


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


def test_requirement_prompt_is_json_only_and_clarification_capable() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = RequirementExtractionRequest(
        project_name="Bottle holder",
        original_intent="Create practical FDM parts.",
        user_instruction="Make this bottle fit on the wall.",
        defaults={"units": "mm", "general_functional_wall_thickness_mm": 3.0},
    )

    prompt = provider.build_requirement_prompt(request)

    assert provider.requirement_prompt_template_version() == "requirements-v1"
    assert "Return JSON only. Do not generate OpenSCAD." in prompt
    assert "clarification_required" in prompt
    assert "Do not silently invent critical dimensions" in prompt


def test_staged_openscad_prompt_uses_design_specification_as_authority() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Mounting plate",
        original_intent="Create a plate.",
        user_instruction="Raw text is secondary.",
        design_specification={
            "purpose": "Mount a controller",
            "critical_dimensions": [
                {
                    "id": "hole_spacing",
                    "value": 60,
                    "unit": "mm",
                    "source": "user",
                    "protected": True,
                }
            ],
        },
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "openscad-generation-v2"
    assert "The Design Specification is the authoritative design source" in prompt
    assert "@volundr-requirement <design_spec_requirement_id>" in prompt
    assert "@volundr-feature <design_spec_requirement_id>" in prompt
    assert "Secondary raw user request" in prompt
    assert "hole_spacing" in prompt


def test_contract_repair_prompt_is_bounded_and_marker_aware() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Repair source contract",
        original_intent="Create a mounting plate.",
        user_instruction="Create a plate with holes.",
        current_source="module main_model() {\n  cube([10, 10, 2]);\n}\nmain_model();\n",
        contract_diagnostics="Protected value changed: expected 60, detected 55",
        design_specification={"critical_dimensions": [{"id": "hole_spacing", "value": 60, "protected": True}]},
    )
    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "contract-repair-v1"
    assert "contract repair, not design revision" in prompt
    assert "@volundr-requirement <id>" in prompt
    assert "Protected value changed" in prompt
