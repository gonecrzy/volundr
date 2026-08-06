"""Frozen offline and live fixture for the executable-source experiment."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FROZEN_MOUNTING_BRACKET_USER_PROMPT = (
    "Create a mounting bracket with a body 80 mm wide, 50 mm deep, and 8 mm thick. "
    "Add four 5 mm through-holes with each mounting-hole center 8 mm from its nearest edge. "
    "Add a centered recessed pocket 40 mm wide, 20 mm deep, and 3 mm deep. "
    "Add one asymmetric 10 mm through-hole centered 18 mm from the left edge and "
    "25 mm from the lower edge. Add a 2 mm external fillet where geometrically valid."
)


def frozen_mounting_bracket_contract() -> dict[str, Any]:
    return {
        "schema_version": "executable-cadquery-design-contract-v1",
        "project_id": "fixture-mounting-bracket-project",
        "workflow_id": "fixture-mounting-bracket-workflow",
        "revision_id": "fixture-mounting-bracket-revision-1",
        "units": "mm",
        "outputs": [
            {
                "output_id": "mounting_bracket",
                "required": True,
                "output_type": "printable_component",
                "expected_solid_count": 1,
            }
        ],
        "requirements": [
            {
                "requirement_id": "body_dimensions",
                "scope": "mounting_bracket",
                "expected": {"width": 80.0, "depth": 50.0, "thickness": 8.0},
                "tolerance": 0.2,
                "verification_policy": "final_mesh_bounds",
            },
            {
                "requirement_id": "mounting_hole_pattern",
                "scope": "mounting_bracket",
                "expected": {"count": 4, "diameter": 5.0, "through": True},
                "tolerance": 0.25,
                "verification_policy": "final_mesh_opening_profiles",
            },
            {
                "requirement_id": "mounting_hole_edge_offsets",
                "scope": "mounting_bracket",
                "expected": {"nearest_edge_offset": 8.0},
                "tolerance": 0.25,
                "verification_policy": "final_mesh_opening_centers",
            },
            {
                "requirement_id": "centered_recessed_pocket",
                "scope": "mounting_bracket",
                "expected": {"width": 40.0, "depth": 20.0, "cut_depth": 3.0, "centered": True},
                "tolerance": 0.25,
                "verification_policy": "final_mesh_feature_profiles",
            },
            {
                "requirement_id": "asymmetric_through_hole",
                "scope": "mounting_bracket",
                "expected": {"diameter": 10.0, "x_from_left": 18.0, "y_from_lower": 25.0, "through": True},
                "tolerance": 0.25,
                "verification_policy": "final_mesh_opening_centers",
            },
            {
                "requirement_id": "external_fillet",
                "scope": "mounting_bracket",
                "expected": {"radius": 2.0},
                "tolerance": 0.25,
                "verification_policy": "measure_when_supported",
            },
        ],
        "relationships": [
            {
                "relationship_id": "pocket_centered_in_body",
                "participants": ["mounting_bracket"],
                "expected_relationship": "centered_recessed_pocket",
            },
            {
                "relationship_id": "mounting_centers_nearest_edges",
                "participants": ["mounting_bracket"],
                "expected_relationship": "each_mounting_center_is_8_mm_from_a_nearest_edge",
            },
        ],
        "protected_facts": [
            {"requirement_id": "body_dimensions", "authoritative_value": {"width": 80.0, "depth": 50.0, "thickness": 8.0}},
            {"requirement_id": "mounting_hole_pattern", "authoritative_value": {"count": 4, "diameter": 5.0}},
            {"requirement_id": "mounting_hole_edge_offsets", "authoritative_value": {"nearest_edge_offset": 8.0}},
            {"requirement_id": "centered_recessed_pocket", "authoritative_value": {"width": 40.0, "depth": 20.0, "cut_depth": 3.0}},
            {"requirement_id": "asymmetric_through_hole", "authoritative_value": {"diameter": 10.0, "x_from_left": 18.0, "y_from_lower": 25.0}},
            {"requirement_id": "external_fillet", "authoritative_value": {"radius": 2.0}},
        ],
    }


FROZEN_MOUNTING_BRACKET_CONTRACT = frozen_mounting_bracket_contract()


def valid_mounting_bracket_source() -> str:
    """A deterministic complete source used only for offline worker fixtures."""

    return '''import cadquery as cq
from volundr_cad.runtime import PrintableOutput, Product


def build(params):
    body = cq.Workplane("XY").box(80.0, 50.0, 8.0)
    body = body.edges("|Z").fillet(2.0)
    body = body.faces(">Z").workplane().pushPoints([
        (-32.0, -17.0),
        (-32.0, 17.0),
        (32.0, -17.0),
        (32.0, 17.0),
    ]).hole(5.0)
    body = body.faces(">Z").workplane().rect(40.0, 20.0).cutBlind(-3.0)
    body = body.faces(">Z").workplane().pushPoints([(-22.0, 0.0)]).hole(10.0)
    return Product(outputs=(PrintableOutput(
        output_id="mounting_bracket",
        label="Mounting bracket",
        model=body,
        component_id="mounting_bracket",
        required=True,
        expected_solid_count=1,
        allow_disconnected_solids=False,
    ),))
'''


def copy_frozen_mounting_bracket_contract() -> dict[str, Any]:
    return deepcopy(FROZEN_MOUNTING_BRACKET_CONTRACT)
