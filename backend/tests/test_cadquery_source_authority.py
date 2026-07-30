import pytest

from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    build_cadquery_source_authority,
    validate_cadquery_source_authority,
)
from app.services.projects.service import ProjectService


ENCLOSURE_PLAN = {
    "parameters": [
        {
            "id": "pcb_width",
            "value": 70.0,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "pcb_width",
            "source": "user",
        },
        {
            "id": "pcb_depth",
            "value": 45.0,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "pcb_depth",
            "source": "user",
        },
        {
            "id": "standoff_count",
            "value": 4,
            "unit": "count",
            "protected": True,
            "source_requirement_id": "standoff_count",
            "source": "user",
        },
        {
            "id": "standoff_hole",
            "value": 2.6,
            "unit": "mm",
            "protected": True,
            "source_requirement_id": "standoff_hole",
            "source": "user",
        },
        {
            "id": "wall_thickness_mm",
            "value": 3.0,
            "unit": "mm",
            "protected": False,
            "source": "product_default",
        },
    ],
    "components": [
        {"id": "base_shell", "features": ["pcb_cavity", "standoffs"]},
        {"id": "snap_lid", "features": ["lid_panel"]},
    ],
    "features": [
        {
            "id": "pcb_cavity",
            "component_id": "base_shell",
            "protected": True,
            "parameters": ["pcb_width", "pcb_depth"],
        },
        {
            "id": "standoffs",
            "component_id": "base_shell",
            "protected": True,
            "parameters": ["standoff_count", "standoff_hole"],
        },
        {"id": "lid_panel", "component_id": "snap_lid", "protected": False},
    ],
    "printable_outputs": [
        {
            "id": "base",
            "component_ids": ["base_shell"],
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        },
        {
            "id": "lid",
            "component_ids": ["snap_lid"],
            "required": True,
            "expected_solid_count": 1,
            "allow_disconnected_solids": False,
        },
    ],
}


def _source(
    *,
    parameters: str,
    components: str = '@component("base_shell")\n@feature("pcb_cavity", component="base_shell")\n@feature("standoffs", component="base_shell")\ndef build_base(params):\n    base = cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], 10)\n    for index in range(params["standoff_count"]):\n        base = base.union(cq.Workplane("XY").cylinder(4, params["standoff_hole"]))\n    return base\n\n@component("snap_lid")\ndef build_enclosure_lid(params):\n    return cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], params["wall_thickness_mm"])\n',
    outputs: str = 'PrintableOutput(output_id="base", component_id="base_shell", label="Base", model=base, quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),\n            PrintableOutput(output_id="lid", component_id="snap_lid", label="Lid", model=lid, quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),',
) -> str:
    return f'''
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature

PARAMETERS = [
{parameters}
]

{components}

def build(params):
    base = build_base(params)
    lid = build_enclosure_lid(params)
    return Product(
        outputs=[
            {outputs}
        ],
        parameters=PARAMETERS,
    )
'''


COMPLETE_PARAMETERS = '''
    ParameterSpec(id="pcb_width", label="PCB Width", type="float", default=70.0, unit="mm", protected=True, source_requirement_id="pcb_width", source="user"),
    ParameterSpec(id="pcb_depth", label="PCB Depth", type="float", default=45.0, unit="mm", protected=True, source_requirement_id="pcb_depth", source="user"),
    ParameterSpec(id="standoff_count", label="Standoff Count", type="int", default=4, unit="count", protected=True, source_requirement_id="standoff_count", source="user"),
    ParameterSpec(id="standoff_hole", label="Standoff Hole", type="float", default=2.6, unit="mm", protected=True, source_requirement_id="standoff_hole", source="user"),
    ParameterSpec(id="wall_thickness_mm", label="Wall Thickness", type="float", default=3.0, unit="mm", protected=False, source="product_default"),
'''


def finding_ids(findings: list[dict]) -> set[str]:
    return {finding["rule_id"] for finding in findings}


def test_builds_canonical_source_authority_from_design_plan() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)

    assert authority["schema_version"] == "cadquery-source-authority-v1"
    assert [parameter["id"] for parameter in authority["parameters"]] == [
        "pcb_width",
        "pcb_depth",
        "standoff_count",
        "standoff_hole",
        "wall_thickness_mm",
    ]
    assert next(
        parameter for parameter in authority["parameters"] if parameter["id"] == "standoff_count"
    )["type"] == "int"
    assert [component["id"] for component in authority["components"]] == [
        "base_shell",
        "snap_lid",
    ]
    assert [output["id"] for output in authority["outputs"]] == ["base", "lid"]


def test_missing_protected_parameters_fail_before_execution() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)
    source = _source(
        parameters=COMPLETE_PARAMETERS.replace(
            '    ParameterSpec(id="standoff_count", label="Standoff Count", type="int", default=4, unit="count", protected=True, source_requirement_id="standoff_count", source="user"),\n',
            "",
        ).replace(
            '    ParameterSpec(id="standoff_hole", label="Standoff Hole", type="float", default=2.6, unit="mm", protected=True, source_requirement_id="standoff_hole", source="user"),\n',
            "",
        )
    )

    with pytest.raises(CadQuerySourceAuthorityError) as exc:
        validate_cadquery_source_authority(source, authority)

    assert {"cadquery.required_parameter_missing"} == finding_ids(exc.value.findings)


def test_declared_protected_count_parameter_must_be_used() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)
    source = _source(
        parameters=COMPLETE_PARAMETERS,
        components='@component("base_shell")\n@feature("pcb_cavity", component="base_shell")\n@feature("standoffs", component="base_shell")\ndef build_base(params):\n    base = cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], 10)\n    for index in range(4):\n        base = base.union(cq.Workplane("XY").cylinder(4, params["standoff_hole"]))\n    return base\n\n@component("snap_lid")\ndef build_enclosure_lid(params):\n    return cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], params["wall_thickness_mm"])\n',
    )

    with pytest.raises(CadQuerySourceAuthorityError) as exc:
        validate_cadquery_source_authority(source, authority)

    assert "cadquery.required_parameter_unused" in finding_ids(exc.value.findings)


def test_invented_component_and_output_ids_fail_before_execution() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)
    source = _source(
        parameters=COMPLETE_PARAMETERS,
        components='@component("base_shell")\ndef build_base(params):\n    return cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], 10)\n\n@component("lid_component")\ndef build_enclosure_lid(params):\n    return cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], params["wall_thickness_mm"])\n',
        outputs='PrintableOutput(output_id="base", component_id="base_shell", label="Base", model=base, quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),\n            PrintableOutput(output_id="lid_body", component_id="lid_component", label="Lid", model=lid, quantity=1, required=True, expected_solid_count=1, allow_disconnected_solids=False),',
    )

    with pytest.raises(CadQuerySourceAuthorityError) as exc:
        validate_cadquery_source_authority(source, authority)

    assert {
        "cadquery.required_component_missing",
        "cadquery.required_output_missing",
        "cadquery.unapproved_identity_added",
    }.issubset(finding_ids(exc.value.findings))


def test_function_names_may_differ_when_stable_ids_match() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)
    source = _source(parameters=COMPLETE_PARAMETERS)

    result = validate_cadquery_source_authority(source, authority)

    assert result["passed_hard_checks"] is True
    assert result["findings"] == []


def test_keyword_decorator_ids_certify_when_stable_ids_match() -> None:
    authority = build_cadquery_source_authority(ENCLOSURE_PLAN)
    source = _source(
        parameters=COMPLETE_PARAMETERS,
        components='@component(id="base_shell")\n@feature("pcb_cavity", component="base_shell")\n@feature("standoffs", component="base_shell")\ndef build_base(params):\n    base = cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], 10)\n    for index in range(params["standoff_count"]):\n        base = base.union(cq.Workplane("XY").cylinder(4, params["standoff_hole"]))\n    return base\n\n@component(id="snap_lid")\ndef build_enclosure_lid(params):\n    return cq.Workplane("XY").box(params["pcb_width"], params["pcb_depth"], params["wall_thickness_mm"])\n',
    )

    result = validate_cadquery_source_authority(source, authority)

    assert result["passed_hard_checks"] is True
    assert result["findings"] == []


def test_execution_parameters_coerce_integral_plan_count_to_source_int() -> None:
    service = ProjectService(db=None, ai_provider=None)  # type: ignore[arg-type]
    source = _source(parameters=COMPLETE_PARAMETERS)
    plan = {
        **ENCLOSURE_PLAN,
        "parameters": [
            {**parameter, "value": 4.0}
            if parameter["id"] == "standoff_count"
            else parameter
            for parameter in ENCLOSURE_PLAN["parameters"]
        ],
    }

    values = service._cadquery_execution_parameter_values(source=source, design_plan_payload=plan)

    assert values["standoff_count"] == 4
    assert isinstance(values["standoff_count"], int)
