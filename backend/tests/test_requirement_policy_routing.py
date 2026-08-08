from __future__ import annotations

from app.services.executable_cadquery.contract import build_executable_cadquery_product_contract
from app.services.executable_cadquery.semantic_policy import evaluate_semantic_policy
from app.services.requirements.policy import (
    REQUIREMENT_POLICY_VERSION,
    resolve_product_requirement_policy,
)
from app.services.requirements.trace import normalize_composite_requirement_parts


def _requirement(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "requirement_id": "requirement",
        "source": "initial_user",
        "explicit": True,
        "authority": "explicit",
        "protected": True,
        "kind": "qualitative",
        "operator": "qualitative",
        "value": "a useful design",
        "raw_evidence": "Make a useful design.",
    }
    value.update(overrides)
    return value


def test_flexible_model_choice_is_informational_and_unprotected() -> None:
    result = resolve_product_requirement_policy(
        _requirement(
            requirement_id="wall_thickness",
            source="ai_assumption",
            explicit=False,
            authority="flexible",
            protected=False,
            kind="dimension",
            operator="exact",
            value=2.0,
            unit="mm",
            semantic_role="delegated_choice",
        )
    )

    assert result["policy"] == "informational"
    assert result["classification"] == "informational"
    assert result["authority"] == "flexible"
    assert result["protected"] is False
    assert result["policy_version"] == REQUIREMENT_POLICY_VERSION


def test_explicit_numeric_and_structural_facts_have_a_machine_hard_floor() -> None:
    for requirement in (
        _requirement(
            requirement_id="clearance",
            kind="clearance",
            operator="exact",
            value=2.0,
            unit="mm",
            classification="informational",
        ),
        _requirement(
            requirement_id="open_top",
            kind="feature",
            operator="present",
            value=True,
            classification="review_required",
        ),
        _requirement(
            requirement_id="body_envelope",
            kind="dimension",
            operator="approximately",
            value={"width": 80, "depth": 60, "height": 30},
            classification="review_required",
        ),
    ):
        result = resolve_product_requirement_policy(requirement)
        assert result["policy"] == "machine_required"
        assert result["classification"] == "machine_required"


def test_flexible_bounds_keep_recovery_a_shape_without_becoming_a_blocker() -> None:
    result = resolve_product_requirement_policy(
        _requirement(
            requirement_id="model_envelope",
            source="ai_assumption",
            explicit=False,
            authority="flexible",
            protected=False,
            kind="dimension",
            operator="approximately",
            value={"width": 80, "depth": 60, "height": 30},
            verification_policy="final_mesh_bounds",
        )
    )

    assert result["policy"] == "informational"
    assert result["protected"] is False


def test_explicit_output_structure_and_count_are_machine_required() -> None:
    for item in (
        _requirement(
            requirement_id="required_outputs",
            kind="output_count",
            operator="exact",
            value=2,
            raw_evidence="Require exactly two separately printable outputs.",
        ),
        _requirement(
            requirement_id="body_output",
            kind="printable_output",
            operator="present",
            value=True,
            required=True,
            output_id="body",
            raw_evidence="The body output is required.",
        ),
    ):
        assert resolve_product_requirement_policy(item)["policy"] == "machine_required"


def test_explicit_structural_feature_and_airflow_path_remain_hard() -> None:
    for item in (
        _requirement(
            requirement_id="open_top",
            kind="feature",
            operator="present",
            value=True,
        ),
        _requirement(
            requirement_id="airflow_path",
            kind="feature",
            operator="qualitative",
            value="usable",
            subject="airflow path",
            raw_evidence="Maintain a usable airflow path.",
        ),
    ):
        assert resolve_product_requirement_policy(item)["policy"] == "machine_required"


def test_provider_policy_cannot_downgrade_or_upgrade_application_authority() -> None:
    hard = resolve_product_requirement_policy(
        _requirement(
            requirement_id="minimum_wall",
            kind="dimension",
            operator="minimum",
            value=2,
            unit="mm",
            classification="informational",
        )
    )
    flexible = resolve_product_requirement_policy(
        _requirement(
            requirement_id="proposed_wall",
            source="ai_assumption",
            explicit=False,
            authority="flexible",
            protected=False,
            kind="dimension",
            operator="exact",
            value=2,
            unit="mm",
            classification="machine_required",
        )
    )

    assert hard["policy"] == "machine_required"
    assert flexible["policy"] == "informational"


def test_review_and_informational_missing_evidence_remain_distinct() -> None:
    requirements = [
        _requirement(
            requirement_id="printability",
            kind="qualitative",
            semantic_role="qualitative_objective",
            value="easy to print",
        ),
        _requirement(
            requirement_id="context",
            kind="design_context",
            semantic_role="design_context",
            value="desktop tray",
        ),
    ]
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic",
        workflow_id="workflow",
        revision_id="revision",
        specification={"schema_version": "1.0", "object_type": "tray"},
        active_requirements=requirements,
    )
    result = evaluate_semantic_policy({"findings": []}, contract)

    assert result["status"] == "review_required"
    assert result["review_required"] == ["printability"]
    assert result["unsupported_verifier"] == []
    assert {item["requirement_id"]: item["result"] for item in result["findings"]} == {
        "printability": "review_required",
        "context": "informational",
    }


def test_explicit_qualitative_objective_is_review_required() -> None:
    result = resolve_product_requirement_policy(
        _requirement(
            requirement_id="printability",
            kind="qualitative",
            semantic_role="qualitative_objective",
            value="easy to print",
            classification="machine_required",
        )
    )

    assert result["policy"] == "review_required"
    assert result["classification"] == "review_required"
    assert result["authority"] == "explicit"
    assert result["protected"] is True


def test_fit_and_compatibility_do_not_become_informational() -> None:
    for kind in ("fit", "compatibility", "relationship"):
        result = resolve_product_requirement_policy(
            _requirement(
                requirement_id=f"{kind}_requirement",
                kind=kind,
                semantic_role="structural_intent",
                value="must fit the mating part",
            )
        )
        assert result["policy"] == "machine_required"


def test_pure_design_context_is_informational() -> None:
    result = resolve_product_requirement_policy(
        _requirement(
            requirement_id="mount_context",
            kind="design_context",
            semantic_role="design_context",
            value="wall mount",
        )
    )

    assert result["policy"] == "informational"


def test_b5_parts_receive_independent_policy_without_authority_leak() -> None:
    composite = {
        "id": "mixed_request",
        "source": "user",
        "explicit": True,
        "authority": "explicit",
        "protected": True,
        "source_fact_id": "fact-1",
        "semantic_parts": [
            {
                "id": "clearance_choice",
                "semantic_role": "delegated_choice",
                "independent": True,
                "delegated": True,
                "source": "user",
                "explicit": False,
                "authority": "flexible",
                "protected": False,
                "kind": "clearance",
                "operator": "delegated",
                "value": 0.4,
            },
            {
                "id": "printability",
                "semantic_role": "qualitative_objective",
                "independent": True,
                "source": "user",
                "explicit": True,
                "authority": "explicit",
                "protected": True,
                "kind": "qualitative",
                "operator": "qualitative",
                "value": "easy to print",
            },
        ],
    }
    result = normalize_composite_requirement_parts([composite])
    delegated = resolve_product_requirement_policy(result[0])
    qualitative = resolve_product_requirement_policy(result[1])

    assert delegated["policy"] == "informational"
    assert delegated["protected"] is False
    assert qualitative["policy"] == "review_required"
    assert qualitative["protected"] is True


def test_contract_uses_application_policy_and_keeps_machine_missing_evidence_fail_closed() -> None:
    contract = build_executable_cadquery_product_contract(
        project_id="synthetic",
        workflow_id="workflow",
        revision_id="revision",
        specification={"schema_version": "1.0", "object_type": "tray"},
        active_requirements=[
            _requirement(
                requirement_id="printability",
                kind="qualitative",
                semantic_role="qualitative_objective",
                value="easy to print",
                classification="machine_required",
            ),
            _requirement(
                requirement_id="clearance",
                kind="clearance",
                operator="exact",
                value=2.0,
                unit="mm",
                classification="informational",
            ),
        ],
    )

    by_id = {item["requirement_id"]: item for item in contract["requirements"]}
    assert by_id["printability"]["classification"] == "review_required"
    assert by_id["clearance"]["classification"] == "machine_required"
    semantic = evaluate_semantic_policy({"findings": []}, contract)
    assert semantic["status"] == "unsupported_verifier"
    assert semantic["review_required"] == ["printability"]
    assert semantic["unsupported_verifier"] == ["clearance"]


def test_policy_routing_does_not_create_benchmark_specific_semantics() -> None:
    result = resolve_product_requirement_policy(_requirement(raw_evidence="A generic holder."))
    assert "mounting-bracket" not in repr(result)
    assert "Printables" not in repr(result)
