from pathlib import Path

from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import (
    DesignPlanRequest,
    ModelGenerationRequest,
    RequirementExtractionRequest,
    RevisionPlanRequest,
)


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


def test_legacy_initial_prompt_preserves_creative_style_intent() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_prompt(
        ModelGenerationRequest(
            project_name="Fish shelf bracket",
            original_intent=(
                "Create a functional 90 degree shelf bracket that looks like a fish "
                "from below."
            ),
            user_instruction=(
                "Build a 90 degree shelf bracket with mounting holes, but make the "
                "visible underside look like a fish."
            ),
        )
    )

    assert "Treat explicit style, theme, silhouette, and decorative requests as part of the design intent" in prompt
    assert "Build requested functional features as real geometry before adding or integrating styling" in prompt
    assert "Model requested through-holes, slots, pockets, and clearances as subtractive geometry inside difference()" in prompt
    assert "functional core" in prompt
    assert "Do not automatically simplify away requested creative or stylistic geometry" in prompt
    assert "stay literal and simple before adding secondary features" not in prompt
    assert "Do not add decorative cutouts" not in prompt


def test_legacy_initial_prompt_includes_compact_cad_pattern_examples() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_prompt(
        ModelGenerationRequest(
            project_name="Fish shelf bracket",
            original_intent="Create a functional bracket with a creative silhouette.",
            user_instruction="Make a 90 degree bracket with through holes and a fish underside.",
        )
    )

    assert "CAD PATTERN EXAMPLES" in prompt
    assert "through_hole_example" in prompt
    assert "translate([x, y, -eps]) cylinder(h = part_thickness + 2*eps" in prompt
    assert "l_bracket_core_example" in prompt
    assert "rotate([0, -90, 0])" in prompt
    assert "style_overlay_example" in prompt
    assert "keep mounting faces and holes outside decorative cuts" in prompt


def test_cadquery_repair_prompt_includes_diagnostics_and_current_source() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_cadquery_prompt(
        ModelGenerationRequest(
            project_name="Repair CadQuery probe",
            original_intent="Create a mounting plate.",
            user_instruction="Repair the CadQuery Python source.",
            current_source=(
                "import cadquery as cq\n\n"
                "plate_width = 80\n\n"
                "def build_model():\n"
                "    return cq.Workplane('XY').box(plate_width, 35, 6).holes(4)\n"
            ),
            compiler_diagnostics="AttributeError: Workplane has no attribute 'holes'",
        )
    )

    assert "cadquery-v1 source contract" in prompt
    assert "Repair mode:" in prompt
    assert "AttributeError: Workplane has no attribute 'holes'" in prompt
    assert "Current CadQuery source to repair begins below" in prompt
    assert ".holes(4)" in prompt
    assert "Return the full corrected CadQuery Python source" in prompt


def test_openscad_generation_prompts_reject_pseudo_cad_and_warning_prone_syntax() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_prompt(
        ModelGenerationRequest(
            project_name="Honeycomb bracket",
            original_intent="Create a honeycomb angle bracket.",
            user_instruction="Create a bracket with honeycomb cutouts.",
        )
    )

    assert "Use valid OpenSCAD syntax only" in prompt
    assert "Do not use pseudo-CAD method chaining" in prompt
    assert ".translate()" in prompt
    assert ".rotate()" in prompt
    assert "Do not call unknown modules such as extrude()" in prompt
    assert "use linear_extrude()" in prompt
    assert "Use PI for the circle constant; do not use lowercase pi" in prompt
    assert "Every assignment and module call must be syntactically complete" in prompt
    assert "Do not write recursive modules" in prompt
    assert "circle() accepts r or d, not r1/r2" in prompt
    assert "For thread-like or knurled details, prefer bounded approximations" in prompt
    assert "For one-piece outputs, all visible bodies must physically overlap or be joined" in prompt
    assert "Do not leave decorative silhouettes, ribs, handles, indicators, or cutout frames as loose disconnected solids" in prompt
    assert "Do not call non-existent string parsing helpers such as str_to_num" in prompt
    assert "String parameters are for labels, style choices, or selection" in prompt


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


def test_legacy_revision_prompt_allows_requested_stylistic_revision() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_prompt(
        ModelGenerationRequest(
            project_name="Fish shelf bracket",
            original_intent="Create a functional shelf bracket.",
            user_instruction="Revise the underside silhouette so it looks like a fish.",
            current_source="module main_model() {\n  cube([100, 50, 5]);\n}\nmain_model();\n",
        )
    )

    assert "If the user requests a stylistic or functional redesign, make that requested change" in prompt
    assert "Treat explicit style, theme, silhouette, and decorative requests as part of the design intent" in prompt
    assert "make the smallest necessary change" not in prompt


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

    assert provider.prompt_template_version_for(request) == "openscad-generation-v3"
    assert "The Design Specification is the authoritative design source" in prompt
    assert "@volundr-requirement <design_spec_requirement_id>" in prompt
    assert "@volundr-feature <design_spec_requirement_id>" in prompt
    assert "@volundr-geometry type=hole_group" in prompt
    assert "Secondary raw user request" in prompt
    assert "hole_spacing" in prompt
    assert "Use valid OpenSCAD syntax only" in prompt
    assert "Do not use pseudo-CAD method chaining" in prompt
    assert "Use PI for the circle constant; do not use lowercase pi" in prompt


def test_design_plan_prompt_is_json_only_and_product_model_aware() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = DesignPlanRequest(
        project_name="Configurable bracket",
        original_intent="Create functional products.",
        user_instruction="Create a configurable L bracket.",
        design_specification={
            "purpose": "Configurable bracket",
            "critical_dimensions": [{"id": "leg_length", "value": 60, "protected": True}],
        },
        defaults={"units": "mm"},
    )

    prompt = provider.build_design_plan_prompt(request)

    assert provider.design_plan_prompt_template_version() == "design-plan-v1"
    assert "Return JSON only. Do not generate OpenSCAD." in prompt
    assert "parameters, derived parameters, dependency edges, components, features, presets" in prompt
    assert "printable_outputs" in prompt
    assert "design_level" in prompt


def test_planned_openscad_prompt_uses_approved_design_plan_as_authority() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Planned bracket",
        original_intent="Create functional products.",
        user_instruction="Raw text is secondary.",
        design_specification={
            "purpose": "Configurable bracket",
            "critical_dimensions": [{"id": "leg_length", "value": 60, "protected": True}],
        },
        design_plan={
            "design_level": "product",
            "parameters": [{"id": "leg_length", "editable": True, "protected": True}],
            "dependency_edges": [{"from": "leg_length", "to": "hole_margin", "relationship": "margin"}],
            "components": [{"id": "bracket_body"}],
            "features": [{"id": "mounting_holes"}],
            "printable_outputs": [{"id": "bracket_output", "component_ids": ["bracket_body"]}],
        },
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "openscad-generation-v5"
    assert "approved Parametric Design Plan" in prompt
    assert "@volundr-component <design_plan_component_id>" in prompt
    assert "@volundr-dependency <from_parameter_id> -> <to_parameter_id>" in prompt
    assert "@volundr-output <output_id> module=<module_name>" in prompt
    assert "selected_output" in prompt
    assert "render_selected_output();" in prompt
    assert "assertions for invalid configurations" in prompt
    assert "prefer additive construction of explicit base, side walls, rails" in prompt
    assert "positive overlap with its supporting component" in prompt
    assert "Use valid OpenSCAD syntax only" in prompt
    assert "Do not use pseudo-CAD method chaining" in prompt
    assert "Use PI for the circle constant; do not use lowercase pi" in prompt


def test_design_plan_prompt_separates_source_values_from_derived_dimensions() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_design_plan_prompt(
        DesignPlanRequest(
            project_name="Tray carrier",
            original_intent="Carry tackle trays.",
            user_instruction="Carry three trays.",
            design_specification={
                "critical_dimensions": [
                    {"id": "tray_height", "value": 45, "unit": "mm", "protected": True}
                ]
            },
        )
    )

    assert "source_requirement_id must copy that source requirement's value and unit" in prompt
    assert "calculated stack, envelope, or overall product dimensions" in prompt


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

    assert provider.prompt_template_version_for(request) == "contract-repair-v2"
    assert "contract repair, not design revision" in prompt
    assert "@volundr-requirement <id>" in prompt
    assert "@volundr-geometry markers" in prompt
    assert "Protected value changed" in prompt


def test_contract_repair_prompt_preserves_design_plan_output_selector() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Repair planned source",
        original_intent="Create a carrying case.",
        user_instruction="Create planned outputs.",
        current_source='selected_output = "body";\nmodule render_selected_output() {}\nmain_model();',
        contract_diagnostics="Missing final render_selected_output() call",
        design_specification={"critical_dimensions": []},
        design_plan={"printable_outputs": [{"id": "body"}]},
    )

    prompt = provider.build_prompt(request)

    assert "Ensure the file ends with exactly one top-level render_selected_output(); call." in prompt
    assert "Ensure module main_model() exists" not in prompt


def test_revision_plan_prompt_is_json_only_and_dependency_aware() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = RevisionPlanRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Make the lid 4 mm thick.",
        reason="user_request",
        base_revision_id="rev-1",
        design_specification={"purpose": "Hold a PCB", "critical_dimensions": []},
        design_plan={
            "parameters": [{"id": "lid_thickness", "value": 3}],
            "dependency_edges": [{"from": "lid_thickness", "to": "lid_lip_depth"}],
            "components": [{"id": "lid"}],
            "features": [{"id": "lid_lip", "component_id": "lid"}],
            "printable_outputs": [{"id": "lid", "component_ids": ["lid"]}],
        },
        output_manifest={"outputs": [{"output_id": "lid", "filename": "lid.stl"}]},
        source_metadata={"parameter_names": ["lid_thickness"], "module_names": ["lid"]},
    )

    prompt = provider.build_revision_plan_prompt(request)

    assert provider.revision_plan_prompt_template_version() == "revision-planning-v1"
    assert "Return JSON only. Do not generate OpenSCAD." in prompt
    assert "Use the Design Plan dependency graph" in prompt
    assert "allowed_parameter_changes" in prompt
    assert "protected_outputs" in prompt
    assert "success_criteria" in prompt
    assert "Make the lid 4 mm thick." in prompt


def test_structured_revision_prompt_is_bounded_by_approved_revision_plan() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Make the lid 4 mm thick.",
        current_source='selected_output = "lid";\nmodule lid() { cube([80, 50, 3]); }\nrender_selected_output();',
        design_specification={"purpose": "Hold a PCB"},
        design_plan={"printable_outputs": [{"id": "lid"}]},
        revision_plan={
            "summary": "Increase lid thickness only",
            "allowed_parameter_changes": ["lid_thickness"],
            "protected_outputs": ["body"],
        },
        output_manifest={"outputs": [{"output_id": "body"}, {"output_id": "lid"}]},
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "openscad-revision-v2"
    assert "The Revision Plan is the only authority for what may change." in prompt
    assert "Preserve all protected requirement, component, feature, dependency, geometry, and output markers." in prompt
    assert "Retain every planned printable output" in prompt
    assert "Do not simplify away difficult features" in prompt
    assert "Increase lid thickness only" in prompt


def test_component_revision_prompt_uses_scoped_context_and_complete_source() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Revise the lid grip.",
        current_source='selected_output = "lid";\nmodule body() { cube([80, 50, 20]); }\nmodule lid() { cube([80, 50, 3]); }\nrender_selected_output();',
        design_specification={"purpose": "Hold a PCB"},
        design_plan={"printable_outputs": [{"id": "body"}, {"id": "lid"}]},
        revision_plan={
            "summary": "Modify lid only",
            "targeted_components": ["lid"],
            "targeted_outputs": ["lid"],
            "protected_outputs": ["body"],
        },
        output_manifest={"outputs": [{"output_id": "body"}, {"output_id": "lid"}]},
        scoped_revision_context={
            "targeted_components": ["lid"],
            "target_modules": ["lid"],
            "protected_outputs": ["body"],
            "protected_modules": ["body"],
            "allowed_shared_modules": [],
        },
        configuration_context={
            "override_manifest": {"openscad_defines": {"body_width": 90}},
        },
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "openscad-component-revision-v1"
    assert "Return the complete authoritative SCAD source" in prompt
    assert "Edit only targeted components" in prompt
    assert "Preserve protected component modules" in prompt
    assert "Active configuration context" in prompt
    assert '"protected_modules": [' in prompt


def test_scope_correction_prompt_is_not_compile_or_contract_repair() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Revise the lid grip.",
        current_source="module body() { cube([80, 60, 20]); }",
        revision_plan={"summary": "Modify lid only", "protected_outputs": ["body"]},
        scoped_revision_context={"protected_modules": ["body"], "target_modules": ["lid"]},
        scope_diagnostics='[{"rule_id":"revision.protected_module_changed"}]',
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "scope-correction-v1"
    assert "This is scope correction, not a new design revision." in prompt
    assert "Revert unauthorized edits" in prompt
    assert "Return complete authoritative SCAD source" in prompt
