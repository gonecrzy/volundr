from __future__ import annotations

from pathlib import Path

import trimesh

from app.services.executable_cadquery.semantic import (
    evaluate_executable_cadquery_semantics_for_outputs,
    resolve_executable_cadquery_output_scope,
)


def _contract(*requirements: dict, outputs: list[dict] | None = None) -> dict:
    return {
        "schema_version": "executable-cadquery-design-contract-v1",
        "project_id": "synthetic-output-scope",
        "workflow_id": "synthetic-workflow",
        "revision_id": "synthetic-revision",
        "units": "mm",
        "outputs": outputs or [
            {"output_id": "primary", "required": True, "output_type": "printable_component", "expected_solid_count": 1}
        ],
        "requirements": list(requirements),
        "relationships": [],
        "protected_facts": [],
    }


def _requirement(requirement_id: str, **fields: object) -> dict:
    return {
        "requirement_id": requirement_id,
        "origin": "user_explicit",
        "authority": "required",
        "classification": "machine_required",
        "expected": {},
        "tolerance": 0.25,
        **fields,
    }


def _write_box(path: Path, *, extents: tuple[float, float, float]) -> None:
    trimesh.creation.box(extents=extents).export(path)


def test_scope_resolver_uses_only_available_output_when_scope_is_absent() -> None:
    result = resolve_executable_cadquery_output_scope(
        _requirement("envelope"),
        available_output_ids=["primary"],
    )

    assert result["status"] == "resolved"
    assert result["scope_kind"] == "output_local"
    assert result["output_ids"] == ["primary"]


def test_scope_resolver_resolves_explicit_multi_output_identity() -> None:
    result = resolve_executable_cadquery_output_scope(
        _requirement("fit", scope="upper/lower"),
        available_output_ids=["upper", "lower"],
    )

    assert result["status"] == "resolved"
    assert result["scope_kind"] == "multi_output"
    assert result["output_ids"] == ["upper", "lower"]


def test_scope_resolver_uses_declared_aliases_and_component_identity() -> None:
    registry = {
        "upper": {"output_id": "upper", "aliases": ["Top Piece"], "component_id": "top_component"},
        "lower": {"output_id": "lower", "aliases": ["Bottom Piece"], "component_id": "bottom_component"},
    }

    alias_result = resolve_executable_cadquery_output_scope(
        _requirement("fit", scope="  top piece  "),
        available_output_ids=["upper", "lower"],
        output_registry=registry,
    )
    component_result = resolve_executable_cadquery_output_scope(
        _requirement("fit", component_id="bottom_component"),
        available_output_ids=["upper", "lower"],
        output_registry=registry,
    )

    assert alias_result["output_ids"] == ["upper"]
    assert component_result["output_ids"] == ["lower"]


def test_scope_resolver_honors_explicit_assembly_scope() -> None:
    result = resolve_executable_cadquery_output_scope(
        _requirement("assembly_clearance", scope_kind="assembly"),
        available_output_ids=["upper", "lower"],
    )

    assert result["status"] == "resolved"
    assert result["scope_kind"] == "assembly"
    assert result["output_ids"] == ["lower", "upper"]


def test_scope_resolver_rejects_unknown_explicit_scope_without_single_output_fallback() -> None:
    result = resolve_executable_cadquery_output_scope(
        _requirement("envelope", scope="not_declared"),
        available_output_ids=["primary"],
    )

    assert result["status"] == "unresolved"
    assert result["output_ids"] == []
    assert result["reason"] == "explicit_scope_not_found"


def test_scope_resolver_rejects_ambiguous_alias_and_unscoped_multi_output() -> None:
    registry = {
        "left": {"output_id": "left", "aliases": ["side"]},
        "right": {"output_id": "right", "aliases": ["side"]},
    }
    alias_result = resolve_executable_cadquery_output_scope(
        _requirement("fit", scope="side"),
        available_output_ids=["left", "right"],
        output_registry=registry,
    )
    unscoped_result = resolve_executable_cadquery_output_scope(
        _requirement("fit"),
        available_output_ids=["left", "right"],
    )

    assert alias_result["status"] == "ambiguous"
    assert unscoped_result["status"] == "ambiguous"


def test_output_local_measurement_cannot_use_another_output(tmp_path: Path) -> None:
    first = tmp_path / "first.stl"
    second = tmp_path / "second.stl"
    _write_box(first, extents=(10.0, 10.0, 2.0))
    _write_box(second, extents=(20.0, 20.0, 4.0))
    contract = _contract(
        _requirement(
            "local_envelope",
            scope="first/second",
            verification_policy="final_mesh_bounds",
            expected={"width": 10.0, "depth": 10.0, "height": 2.0},
        ),
        outputs=[
            {"output_id": "first", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
            {"output_id": "second", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
        ],
    )

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"first": first, "second": second},
        design_contract=contract,
    )
    finding = next(item for item in result["findings"] if item["requirement_id"] == "local_envelope")

    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["measurements"]["reason"] == "output_local_scope_requires_single_output"


def test_required_output_identity_verifier_handles_single_and_multiple_outputs(tmp_path: Path) -> None:
    first = tmp_path / "first.stl"
    second = tmp_path / "second.stl"
    _write_box(first, extents=(10.0, 10.0, 2.0))
    _write_box(second, extents=(20.0, 20.0, 4.0))

    single = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"first": first},
        design_contract=_contract(
            _requirement(
                "identity",
                scope="first",
                verification_policy="required_output_identity",
                expected={"count": 1, "output_id": "first"},
            ),
            outputs=[
                {"output_id": "first", "required": True, "output_type": "printable_component", "expected_solid_count": 1}
            ],
        ),
    )
    multiple = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"first": first, "second": second},
        design_contract=_contract(
            _requirement(
                "identity",
                scope="first/second",
                verification_policy="required_output_identity",
                expected={"count": 2, "independent": True},
            ),
            outputs=[
                {"output_id": "first", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
                {"output_id": "second", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
            ],
        ),
    )

    single_finding = next(item for item in single["findings"] if item["requirement_id"] == "identity")
    multiple_finding = next(item for item in multiple["findings"] if item["requirement_id"] == "identity")
    assert single_finding["status"] == "passed"
    assert single_finding["measurement_available"] is True
    assert multiple_finding["status"] == "passed"
    assert multiple_finding["measurement_available"] is True
    assert multiple_finding["measurements"]["resolved_output_ids"] == ["first", "second"]


def test_required_output_identity_fails_closed_for_ambiguous_scope(tmp_path: Path) -> None:
    first = tmp_path / "first.stl"
    second = tmp_path / "second.stl"
    _write_box(first, extents=(10.0, 10.0, 2.0))
    _write_box(second, extents=(20.0, 20.0, 4.0))

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths={"first": first, "second": second},
        design_contract=_contract(
            _requirement(
                "identity",
                verification_policy="required_output_identity",
                expected={"count": 1},
            ),
            outputs=[
                {"output_id": "first", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
                {"output_id": "second", "required": True, "output_type": "printable_component", "expected_solid_count": 1},
            ],
        ),
    )
    finding = next(item for item in result["findings"] if item["requirement_id"] == "identity")

    assert finding["status"] == "unverifiable"
    assert finding["measurement_available"] is False
    assert finding["measurements"]["reason"] == "output_scope_ambiguous"
