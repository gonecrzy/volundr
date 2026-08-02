from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.services.cad.geometry_bodies import GeometryBodyError, assemble_geometry_bodies, build_geometry_function_inventory
from app.services.cad.cadquery_source_authority import build_cadquery_source_authority, validate_cadquery_source_authority
from app.services.cad.parameter_effects import build_parameter_effect_contract
from app.services.cad.source_scaffold import SCAFFOLD_VERSION, render_cadquery_scaffold
from app.models.generation_attempt import GenerationAttempt
from app.services.projects.plan_constraints import normalize_plan_constraints
from app.services.projects.requirement_ledger import apply_requirement_delta, build_requirement_ledger
from app.services.projects.service import ProjectService, _control_source_inventory


def _plan(*, exposed_controls: list[dict] | None = None) -> dict:
    return {
        "parameters": [
            {
                "id": "bottle_diameter",
                "label": "Bottle diameter",
                "value": 81.0,
                "unit": "mm",
                "protected": True,
                "source_requirement_id": "bottle_diameter",
                "constraint_mode": "fixed_constraint",
            },
            {
                "id": "mounting_hole_diameter",
                "label": "Mounting hole diameter",
                "value": 4.2,
                "unit": "mm",
                "protected": True,
                "constraint_mode": "proposed_value",
            },
        ],
        "derived_parameters": [
            {
                "id": "holder_inner_diameter",
                "label": "Holder inner diameter",
                "value": 82.6,
                "unit": "mm",
                "expression": "bottle_diameter + 1.6",
                "depends_on": ["bottle_diameter"],
                "constraint_mode": "derived_parameter",
            }
        ],
        "dependency_edges": [
            {"from": "bottle_diameter", "to": "holder_inner_diameter", "relationship": "diameter"}
        ],
        "components": [{"id": "holder", "parameters": ["holder_inner_diameter"]}],
        "features": [
            {
                "id": "cavity",
                "component_id": "holder",
                "type": "containment",
                "description": "Bottle cavity",
                "parameters": ["holder_inner_diameter"],
            },
            {
                "id": "mounting_holes",
                "component_id": "holder",
                "type": "mounting_hole_group",
                "description": "Two mounting holes",
                "parameters": ["mounting_hole_diameter"],
            },
        ],
        "feature_layouts": [
            {
                "feature_id": "mounting_holes",
                "owning_component_id": "holder",
                "layout_mode": "fixed_positions",
                "required_count": 2,
                "positions": [{"x": 0, "y": 0, "z": -25}, {"x": 0, "y": 0, "z": 25}],
                "hole_axis": "Y",
            }
        ],
        "printable_outputs": [{"id": "holder", "component_ids": ["holder"]}],
        "exposed_controls": exposed_controls if exposed_controls is not None else [],
    }


def _body_payload(*, cavity: str = 'cq.Workplane("XY").cylinder(20, 83.6 / 2)', hole: str = "4.2") -> str:
    import json

    return json.dumps(
        {
            "schema_version": "cadquery-geometry-bodies-v2",
            "functions": [
                {
                    "function_id": "_ai_component_holder",
                    "statements": [f"body = {cavity}"],
                    "result_symbol": "body",
                },
                {
                    "function_id": "_ai_feature_cavity",
                    "statements": [f"modified = body.cut(cq.Workplane(\"XY\").cylinder(20, {hole} / 2))"],
                    "result_symbol": "modified",
                },
                {
                    "function_id": "_ai_feature_mounting_holes",
                    "statements": [
                        "points = [(0, 0, -25), (0, 0, 25)]",
                        "modified = body.pushPoints(points).hole(4.2)",
                    ],
                    "result_symbol": "modified",
                },
            ],
        }
    )


def _with_malformed_unused_derived(plan: dict) -> dict:
    result = deepcopy(plan)
    result["derived_parameters"].append(
        {
            "id": "unused_planning_value",
            "label": "Unused planning value",
            "unit": "mm",
            "expression": "missing_planning_input + 1",
            "depends_on": ["missing_planning_input"],
            "constraint_mode": "derived_parameter",
        }
    )
    return result


def test_ordinary_source_inventory_is_empty_but_exposed_controls_remain_strict() -> None:
    inventory = [
        {"requirement_id": "plate_width", "value": 80},
        {"requirement_id": "plate_thickness", "value": 6},
    ]

    assert _control_source_inventory({"exposed_controls": []}, inventory) == []
    assert _control_source_inventory(
        {"exposed_controls": [{"parameter_id": "plate_width"}]},
        inventory,
    ) == [inventory[0]]
    assert _control_source_inventory({}, inventory) == inventory


def test_unused_malformed_derived_dependency_is_diagnostic_only() -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(_plan()),
        request_context="Create an ordinary holder",
    )
    contract = build_parameter_effect_contract(plan)
    finding = next(
        item
        for item in contract["dependency_findings"]
        if item["parameter_id"] == "unused_planning_value"
    )

    assert finding["classification"] == "diagnostic_only"
    assert finding["blocking"] is False
    assert finding["rule_id"] == "planning.derived_dependency_unused_or_incomplete"
    assert "not_exposed" in finding["reasons"]
    assert "not_required_by_scaffold" in finding["reasons"]

    assembly = assemble_geometry_bodies(
        _body_payload(),
        build_geometry_function_inventory(plan),
    )
    assembly_finding = next(
        item
        for item in assembly.dependency_findings
        if item["parameter_id"] == "unused_planning_value"
    )
    assert assembly_finding["blocking"] is False
    rendered = render_cadquery_scaffold(plan, assembly.functions)
    assert rendered.source.startswith("# VOLUNDR_SCAFFOLD_VERSION:")


def test_ordinary_geometry_referencing_malformed_derived_value_remains_blocking() -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(_plan()),
        request_context="Create an ordinary holder",
    )

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(
            _body_payload(
                cavity='cq.Workplane("XY").cylinder(20, params["unused_planning_value"] / 2)'
            ),
            build_geometry_function_inventory(plan),
        )

    assert error.value.rule_id == "geometry_body.derived_dependency_broken"
    findings = error.value.details["findings"]
    finding = next(item for item in findings if item["parameter_id"] == "unused_planning_value")
    assert finding["blocking"] is True
    assert "referenced_by_geometry" in finding["reasons"]


def test_exposed_control_with_broken_dependency_remains_blocking() -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(
            _plan(exposed_controls=[{"parameter_id": "unused_planning_value"}])
        ),
        request_context="Expose the planning value as an adjustable control",
    )

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(_body_payload(), build_geometry_function_inventory(plan))

    assert error.value.rule_id == "geometry_body.derived_dependency_broken"
    finding = next(
        item
        for item in error.value.details["findings"]
        if item["parameter_id"] == "unused_planning_value"
    )
    assert finding["blocking"] is True
    assert "exposed_control" in finding["reasons"]


def test_derived_value_supporting_exposed_control_remains_blocking() -> None:
    plan = normalize_plan_constraints(
        _plan(exposed_controls=[{"parameter_id": "bottle_diameter"}]),
        request_context="Expose bottle diameter as an adjustable control",
    )
    plan["derived_parameters"].append(
        {
            "id": "broken_control_derived_value",
            "value": 82.0,
            "unit": "mm",
            "expression": "bottle_diameter + missing_control_input",
            "depends_on": ["bottle_diameter", "missing_control_input"],
            "constraint_mode": "derived_parameter",
        }
    )
    contract = build_parameter_effect_contract(plan)
    finding = next(
        item
        for item in contract["dependency_findings"]
        if item["parameter_id"] == "broken_control_derived_value"
    )

    assert finding["blocking"] is True
    assert "supports_exposed_control" in finding["reasons"]


def test_configurable_pattern_dependency_remains_blocking() -> None:
    plan = deepcopy(_plan())
    plan.pop("exposed_controls")
    plan["derived_parameters"].append(
        {
            "id": "broken_pattern_spacing",
            "value": 50.0,
            "unit": "mm",
            "expression": "missing_pattern_spacing + 1",
            "depends_on": ["missing_pattern_spacing"],
            "constraint_mode": "derived_parameter",
        }
    )
    plan["feature_layouts"][0].update(
        {
            "layout_mode": "uniform_linear",
            "count_parameter_id": "mounting_hole_count",
            "spacing_parameter_id": "broken_pattern_spacing",
            "arrangement_axis": "Z",
        }
    )
    plan["parameters"].append(
        {
            "id": "mounting_hole_count",
            "value": 2,
            "unit": "count",
            "protected": True,
        }
    )
    plan["patterns"] = [
        {
            "pattern_id": "mounting_hole_pattern",
            "owning_feature_id": "mounting_holes",
            "owning_component_id": "holder",
            "pattern_type": "linear",
            "point_parameter_id": "mounting_hole_points",
            "count_parameter_id": "mounting_hole_count",
            "spacing_parameter_id": "broken_pattern_spacing",
            "axis": "Z",
            "centered": True,
        }
    ]
    contract = build_parameter_effect_contract(plan)
    finding = next(
        item
        for item in contract["dependency_findings"]
        if item["parameter_id"] == "broken_pattern_spacing"
    )

    assert finding["blocking"] is True
    assert "required_by_configurable_pattern" in finding["reasons"]


def test_mixed_dependency_findings_reject_only_for_blocking_finding() -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(
            _plan(exposed_controls=[{"parameter_id": "unused_planning_value"}])
        ),
        request_context="Expose the planning value as an adjustable control",
    )
    plan["derived_parameters"].append(
        {
            "id": "another_unused_planning_value",
            "value": 3.0,
            "unit": "mm",
            "expression": "missing_other_input + 1",
            "depends_on": ["missing_other_input"],
            "constraint_mode": "derived_parameter",
        }
    )

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(_body_payload(), build_geometry_function_inventory(plan))

    findings = error.value.details["findings"]
    assert {item["parameter_id"] for item in findings} >= {
        "unused_planning_value",
        "another_unused_planning_value",
    }
    assert next(item for item in findings if item["parameter_id"] == "unused_planning_value")["blocking"] is True
    assert next(item for item in findings if item["parameter_id"] == "another_unused_planning_value")["blocking"] is False


def test_dependency_classification_is_persisted_in_scaffold_evidence(tmp_path) -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(_plan()),
        request_context="Create an ordinary holder",
    )
    attempt = GenerationAttempt(
        id="attempt-1",
        project_id="project-1",
        attempt_number=1,
        provider_id="fixture",
        prompt_version="test",
        ruleset_version="test",
        request_payload_path="",
        prompt_path="",
    )
    service = ProjectService(db=None, data_dir=tmp_path)  # type: ignore[arg-type]
    (tmp_path / "projects" / "project-1" / "generation-runs" / "attempt-1").mkdir(parents=True)

    service._prepare_generated_source(
        raw_output=_body_payload(),
        design_plan_payload=plan,
        generation_contract_version=SCAFFOLD_VERSION,
        attempt=attempt,
        workflow_run=None,
        role="initial_geometry",
    )

    manifest = json.loads(
        (tmp_path / "projects" / "project-1" / "generation-runs" / "attempt-1" / "scaffold-manifest.json").read_text()
    )
    finding = next(
        item
        for item in manifest["derived_dependency_findings"]
        if item["parameter_id"] == "unused_planning_value"
    )
    assert finding["classification"] == "diagnostic_only"
    assert finding["blocking"] is False
    assert finding["reasons"]


def test_source_authority_retains_unused_dependency_as_nonblocking_diagnostic() -> None:
    plan = normalize_plan_constraints(
        _with_malformed_unused_derived(_plan()),
        request_context="Create an ordinary holder",
    )
    assembly = assemble_geometry_bodies(_body_payload(), build_geometry_function_inventory(plan))
    source = render_cadquery_scaffold(plan, assembly.functions).source
    result = validate_cadquery_source_authority(source, build_cadquery_source_authority(plan))

    assert result["passed_hard_checks"] is True
    finding = next(
        item
        for item in result["diagnostic_findings"]
        if item["parameter_id"] == "unused_planning_value"
    )
    assert finding["severity"] == "warning"
    assert finding["is_blocking"] is False


def test_ordinary_design_does_not_block_on_missing_canonical_symbols() -> None:
    plan = normalize_plan_constraints(_plan(), request_context="Create a holder for an 81 mm bottle")
    contract = build_parameter_effect_contract(plan)

    assert contract["exposed_control_ids"] == []
    assert all(not function["required_parameter_effects"] for function in contract["functions"])
    assert assemble_geometry_bodies(_body_payload(), build_geometry_function_inventory(plan))


def test_explicit_exposed_control_keeps_strict_effect_validation() -> None:
    plan = normalize_plan_constraints(
        _plan(exposed_controls=[{"parameter_id": "bottle_diameter", "label": "Bottle diameter"}]),
        request_context="Expose bottle diameter as an adjustable control",
    )
    contract = build_parameter_effect_contract(plan)
    cavity = next(function for function in contract["functions"] if function["feature_id"] == "cavity")
    assert {item["parameter_id"] for item in cavity["required_parameter_effects"]} == {
        "bottle_diameter",
        "holder_inner_diameter",
    }

    with pytest.raises(GeometryBodyError) as error:
        assemble_geometry_bodies(_body_payload(), build_geometry_function_inventory(plan))

    assert error.value.rule_id in {
        "geometry_body.dimension_bypassed_by_literal",
        "geometry_body.required_effect_missing",
    }


def test_numeric_request_does_not_auto_expose_control_but_explicit_request_does() -> None:
    ordinary = normalize_plan_constraints(_plan(), request_context="Create a holder for an 81 mm bottle")
    assert ordinary["exposed_controls"] == []

    requested = normalize_plan_constraints(
        _plan(),
        request_context="Expose bottle diameter as an adjustable control.",
    )
    assert [item["parameter_id"] for item in requested["exposed_controls"]] == ["bottle_diameter"]


def test_requirement_delta_supersedes_only_the_changed_requirement() -> None:
    ledger = build_requirement_ledger(
        [
            {
                "requirement_id": "bottle_diameter",
                "source": "initial_user",
                "type": "exact_dimension",
                "value": 81,
                "unit": "mm",
                "explicit": True,
            },
            {
                "requirement_id": "mounting_hole_count",
                "source": "initial_user",
                "type": "count",
                "value": 2,
                "explicit": True,
            },
        ]
    )

    revised = apply_requirement_delta(
        ledger,
        [
            {
                "operation": "change",
                "requirement_id": "fit_clearance",
                "type": "clearance",
                "value": 0.5,
                "unit": "mm",
                "source": "physical_test_feedback",
                "explicit": True,
            }
        ],
        originating_message="The printed fit is too tight. Add 0.5 mm clearance per side.",
    )

    active = {item["requirement_id"]: item for item in revised["requirements"] if item["status"] == "active"}
    assert set(active) == {"bottle_diameter", "mounting_hole_count", "fit_clearance"}
    assert active["bottle_diameter"]["value"] == 81
    assert active["fit_clearance"]["value"] == 0.5
    assert any(
        item["requirement_id"] == "fit_clearance" and item["status"] == "superseded"
    for item in revised["requirements"]
    ) is False


def test_requirement_delta_supersedes_an_existing_value_and_keeps_history() -> None:
    ledger = build_requirement_ledger(
        [{
            "requirement_id": "fit_clearance_per_side",
            "source": "volundr_proposal",
            "type": "clearance",
            "value": 0.8,
            "unit": "mm",
        }]
    )
    revised = apply_requirement_delta(
        ledger,
        [{
            "operation": "change",
            "requirement_id": "fit_clearance_per_side",
            "type": "clearance",
            "value": 1.3,
            "unit": "mm",
            "source": "physical_test_feedback",
            "explicit": True,
        }],
        originating_message="The printed fit is too tight. Add clearance.",
    )
    active = [item for item in revised["requirements"] if item["status"] == "active"]
    assert len(active) == 1
    assert active[0]["value"] == 1.3
    assert any(
        item["status"] == "superseded"
        and item["value"] == 0.8
        and item["superseded_by"] == "fit_clearance_per_side"
        for item in revised["requirements"]
    )


def test_long_ordinary_revision_chain_stays_recoverable_without_controls() -> None:
    ledger = build_requirement_ledger(
        [{"requirement_id": "bottle_diameter", "type": "exact_dimension", "value": 81, "unit": "mm"}]
    )
    for index in range(20):
        ledger = apply_requirement_delta(
            ledger,
            [{
                "operation": "add",
                "requirement_id": f"revision_note_{index}",
                "type": "qualitative_behavior",
                "value": f"ordinary revision {index}",
                "source": "revision_user",
            }],
            originating_message=f"Revision {index}",
        )
    assert len([item for item in ledger["requirements"] if item["status"] == "active"]) == 21
    assert next(item for item in ledger["requirements"] if item["requirement_id"] == "bottle_diameter")["value"] == 81
