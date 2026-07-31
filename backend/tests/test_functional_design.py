from __future__ import annotations

import pytest
import trimesh

from app.services.cad.cadquery_source_authority import (
    CadQuerySourceAuthorityError,
    validate_cadquery_source_authority,
)
from app.services.functional.intent import (
    validate_functional_plan,
    validate_revision_success_criteria,
)
from app.services.geometry.functional import (
    FunctionalGeometryContext,
    FunctionalGeometryVerifierRegistry,
)


def _plan(**overrides):
    plan = {
        "schema_version": "1.1",
        "functional_contract": {
            "coordinate_frames": [
                {
                    "id": "primary_product_frame",
                    "axes": {"x": "horizontal", "y": "wall_normal", "z": "vertical"},
                }
            ],
            "mounting_interfaces": [
                {
                    "id": "wall_mount",
                    "type": "planar_mount",
                    "component_id": "holder_body",
                    "mounting_plane": "XZ",
                    "normal_axis": "Y",
                    "fastener_count": 2,
                    "hole_axis": "Y",
                    "arrangement_axis": "Z",
                    "hole_style": "clearance",
                    "spacing": {"value": 50, "unit": "mm", "source": "volundr_proposal"},
                }
            ],
            "support_interfaces": [
                {
                    "id": "bottle_support",
                    "type": "contained_object_support",
                    "object_requirement_id": "bottle_diameter",
                    "primary_axis": "Z",
                    "bottom_support_required": True,
                    "minimum_floor_thickness": {
                        "value": 3,
                        "unit": "mm",
                        "source": "volundr_proposal",
                    },
                    "removal_direction": "+Z",
                }
            ],
            "retention_interfaces": [
                {
                    "id": "boat_retention",
                    "type": "retention",
                    "required": True,
                    "environment": "moving_vehicle",
                    "release_behavior": "one_handed",
                    "strategy": "retention_lip",
                    "feature_id": "retention_feature",
                    "component_id": "holder_body",
                }
            ],
        },
    }
    plan.update(overrides)
    return plan


def test_functional_plan_rejects_ambiguous_mounting_contract() -> None:
    plan = _plan(
        functional_contract={
            "mounting_interfaces": [
                {
                    "id": "wall_mount",
                    "type": "planar_mount",
                    "component_id": "holder_body",
                    "mounting_plane": "XZ",
                    "normal_axis": None,
                    "fastener_count": 2,
                    "hole_axis": "vertical or horizontal",
                    "arrangement_axis": None,
                    "hole_style": "countersunk or clearance",
                }
            ]
        }
    )

    findings = validate_functional_plan(plan)

    assert {finding["rule_id"] for finding in findings} >= {
        "functional.hole_axis_missing",
        "functional.mounting_strategy_ambiguous",
    }


def test_functional_plan_accepts_explicit_mounting_support_and_retention() -> None:
    assert validate_functional_plan(_plan()) == []


def test_functional_plan_rejects_placeholder_retention_strategy() -> None:
    findings = validate_functional_plan(
        _plan(
            functional_contract={
                **_plan()["functional_contract"],
                "retention_interfaces": [
                    {
                        **_plan()["functional_contract"]["retention_interfaces"][0],
                        "strategy": "reviewed_proposal",
                        "feature_id": None,
                    }
                ],
            }
        )
    )

    assert any(finding["rule_id"] == "functional.retention_strategy_unresolved" for finding in findings)


def test_revision_criteria_reject_output_as_parameter_and_unknown_types() -> None:
    findings = validate_revision_success_criteria(
        {
            "schema_version": "revision-plan-v2",
            "success_criteria": [
                {"type": "parameter_value", "target_id": "print_body", "expected_value": 1},
                {"type": "unknown_rule", "target_id": "holder_body"},
            ],
        },
        plan={"parameters": [{"id": "wall_thickness"}], "printable_outputs": [{"id": "print_body"}]},
    )

    assert {finding["rule_id"] for finding in findings} >= {
        "functional.revision_criterion_type_unknown",
        "functional.revision_criterion_target_invalid",
    }


def test_noop_protected_parameter_reference_is_rejected() -> None:
    source = '''
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper

PARAMETERS = [
    ParameterSpec(id="bottle_diameter", label="Bottle diameter", type="float", default=81.0, unit="mm", protected=True),
]

@component("holder_body")
@feature("bottle_cavity", component="holder_body")
@shared_helper("build_holder")
def build_holder(params):
    _ = params["bottle_diameter"]
    return cq.Workplane("XY").box(10, 10, 3)

def build(params):
    return Product(outputs=[PrintableOutput(output_id="print_body", label="Body", model=build_holder(params), component_id="holder_body", expected_solid_count=1, allow_disconnected_solids=False)], parameters=PARAMETERS)
'''
    authority = {
        "parameters": [{"id": "bottle_diameter", "type": "float", "unit": "mm", "value": 81.0, "protected": True, "required": True}],
        "components": [{"id": "holder_body", "required": True}],
        "features": [{"id": "bottle_cavity", "component_id": "holder_body", "required": True, "protected": True}],
        "outputs": [{"id": "print_body", "component_ids": ["holder_body"], "required": True, "expected_solid_count": 1}],
    }

    with pytest.raises(CadQuerySourceAuthorityError) as error:
        validate_cadquery_source_authority(source, authority)

    assert any(
        finding["rule_id"] == "cadquery.protected_parameter_no_geometry_effect"
        for finding in error.value.findings
    )


def test_declared_feature_without_invocation_is_rejected() -> None:
    source = '''
import cadquery as cq
from volundr_cad.runtime import ParameterSpec, PrintableOutput, Product, component, feature, shared_helper

PARAMETERS = []

@component("holder_body")
def build_holder(params):
    return cq.Workplane("XY").box(10, 10, 3)

@feature("retention", component="holder_body")
def add_retention(body, params):
    return body.union(cq.Workplane("XY").box(2, 2, 2))

def build(params):
    return Product(outputs=[PrintableOutput(output_id="print_body", label="Body", model=build_holder(params), component_id="holder_body", expected_solid_count=1, allow_disconnected_solids=False)], parameters=PARAMETERS)
'''
    authority = {
        "parameters": [],
        "components": [{"id": "holder_body", "required": True}],
        "features": [{"id": "retention", "component_id": "holder_body", "required": True, "protected": True}],
        "outputs": [{"id": "print_body", "component_ids": ["holder_body"], "required": True, "expected_solid_count": 1}],
    }

    with pytest.raises(CadQuerySourceAuthorityError) as error:
        validate_cadquery_source_authority(source, authority)

    assert any(
        finding["rule_id"] == "functional.feature_declared_not_invoked"
        for finding in error.value.findings
    )


def test_mounting_interface_without_measurable_holes_is_blocked() -> None:
    contract = _plan()["functional_contract"]
    findings = FunctionalGeometryVerifierRegistry.default().verify(
        FunctionalGeometryContext(
            product_plan={"functional_contract": contract},
            output_shape=trimesh.creation.box(extents=(20, 20, 3)),
        )
    )

    assert any(
        finding.rule_id == "functional.mounting_hole_axis" and finding.is_blocking
        for finding in findings
    )


def test_support_floor_for_solid_geometry_is_verified() -> None:
    contract = _plan()["functional_contract"]
    findings = FunctionalGeometryVerifierRegistry.default().verify(
        FunctionalGeometryContext(
            product_plan={"functional_contract": contract},
            output_shape=trimesh.creation.box(extents=(20, 20, 20)),
        )
    )

    floor = next(finding for finding in findings if finding.rule_id == "functional.support_floor_present")
    assert floor.verification_state == "verified"
