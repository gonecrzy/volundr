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
    specification: dict | None = None,
    execution_parameters: dict | None = None,
    execution_manifest: dict | None = None,
    output_manifest: dict | None = None,
) -> dict:
    return certify_design_artifact_consistency(
        project_id="project-1",
        revision_id="revision-1",
        design_specification_id="spec-1",
        design_specification_payload=specification or DESIGN_SPECIFICATION,
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
    plan = copy.deepcopy(DESIGN_PLAN)
    plan["components"][0]["features"] = ["standoff_pattern"]

    result = certify(source, plan=plan)

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


TRACE_SPECIFICATION = {
    "critical_dimensions": [],
    "parameters": [],
    "functional_requirements": [
        {
            "id": "include_integral_handle",
            "description": "Include an integrated carrying handle",
            "source": "user",
            "protected": False,
        }
    ],
}

TRACE_PLAN = {
    "outcome": "plan_ready",
    "components": [
        {
            "id": "base",
            "role": "printable_part",
            "required": True,
            "features": ["integral_handle"],
        }
    ],
    "features": [
        {
            "id": "integral_handle",
            "component_id": "base",
            "type": "extrusion",
            "description": "Integrated carrying handle",
        }
    ],
    "parameters": [],
    "derived_parameters": [],
    "printable_outputs": [
        {
            "id": "base_output",
            "component_ids": ["base"],
            "required": True,
            "expected_solid_count": 1,
        }
    ],
    "validation_targets": [],
}

TRACE_SOURCE = """
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component

PARAMETERS = []

@component("base")
def build_base(params):
    body = cq.Workplane("XY").box(40.0, 30.0, 4.0)
    handle = cq.Workplane("XY").box(10.0, 4.0, 8.0).translate((0.0, 0.0, 6.0))
    return body.union(handle)

def build(params):
    return Product(
        outputs=[PrintableOutput(output_id="base_output", label="Base", model=build_base(params), component_ids=("base",), quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False)],
        parameters=PARAMETERS,
        schema_version="cadquery-v1",
    )
"""


def test_integral_feature_inside_component_function_needs_no_feature_function_or_output() -> None:
    result = certify(
        TRACE_SOURCE,
        specification=TRACE_SPECIFICATION,
        plan=TRACE_PLAN,
    )

    assert result["pre_execution_passed"] is True
    assert not any(
        finding["rule_id"] == "design_artifact.feature_function_trace_missing"
        and finding["is_blocking"]
        for finding in result["findings"]
    )
    obligation = next(
        item for item in result["requirement_trace"]["normalized"]["obligations"]
        if item["requirement_id"] == "include_integral_handle"
    )
    assert obligation["plan_feature_id"] == "integral_handle"
    assert obligation["function_id"] == "build_base"
    assert obligation["output_id"] == "base_output"


def test_protected_integral_feature_can_trace_to_component_function() -> None:
    plan = copy.deepcopy(TRACE_PLAN)
    plan["features"][0]["protected"] = True

    result = certify(TRACE_SOURCE, specification=TRACE_SPECIFICATION, plan=plan)

    assert result["pre_execution_passed"] is True
    mapping = next(
        item for item in result["feature_mappings"] if item["plan_feature_id"] == "integral_handle"
    )
    assert mapping["status"] == "integral_in_component_function"
    assert mapping["source_component_id"] == "base"


def test_printable_component_requirement_traces_component_and_output() -> None:
    specification = {
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [
            {
                "id": "print_base",
                "description": "Provide the printable base component",
                "source": "user",
                "protected": True,
                "type": "printable_component",
                "component_id": "base",
            }
        ],
    }

    result = certify(TRACE_SOURCE, specification=specification, plan=TRACE_PLAN)

    assert result["pre_execution_passed"] is True
    obligation = result["requirement_trace"]["normalized"]["obligations"][0]
    assert obligation["trace_classification"] == "source_trace_required"
    assert obligation["status"] == "source_component_output_trace"
    assert obligation["component_ids"] == ["base"]
    assert obligation["output_ids"] == ["base_output"]


def test_required_output_requirement_reports_missing_output_trace() -> None:
    specification = {
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [
            {
                "id": "print_base",
                "description": "Produce the base output",
                "source": "user",
                "protected": True,
                "type": "required_output",
                "output_id": "base_output",
            }
        ],
    }

    source = TRACE_SOURCE.replace('output_id="base_output"', 'output_id="other_output"')
    result = certify(source, specification=specification, plan=TRACE_PLAN)

    assert result["pre_execution_passed"] is False
    assert any(
        finding["rule_id"] == "design_artifact.output_trace_missing"
        for finding in result["findings"]
    )


def test_required_feature_without_function_or_verification_target_blocks() -> None:
    specification = {
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [
            {
                "id": "required_handle",
                "description": "Include a carrying handle",
                "source": "user",
                "protected": False,
                "type": "explicit_feature",
            }
        ],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["features"] = []

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is False
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.required_feature_missing"
    )
    assert finding["requirement_id"] == "required_handle"
    assert finding["trace_classification"] == "source_or_geometry_trace"


def test_fixed_count_can_defer_to_geometry_verification_without_parameter_trace() -> None:
    specification = {
        "critical_dimensions": [
            {
                "id": "hole_count",
                "value": 2,
                "unit": "count",
                "source": "user",
                "protected": True,
            }
        ],
        "parameters": [],
        "functional_requirements": [],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["validation_targets"] = [
        {"id": "verify_hole_count", "requirement_id": "hole_count", "type": "count"}
    ]

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is True
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.geometry_verification_deferred"
    )
    assert finding["is_blocking"] is False
    assert finding["requirement_id"] == "hole_count"


def test_explicit_numeric_requirement_can_defer_to_geometry_verification() -> None:
    specification = {
        "critical_dimensions": [
            {
                "id": "plate_width",
                "value": 80.0,
                "source": "user",
                "protected": True,
            }
        ],
        "parameters": [],
        "functional_requirements": [],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["validation_targets"] = [
        {"id": "verify_plate_width", "requirement_id": "plate_width", "type": "dimension"}
    ]

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is True
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.geometry_verification_deferred"
    )
    assert finding["requirement_id"] == "plate_width"
    assert finding["trace_classification"] == "geometry_verification_required"


def test_integral_feature_without_function_can_defer_to_geometry_target() -> None:
    specification = {
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [
            {
                "id": "protected_handle",
                "description": "Include the required carrying handle",
                "source": "user",
                "protected": False,
                "type": "explicit_feature",
                "feature_id": "integral_handle",
            }
        ],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["features"][0]["protected"] = False
    plan["validation_targets"] = [
        {"id": "verify_handle", "requirement_id": "protected_handle", "type": "feature_presence"}
    ]

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is True
    plan["components"][0]["features"] = []

    source = TRACE_SOURCE.replace(
        '    handle = cq.Workplane("XY").box(10.0, 4.0, 8.0).translate((0.0, 0.0, 6.0))\n',
        "",
    ).replace(
        "    return body.union(handle)\n",
        "    return body\n",
    )
    result = certify(source, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is True
    obligation = next(
        item
        for item in result["requirement_trace"]["normalized"]["obligations"]
        if item["requirement_id"] == "protected_handle"
    )
    assert obligation["status"] == "geometry_verification_target"


def test_qualitative_requirement_without_source_trace_is_human_review() -> None:
    specification = {
        "critical_dimensions": [],
        "parameters": [],
        "functional_requirements": [
            {
                "id": "one_handed_removal",
                "description": "One-handed removal should feel comfortable",
                "source": "user",
                "protected": False,
                "type": "qualitative_behavior",
            }
        ],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["features"] = []

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is True
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.requirement_trace_unverifiable"
    )
    assert finding["trace_classification"] == "human_review"
    assert finding["is_blocking"] is False


def test_feature_owner_mismatch_is_specific_and_blocking() -> None:
    specification = copy.deepcopy(TRACE_SPECIFICATION)
    plan = copy.deepcopy(TRACE_PLAN)
    plan["components"].append({"id": "lid", "role": "printable_part", "required": False})
    plan["features"][0]["component_id"] = "base"
    source = TRACE_SOURCE.replace(
        '@component("base")',
        '@component("base")\n@feature("integral_handle", component="lid")',
    ).replace(
        'from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component',
        'from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature',
    )

    result = certify(source, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is False
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.feature_owner_mismatch"
    )
    assert finding["requirement_id"] == "include_integral_handle"
    assert finding["blocking"] is True


def test_feature_owner_alias_is_normalized_when_unambiguous() -> None:
    plan = copy.deepcopy(TRACE_PLAN)
    feature = plan["features"][0]
    feature.pop("component_id")
    feature["owner_component_id"] = "base"

    result = certify(TRACE_SOURCE, specification=TRACE_SPECIFICATION, plan=plan)

    assert result["pre_execution_passed"] is True
    obligation = next(
        item for item in result["requirement_trace"]["normalized"]["obligations"]
        if item["requirement_id"] == "include_integral_handle"
    )
    assert obligation["owning_component_id"] == "base"
    assert any(
        finding["rule_id"] == "design_artifact.trace_alias_normalized"
        and finding["feature_id"] == "integral_handle"
        for finding in result["findings"]
    )


def test_exposed_control_without_source_parameter_trace_blocks() -> None:
    specification = {
        "critical_dimensions": [
            {
                "id": "plate_width",
                "value": 80.0,
                "unit": "mm",
                "source": "user",
                "protected": True,
            }
        ],
        "parameters": [],
        "functional_requirements": [],
    }
    plan = copy.deepcopy(TRACE_PLAN)
    plan["exposed_controls"] = ["plate_width"]
    plan["parameters"] = [
        {
            "id": "plate_width",
            "value": 80.0,
            "unit": "mm",
            "editable": True,
            "constraint_mode": "configurable_parameter",
            "source_requirement_id": "plate_width",
        }
    ]

    result = certify(TRACE_SOURCE, specification=specification, plan=plan)

    assert result["pre_execution_passed"] is False
    finding = next(
        item for item in result["findings"]
        if item["rule_id"] == "design_artifact.requirement_trace_unverifiable"
        and item.get("requirement_id") == "plate_width"
    )
    assert finding["trace_classification"] == "source_trace_required"
    assert finding["is_blocking"] is True


def test_multiple_printable_components_cannot_collapse_into_one_output() -> None:
    plan = copy.deepcopy(TRACE_PLAN)
    plan["components"].append({"id": "lid", "role": "printable_part", "required": True})

    result = certify(TRACE_SOURCE, specification=TRACE_SPECIFICATION, plan=plan)

    assert result["pre_execution_passed"] is False
    assert "design_artifact.component_output_conflict" in finding_ids(result)
