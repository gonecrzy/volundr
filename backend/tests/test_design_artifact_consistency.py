import copy

from app.services.projects.design_artifact_consistency import (
    certify_design_artifact_consistency,
    consistency_failure_message,
)


DESIGN_SPECIFICATION = {
    "schema_version": "1.0",
    "object_type": "electronics_enclosure",
    "purpose": "Hold a PCB in a base with a lid",
    "units": "mm",
    "critical_dimensions": [
        {
            "id": "pcb_width",
            "label": "PCB width",
            "value": 70.0,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "parameters": [],
    "functional_requirements": [],
    "print_requirements": {},
    "assumptions": [],
    "conflicts": [],
    "missing_requirements": [],
    "clarification_required": False,
    "clarification_questions": [],
    "generation_ready": True,
    "outcome": "generation_ready",
}


DESIGN_PLAN = {
    "schema_version": "1.0",
    "design_level": "assembly",
    "product_type": "electronics_enclosure",
    "purpose": "Hold a PCB in a base with a lid",
    "units": "mm",
    "parameters": [
        {
            "id": "pcb_width",
            "label": "PCB width",
            "value": 70.0,
            "unit": "mm",
            "editable": True,
            "protected": True,
            "component_id": "base_shell",
            "source_requirement_id": "pcb_width",
        },
        {
            "id": "wall_thickness",
            "label": "Wall thickness",
            "value": 3.0,
            "unit": "mm",
            "editable": True,
            "protected": False,
            "component_id": "base_shell",
            "source_requirement_id": None,
            "source": "product_default",
        },
    ],
    "derived_parameters": [
        {
            "id": "outer_width",
            "label": "Outer width",
            "expression": "pcb_width + 2 * wall_thickness",
            "unit": "mm",
            "depends_on": ["pcb_width", "wall_thickness"],
        }
    ],
    "dependency_edges": [],
    "components": [
        {
            "id": "base_shell",
            "label": "Base shell",
            "description": "Base with cavity and standoffs",
            "features": ["pcb_cavity", "standoff_pattern"],
            "parameters": ["pcb_width", "wall_thickness"],
        },
        {
            "id": "snap_lid",
            "label": "Snap lid",
            "description": "Separate lid",
            "features": ["lid_retention"],
            "parameters": ["pcb_width", "wall_thickness"],
        },
    ],
    "features": [
        {
            "id": "pcb_cavity",
            "component_id": "base_shell",
            "type": "cavity",
            "description": "Protected PCB cavity",
            "parameters": ["pcb_width"],
            "protected": True,
        },
        {
            "id": "standoff_pattern",
            "component_id": "base_shell",
            "type": "mounting",
            "description": "Protected standoffs",
            "parameters": [],
            "protected": True,
        },
        {
            "id": "lid_retention",
            "component_id": "snap_lid",
            "type": "fit",
            "description": "Revision-targetable lid fit",
            "parameters": ["wall_thickness"],
            "protected": False,
        },
    ],
    "presets": [],
    "assembly_strategy": {},
    "printable_outputs": [
        {
            "id": "base",
            "label": "Base",
            "component_ids": ["base_shell"],
            "quantity": 1,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        },
        {
            "id": "lid",
            "label": "Lid",
            "component_ids": ["snap_lid"],
            "quantity": 1,
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        },
    ],
    "risks": [],
    "clarification_required": False,
    "clarification_questions": [],
    "plan_ready": True,
    "outcome": "plan_ready",
}


CONSISTENT_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper, protected_interface

PARAMETERS = [
    ParameterSpec(id="pcb_width", label="PCB width", type="float", default=70.0, unit="mm", min_value=10.0, max_value=200.0, editable=True, protected=True, source_requirement_id="pcb_width", source="user"),
    ParameterSpec(id="wall_thickness", label="Wall thickness", type="float", default=3.0, unit="mm", min_value=1.0, max_value=6.0, editable=True, protected=False, source="product_default"),
]

@component("base_shell")
@feature("pcb_cavity", component="base_shell")
@feature("standoff_pattern", component="base_shell")
def build_enclosure_base(params):
    outer_w = params["pcb_width"] + params["wall_thickness"] * 2
    return cq.Workplane("XY").box(outer_w, 50.0, 20.0)

@component("snap_lid")
@feature("lid_retention", component="snap_lid")
def build_enclosure_lid(params):
    outer_w = params["pcb_width"] + params["wall_thickness"] * 2
    return cq.Workplane("XY").box(outer_w, 50.0, params["wall_thickness"])

def build(params):
    return Product(
        outputs=[
            PrintableOutput(output_id="base", label="Base", model=build_enclosure_base(params), component_id="base_shell", quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),
            PrintableOutput(output_id="lid", label="Lid", model=build_enclosure_lid(params), component_id="snap_lid", quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),
        ],
        parameters=PARAMETERS,
        schema_version="cadquery-v1",
    )
"""


INCONSISTENT_ENCLOSURE_SOURCE = CONSISTENT_SOURCE.replace(
    '@component("base_shell")',
    '@component("enclosure_base")',
).replace(
    '@component("snap_lid")',
    '@component("enclosure_lid")',
).replace(
    'component_id="base_shell"',
    'component_id="enclosure_base"',
).replace(
    'component_id="snap_lid"',
    'component_id="enclosure_lid"',
).replace(
    'output_id="base"',
    'output_id="base_body"',
).replace(
    'output_id="lid"',
    'output_id="lid_body"',
).replace(
    'default=3.0',
    'default=2.5',
    1,
)


def certify(
    source: str,
    *,
    plan: dict | None = None,
    execution_parameters: dict | None = None,
    execution_manifest: dict | None = None,
    output_manifest: dict | None = None,
) -> dict:
    return certify_design_artifact_consistency(
        project_id="project-1",
        revision_id="revision-1",
        design_specification_id="spec-1",
        design_specification_payload=DESIGN_SPECIFICATION,
        design_plan_id="plan-1",
        design_plan_payload=plan or DESIGN_PLAN,
        source=source,
        execution_parameters=execution_parameters,
        execution_manifest=execution_manifest,
        output_manifest=output_manifest,
    )


def finding_ids(result: dict) -> set[str]:
    return {finding["rule_id"] for finding in result["findings"]}


def test_matching_plan_source_ids_certify_before_execution() -> None:
    result = certify(CONSISTENT_SOURCE)

    assert result["schema_version"] == "design-artifact-consistency-v1"
    assert result["pre_execution_passed"] is True
    assert result["revision_base_ready"] is False
    assert result["configuration_ready"] is False
    assert result["findings"] == []
    assert {item["plan_component_id"] for item in result["component_mappings"]} == {
        "base_shell",
        "snap_lid",
    }


def test_different_function_names_with_explicit_ids_certify() -> None:
    result = certify(CONSISTENT_SOURCE)

    lid_mapping = next(
        item for item in result["component_mappings"] if item["plan_component_id"] == "snap_lid"
    )
    assert lid_mapping["source_component_id"] == "snap_lid"
    assert lid_mapping["source_symbol"] == "build_enclosure_lid"
    assert result["pre_execution_passed"] is True


def test_enclosure_plan_source_mismatch_fails_with_exact_findings() -> None:
    result = certify(INCONSISTENT_ENCLOSURE_SOURCE)

    assert result["pre_execution_passed"] is False
    assert "design_artifact.component_missing" in finding_ids(result)
    assert "design_artifact.output_missing" in finding_ids(result)
    assert "design_artifact.parameter_value_mismatch" in finding_ids(result)
    assert "planned component `base_shell` has no matching CadQuery source component" in consistency_failure_message(result)
    assert "wall_thickness" in consistency_failure_message(result)


def test_missing_protected_feature_mapping_blocks() -> None:
    source = CONSISTENT_SOURCE.replace('@feature("pcb_cavity", component="base_shell")\n', "")

    result = certify(source)

    assert result["pre_execution_passed"] is False
    assert "design_artifact.feature_missing" in finding_ids(result)


def test_post_execution_certifies_matching_manifest_and_artifacts() -> None:
    result = certify(
        CONSISTENT_SOURCE,
        execution_parameters={"pcb_width": 70.0, "wall_thickness": 3.0},
        execution_manifest={
            "source_hash": None,
            "parameter_hash": None,
            "parameters": {"pcb_width": 70.0, "wall_thickness": 3.0},
            "requested_output_ids": ["base", "lid"],
            "output_ids": ["base", "lid"],
            "outputs": [
                {
                    "output_id": "base",
                    "success": True,
                    "required": True,
                    "topology_metadata": {
                        "output_id": "base",
                        "valid": True,
                        "expected_solid_count": 1,
                        "detected_solid_count": 1,
                    },
                    "stl_hash": "stl-base",
                    "step_hash": "step-base",
                },
                {
                    "output_id": "lid",
                    "success": True,
                    "required": True,
                    "topology_metadata": {
                        "output_id": "lid",
                        "valid": True,
                        "expected_solid_count": 1,
                        "detected_solid_count": 1,
                    },
                    "stl_hash": "stl-lid",
                    "step_hash": "step-lid",
                },
            ],
        },
        output_manifest={
            "source": {"sha256": None},
            "parameter_hash": None,
            "outputs": [
                {
                    "output_id": "base",
                    "component_ids": ["base_shell"],
                    "state": "ready",
                    "required": True,
                    "expected_solid_count": 1,
                    "detected_solid_count": 1,
                    "topology": {"valid": True},
                    "stl": {"sha256": "stl-base"},
                    "step": {"sha256": "step-base"},
                },
                {
                    "output_id": "lid",
                    "component_ids": ["snap_lid"],
                    "state": "ready",
                    "required": True,
                    "expected_solid_count": 1,
                    "detected_solid_count": 1,
                    "topology": {"valid": True},
                    "stl": {"sha256": "stl-lid"},
                    "step": {"sha256": "step-lid"},
                },
            ],
        },
    )

    assert result["pre_execution_passed"] is True
    assert result["post_execution_passed"] is True
    assert result["revision_base_ready"] is True
    assert result["configuration_ready"] is True


def test_post_execution_blocks_output_manifest_mismatch() -> None:
    manifest = {
        "outputs": [
            {
                "output_id": "base_body",
                "component_ids": ["base_shell"],
                "state": "ready",
                "required": True,
                "expected_solid_count": 1,
                "detected_solid_count": 1,
                "topology": {"valid": True},
            }
        ]
    }

    result = certify(CONSISTENT_SOURCE, output_manifest=manifest)

    assert result["post_execution_passed"] is False
    assert "design_artifact.manifest_required_output_missing" in finding_ids(result)


def test_execution_override_is_accepted_when_declared() -> None:
    result = certify(
        CONSISTENT_SOURCE,
        execution_parameters={"pcb_width": 70.0, "wall_thickness": 4.0},
        execution_manifest={
            "parameters": {"pcb_width": 70.0, "wall_thickness": 4.0},
            "parameter_overrides": {"wall_thickness": 4.0},
        },
    )

    assert result["pre_execution_passed"] is True
    assert "design_artifact.execution_parameter_mismatch" not in finding_ids(result)


def test_unapproved_execution_mismatch_blocks() -> None:
    result = certify(
        CONSISTENT_SOURCE,
        execution_parameters={"pcb_width": 70.0, "wall_thickness": 4.0},
        execution_manifest={"parameters": {"pcb_width": 70.0, "wall_thickness": 4.0}},
    )

    assert result["pre_execution_passed"] is False
    assert "design_artifact.execution_parameter_mismatch" in finding_ids(result)


def test_derived_parameter_is_not_required_as_source_default() -> None:
    result = certify(CONSISTENT_SOURCE)

    assert result["pre_execution_passed"] is True
    parameter = next(item for item in result["parameter_mappings"] if item["parameter_id"] == "outer_width")
    assert parameter["status"] == "derived_not_submitted"
