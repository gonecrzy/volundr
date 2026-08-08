from __future__ import annotations

import trimesh

from app.services.executable_cadquery.semantic import (
    _generic_requirement_finding,
    resolve_executable_cadquery_output_scope,
)
from app.services.executable_cadquery.semantic_contract import (
    normalize_executable_cadquery_requirement,
)
from app.services.executable_cadquery.semantic_policy import evaluate_semantic_policy


def _requirement(*, policy: str, expected: dict, **fields: object) -> dict:
    return {
        "requirement_id": "synthetic-requirement",
        "classification": "machine_required",
        "verification_policy": policy,
        "expected": expected,
        "tolerance": 0.25,
        **fields,
    }


def test_canonical_wall_field_is_the_verifier_input() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(policy="final_mesh_wall_profile", expected={"wall_thickness": 2.5})
    )

    assert result["status"] == "normalized"
    assert result["expected"]["wall_thickness"] == 2.5
    assert result["unsupported_fields"] == []


def test_supported_legacy_wall_and_opening_fields_normalize_centrally() -> None:
    wall = normalize_executable_cadquery_requirement(
        _requirement(policy="final_mesh_wall_profile", expected={"wall": 2.5})
    )
    openings = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"count": 2, "diameter": 4.0, "through": True},
        )
    )

    assert wall["expected"]["wall_thickness"] == 2.5
    assert openings["expected"]["hole_count"] == 2
    assert openings["expected"]["hole_diameter"] == 4.0
    assert openings["expected"]["through"] is True


def test_opening_center_diameter_does_not_invent_a_count() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_opening_centers",
            expected={"diameter": 10.0},
        )
    )

    assert result["status"] == "normalized"
    assert result["expected"]["hole_diameter"] == 10.0
    assert "hole_count" not in result["expected"]


def test_canonical_field_wins_over_legacy_field() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"hole_count": 2, "count": 99},
        )
    )

    assert result["status"] == "normalized"
    assert result["expected"]["hole_count"] == 2
    assert result["shadowed_legacy_fields"] == ["count"]


def test_conflicting_legacy_aliases_fail_closed() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_wall_profile",
            expected={"wall": 2.5, "value": 3.0},
        )
    )

    assert result["status"] == "conflict"
    assert result["conflicts"] == ["wall_thickness"]


def test_unrelated_fields_and_missing_measurement_information_do_not_substitute() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(policy="final_mesh_wall_profile", expected={"width": 10.0, "height": 4.0})
    )

    assert result["status"] == "unverifiable"
    assert result["unsupported_fields"] == ["height", "width"]
    assert "wall_thickness" in result["missing_fields"]


def test_semantically_narrow_screw_count_is_not_generic_hole_count() -> None:
    result = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"screw_hole_count": 2, "flat_surface_mount": True},
        )
    )

    assert result["status"] == "unverifiable"
    assert result["unsupported_fields"] == ["flat_surface_mount", "screw_hole_count"]
    assert "hole_count" in result["missing_fields"]


def test_output_scope_resolver_receives_normalized_requirement_without_scope_guessing() -> None:
    normalized = normalize_executable_cadquery_requirement(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"hole_count": 2},
            scope="upper/lower",
        )
    )
    result = resolve_executable_cadquery_output_scope(
        normalized["requirement"],
        available_output_ids=["upper", "lower"],
    )

    assert result["status"] == "resolved"
    assert result["output_ids"] == ["upper", "lower"]


def test_stl_hole_candidate_does_not_become_authoritative_failure() -> None:
    mesh = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    finding = _generic_requirement_finding(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"hole_count": 1, "hole_diameter": 2.0},
        ),
        mesh=mesh,
        output_id="primary",
        meshes={"primary": mesh},
    )

    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["evidence_source"] == "derived_stl_candidate"
    assert finding["measurements"]["physical_feature_count"] is None


def test_unsupported_qualifier_does_not_become_pass() -> None:
    mesh = trimesh.creation.box(extents=(10.0, 10.0, 2.0))
    finding = _generic_requirement_finding(
        _requirement(
            policy="final_mesh_opening_profiles",
            expected={"hole_count": 0, "flat_surface_mount": True},
        ),
        mesh=mesh,
        output_id="primary",
        meshes={"primary": mesh},
    )

    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False


def test_review_policy_remains_non_machine_required() -> None:
    requirement = _requirement(
        policy="final_mesh_opening_profiles",
        expected={"hole_count": 1},
        classification="review_required",
    )
    result = evaluate_semantic_policy(
        {"findings": [{"requirement_id": "synthetic-requirement", "status": "unverifiable", "measurement_available": False}]},
        {"requirements": [requirement]},
    )

    assert result["findings"][0]["policy"] == "review_required"
    assert result["findings"][0]["result"] == "review_required"


def test_semantic_policy_preserves_normalization_diagnostics_for_product_paths() -> None:
    requirement = _requirement(
        policy="final_mesh_opening_profiles",
        expected={"hole_count": 1},
    )
    diagnostics = {
        "version": "executable-cadquery-semantic-contract-v1",
        "status": "unsupported_semantic_fields",
        "unsupported_fields": ["flat_surface_mount"],
    }
    result = evaluate_semantic_policy(
        {
            "findings": [
                {
                    "requirement_id": "synthetic-requirement",
                    "status": "unverifiable",
                    "measurement_available": False,
                    "semantic_contract": diagnostics,
                }
            ]
        },
        {"requirements": [requirement]},
    )

    assert result["findings"][0]["semantic_contract"] == diagnostics
