from app.services.ai.gemini_cli import GeminiCliProvider
from app.services.ai.provider import (
    DesignPlanRequest,
    ModelGenerationRequest,
    RequirementExtractionRequest,
    RevisionPlanRequest,
)


def test_cadquery_initial_prompt_uses_product_contract() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Generated cube",
        original_intent="Create a calibration cube.",
        user_instruction="Create a 10mm cube with named parameters.",
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "cadquery-generation-v1"
    assert provider.ruleset_version == "gemini-ruleset-v1"
    assert "You generate CadQuery Python for Volundr." in prompt
    assert "Return only a single fenced python block" in prompt
    assert "Follow the cadquery-v1 source contract" in prompt
    assert "from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product" in prompt
    assert "Define `def build(params):`" in prompt
    assert "Return exactly one `Product`" in prompt
    assert "Do not define `build_model()`" in prompt


def test_cadquery_prompt_guides_mathless_connected_creative_geometry() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    prompt = provider.build_cadquery_prompt(
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

    assert "Do not import or use `math`" in prompt
    assert "Do not wrap fillet(), chamfer(), or optional details in try/except" in prompt
    assert "Use fixed point lists or CadQuery polygon/spline profiles instead of sin/cos loops" in prompt
    assert "Do not call `map()`, `.split()`, or parse string parameters" in prompt
    assert "If `thread_spec` is requested, expose it as a numeric millimeter diameter" in prompt
    assert "Extrude only closed profiles" in prompt
    assert "For indicator slots, use `rect(indicator_width, length).extrude(depth)`" in prompt
    assert "Prefer one extruded 2D profile for creative one-piece brackets" in prompt
    assert "Return the main fused solid directly, not a Compound of loose solids" in prompt


def test_cadquery_repair_prompt_includes_diagnostics_and_current_source() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
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

    prompt = provider.build_cadquery_prompt(request)

    assert provider.prompt_template_version_for(request) == "cadquery-generation-v1"
    assert "Repair mode:" in prompt
    assert "AttributeError: Workplane has no attribute 'holes'" in prompt
    assert "Current CadQuery source to repair begins below" in prompt
    assert ".holes(4)" in prompt
    assert "Return the full corrected CadQuery Python source" in prompt


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
    assert "Return JSON only. Do not generate CAD source." in prompt
    assert "clarification_required" in prompt
    assert "Do not silently invent critical dimensions" in prompt


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
    assert "Return JSON only. Do not generate CAD source." in prompt
    assert "parameters, derived parameters, dependency edges, components, features, presets" in prompt
    assert "printable_outputs" in prompt
    assert "design_level" in prompt


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


def test_cadquery_contract_repair_prompt_is_bounded() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Repair source contract",
        original_intent="Create a mounting plate.",
        user_instruction="Create a plate with holes.",
        current_source="import cadquery as cq\n",
        contract_diagnostics="Protected value changed: expected 60, detected 55",
        design_specification={"critical_dimensions": [{"id": "hole_spacing", "value": 60, "protected": True}]},
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "contract-repair-v2"
    assert "Contract repair mode:" in prompt
    assert "contract repair, not design revision" in prompt
    assert "ParameterSpec ID" in prompt
    assert "PrintableOutput output_id" in prompt
    assert "Protected value changed" in prompt


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
        source_metadata={"parameter_names": ["lid_thickness"], "component_ids": ["lid"]},
    )

    prompt = provider.build_revision_plan_prompt(request)

    assert provider.revision_plan_prompt_template_version() == "revision-planning-v1"
    assert "Return JSON only. Do not generate CAD source." in prompt
    assert "Use the Design Plan dependency graph" in prompt
    assert "allowed_parameter_changes" in prompt
    assert "protected_outputs" in prompt
    assert "success_criteria" in prompt
    assert "Make the lid 4 mm thick." in prompt


def test_cadquery_revision_prompt_is_bounded_by_approved_revision_plan() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Make the lid 4 mm thick.",
        current_source="import cadquery as cq\nfrom volundr_cad.runtime import ParameterSpec, PrintableOutput, Product\n",
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

    assert provider.prompt_template_version_for(request) == "cadquery-revision-v1"
    assert "Structured revision mode:" in prompt
    assert "Make only changes approved by the Revision Plan" in prompt
    assert "Preserve protected parameters, components, features, outputs, and interfaces" in prompt
    assert "Increase lid thickness only" in prompt


def test_cadquery_component_revision_prompt_uses_scoped_context() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Revise the lid grip.",
        current_source="import cadquery as cq\nfrom volundr_cad.runtime import ParameterSpec, PrintableOutput, Product\n",
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
            "protected_components": ["body"],
            "allowed_shared_components": [],
        },
        configuration_context={
            "override_manifest": {"parameter_values": {"body_width": 90}},
        },
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "cadquery-component-revision-v1"
    assert "Structured revision mode:" in prompt
    assert "Scoped revision context:" in prompt
    assert "Active configuration context:" in prompt
    assert '"protected_components": [' in prompt


def test_cadquery_scope_correction_prompt_is_not_compile_or_contract_repair() -> None:
    provider = GeminiCliProvider(model="gemini-3.5-flash-lite")
    request = ModelGenerationRequest(
        project_name="Configurable enclosure",
        original_intent="Create a two-part electronics enclosure.",
        user_instruction="Revise the lid grip.",
        current_source="import cadquery as cq\n",
        revision_plan={"summary": "Modify lid only", "protected_outputs": ["body"]},
        scoped_revision_context={"protected_components": ["body"], "targeted_components": ["lid"]},
        scope_diagnostics='[{"rule_id":"revision.protected_component_changed"}]',
    )

    prompt = provider.build_prompt(request)

    assert provider.prompt_template_version_for(request) == "scope-correction-v1"
    assert "Revision scope correction mode:" in prompt
    assert "This is scope correction, not a new design revision." in prompt
    assert "Revert unauthorized edits" in prompt
