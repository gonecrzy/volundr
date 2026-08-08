from __future__ import annotations

from pathlib import Path

import trimesh

from app.services.executable_cadquery.semantic import evaluate_executable_cadquery_semantics_for_outputs


def _write_box(path: Path, *, extents: tuple[float, float, float]) -> None:
    trimesh.creation.box(extents=extents).export(path)


def _contract(*, requirement: dict, outputs: list[dict] | None = None) -> dict:
    return {
        "schema_version": "executable-cadquery-design-contract-v1",
        "project_id": "synthetic-topology-policy",
        "workflow_id": "synthetic-topology-policy-workflow",
        "revision_id": "synthetic-topology-policy-revision",
        "units": "mm",
        "outputs": outputs or [
            {
                "output_id": "primary",
                "required": True,
                "output_type": "printable_component",
                "expected_solid_count": 1,
            }
        ],
        "requirements": [requirement],
        "relationships": [],
        "protected_facts": [],
    }


def _requirement(**expected: object) -> dict:
    return {
        "requirement_id": "output_topology",
        "scope": "primary",
        "origin": "user_explicit",
        "authority": "required",
        "classification": "machine_required",
        "expected": expected,
        "tolerance": 0.0,
        "verification_policy": "topology_and_required_output",
    }


def test_topology_and_required_output_uses_resolved_identity_and_authoritative_topology(tmp_path: Path) -> None:
    mesh_path = tmp_path / "primary.stl"
    _write_box(mesh_path, extents=(12.0, 8.0, 4.0))

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"primary": mesh_path},
        design_contract=_contract(requirement=_requirement(count=1, connected=True)),
        topology_by_output={
            "primary": {
                "valid": True,
                "overall_shape_valid": True,
                "detected_solid_count": 1,
            }
        },
    )

    finding = result["findings"][0]
    assert finding["status"] == "passed"
    assert finding["measurement_available"] is True
    assert finding["measurements"]["resolved_output_ids"] == ["primary"]
    assert finding["measurements"]["topology"]["primary"]["connected"] is True


def test_topology_and_required_output_fails_when_authoritative_topology_is_disconnected(tmp_path: Path) -> None:
    mesh_path = tmp_path / "primary.stl"
    _write_box(mesh_path, extents=(12.0, 8.0, 4.0))

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"primary": mesh_path},
        design_contract=_contract(requirement=_requirement(count=1, connected=True)),
        topology_by_output={
            "primary": {
                "valid": False,
                "overall_shape_valid": True,
                "detected_solid_count": 2,
            }
        },
    )

    finding = result["findings"][0]
    assert finding["status"] == "failed"
    assert finding["measurement_available"] is True
    assert finding["measurements"]["topology"]["primary"]["connected"] is False


def test_topology_and_required_output_fails_closed_without_authoritative_topology(tmp_path: Path) -> None:
    mesh_path = tmp_path / "primary.stl"
    _write_box(mesh_path, extents=(12.0, 8.0, 4.0))

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"primary": mesh_path},
        design_contract=_contract(requirement=_requirement(count=1, connected=True)),
    )

    finding = result["findings"][0]
    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["measurements"]["reason"] == "authoritative_topology_evidence_missing"


def test_topology_and_required_output_requires_explicit_connected_semantics(tmp_path: Path) -> None:
    mesh_path = tmp_path / "primary.stl"
    _write_box(mesh_path, extents=(12.0, 8.0, 4.0))

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"primary": mesh_path},
        design_contract=_contract(requirement=_requirement(count=1)),
        topology_by_output={
            "primary": {
                "valid": True,
                "overall_shape_valid": True,
                "detected_solid_count": 1,
            }
        },
    )

    finding = result["findings"][0]
    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["measurements"]["reason"] == "connected_expectation_missing"
