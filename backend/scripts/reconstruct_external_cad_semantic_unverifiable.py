"""Reconstruct the semantic-unverifiable external development cluster.

This module is deliberately an evidence reader, not a recovery implementation.
It reads the frozen development survey records and produces a deterministic
ownership/classification report without constructing providers or workers.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


FAILURE_CLASS = "semantic_requirement_unverifiable"
MACHINE_REQUIRED = "machine_required"
REVIEW_REQUIRED = "review_required"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_ROOT = ROOT / "data/debug-sessions/external-benchmarks/cad-50-v1.1/development-first-pass"
DEFAULT_SPECS = ROOT / "benchmarks/external/cad-50-v1.1/comparison-specifications-development.json"


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_paths(evidence_root: Path) -> list[Path]:
    return sorted(
        [*evidence_root.glob("premise-only/*/run.json"), *evidence_root.glob("comparison-specification/*/run.json")]
    )


def load_semantic_cells(evidence_root: Path | str = DEFAULT_EVIDENCE_ROOT) -> list[dict[str, Any]]:
    """Select exactly the frozen development cells at the requested blocker."""

    root = Path(evidence_root)
    cells = [_read(path) for path in _run_paths(root)]
    selected = [cell for cell in cells if cell.get("failure_class") == FAILURE_CLASS]
    selected.sort(key=lambda cell: (cell.get("category", ""), cell["benchmark_project_id"], cell["mode"]))
    if len(selected) != 16:
        raise ValueError(f"expected 16 semantic cells, found {len(selected)}")
    if any("validation" in cell["benchmark_project_id"] or "holdout" in cell["benchmark_project_id"] for cell in selected):
        raise ValueError("validation or holdout detail was selected")
    return selected


def _spec_projects(specs_path: Path) -> dict[str, dict[str, Any]]:
    data = _read(specs_path)
    return {project["benchmark_id"]: project for project in data.get("projects", [])}


def _fact(project: dict[str, Any], fact_id: str) -> Any:
    for fact in project.get("reference_specification", {}).get("facts", []):
        if fact.get("id") == fact_id:
            return fact.get("value")
    for fact in project.get("facts", []):
        if fact.get("id") == fact_id:
            return fact.get("value")
    return None


def _expected_output_count(project: dict[str, Any]) -> int:
    value = _fact(project, "output_count")
    return int(value) if isinstance(value, (int, float)) else 1


def _is_envelope(requirement: dict[str, Any]) -> bool:
    identifier = str(requirement.get("requirement_id", ""))
    raw = str(requirement.get("raw_evidence", "")).lower()
    return "envelope" in identifier or "overall envelope" in raw or "bounding" in raw


# These are analysis judgments, not application rules.  They make the report
# explicit about claims that are qualitative despite being emitted as generic
# feature/qualitative requirements.  No production behavior imports this map.
QUALITATIVE_REVIEW_REQUIREMENTS = {
    "req_printable",
    "req_portable_case",
    "req_protect_cell",
    "req_instrument_usability",
    "req_protect_handling",
    "req_protect_electronics",
    "requiring_special_removal_tool",
    "standalone_usability",
    "req_airflow_path",
    "req_mount_type",
}

OUTPUT_STRUCTURE_REQUIREMENTS = {
    "req_two_part_case",
    "platform",
    "req_scale_assembly_components",
    "req_output_count",
    "req_printed_outputs_count",
}


def _classify(
    requirement: dict[str, Any],
    *,
    expected_output_count: int,
    contract_output_count: int,
) -> tuple[str, str]:
    """Assign one evidence-layer A-G primary category."""

    if requirement.get("classification") == REVIEW_REQUIRED:
        return "F", "correct review obligation; not itself a machine blocker"

    identifier = str(requirement.get("requirement_id", ""))
    authority = requirement.get("authority")
    kind = requirement.get("kind")
    operator = requirement.get("operator")

    if authority == "flexible":
        return "B", "model-design choice was emitted as machine-required; it should not block completion"
    if identifier in QUALITATIVE_REVIEW_REQUIREMENTS or (kind == "qualitative"):
        return "B", "qualitative/non-geometric claim requires review or informational policy"
    if identifier in OUTPUT_STRUCTURE_REQUIREMENTS:
        return "C", "output/component structure is not preserved in the executable contract"
    if expected_output_count > 1 and contract_output_count == 1 and _is_envelope(requirement):
        return "C", "part-scoped envelope is present but output identity was collapsed before verification"
    if expected_output_count > 1 and contract_output_count == 1 and identifier in {"platform"}:
        return "C", "part-local requirement has no distinct executable output scope"
    if _is_envelope(requirement) and kind == "dimension":
        return "A", "scalarized envelope cannot route to the existing final_mesh_bounds verifier"
    if kind in {"dimension", "clearance", "capacity", "feature", "count"}:
        return "E", "machine-required claim has no trustworthy registered deterministic verifier"
    return "E", "machine-required claim has no trustworthy registered deterministic verifier"


def _output_audit(cell: dict[str, Any], project: dict[str, Any]) -> dict[str, Any]:
    contract = cell.get("executable_contract", {}).get("contract", {})
    outputs = contract.get("outputs", [])
    generated = cell.get("worker", {}).get("outputs", [])
    expected = _expected_output_count(project)
    generated_ids = [item.get("output_id") for item in generated]
    contract_ids = [item.get("output_id") for item in outputs]
    object_type = contract.get("product_state", {}).get("object_type")
    return {
        "expected_printed_output_count": expected,
        "contract_output_count": len(outputs),
        "contract_output_ids": contract_ids,
        "generated_output_count": len(generated),
        "generated_output_ids": generated_ids,
        "generated_solid_counts": [item.get("solid_count") for item in generated],
        "output_loss": expected > 1 and len(outputs) == 1,
        "fallback_to_object_type_consistent": len(outputs) == 1 and contract_ids == [object_type],
        "pre_materialization_outputs_persisted": False,
        "fallback_invocation_provenance": "consistent_with_contract.py_fallback_but_not_directly_observable_in_compact_run",
        "owner_boundary": "requirement_extraction_or_design_specification_to_contract_materialization",
    }


def _requirement_record(
    requirement: dict[str, Any],
    ledger: dict[str, Any],
    contract: dict[str, Any],
    cell: dict[str, Any],
    project: dict[str, Any],
    output_audit: dict[str, Any],
) -> dict[str, Any]:
    contract_req = next(
        (item for item in contract.get("requirements", []) if item.get("requirement_id") == requirement.get("requirement_id")),
        None,
    )
    expected_count = output_audit["expected_printed_output_count"]
    contract_count = output_audit["contract_output_count"]
    category, basis = _classify(
        requirement,
        expected_output_count=expected_count,
        contract_output_count=contract_count,
    )
    return {
        "benchmark_project_id": cell["benchmark_project_id"],
        "mode": cell["mode"],
        "category": cell.get("category"),
        "requirement_id": requirement.get("requirement_id"),
        "kind": requirement.get("kind"),
        "operator": requirement.get("operator"),
        "raw_evidence": requirement.get("raw_evidence"),
        "original_extracted_requirement": next(
            (item for item in cell.get("requirement_extraction", {}).get("requirements", []) if item.get("requirement_id") == requirement.get("requirement_id")),
            None,
        ),
        "requirement_ledger_entry": requirement,
        "executable_contract_representation": contract_req,
        "output_scope": (contract_req or {}).get("scope", requirement.get("subject")),
        "authority": (contract_req or {}).get("authority", requirement.get("authority")),
        "classification": (contract_req or {}).get("classification", requirement.get("classification")),
        "expected_value": (contract_req or {}).get("expected", {"value": requirement.get("value")}),
        "verifier_policy": (contract_req or {}).get("verification_policy", requirement.get("verification_policy")),
        "available_worker_topology_brep_evidence": {
            "topology": cell.get("topology"),
            "worker_output_geometry": [item.get("geometry") for item in cell.get("worker", {}).get("outputs", [])],
            "requirement_specific_measurement_evidence_persisted": False,
        },
        "semantic_finding": {
            "aggregate_only": True,
            "cell_overall_status": cell.get("semantic", {}).get("overall_status"),
            "unsupported_verifier_count": cell.get("semantic", {}).get("unsupported_verifier"),
            "per_requirement_finding_persisted": False,
        },
        "final_blocker": {
            "observed_stage": cell.get("observed_stage"),
            "failure_class": cell.get("failure_class"),
            "first_incorrect_owner": cell.get("first_incorrect_owner"),
        },
        "primary_category": category,
        "classification_basis": basis,
        "analysis_note": "This is an offline ownership classification; no persisted run result was mutated.",
    }


def _envelope_audit(requirements: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in requirements:
        if item["classification"] != MACHINE_REQUIRED or item["kind"] != "dimension":
            continue
        if _is_envelope(item):
            groups[(item["benchmark_project_id"], item["mode"], item["raw_evidence"] or "")].append(item)
    records = []
    for (project, mode, raw), items in sorted(groups.items()):
        records.append({
            "benchmark_project_id": project,
            "mode": mode,
            "source_statement": raw,
            "scalar_requirement_ids": sorted(item["requirement_id"] for item in items),
            "scalar_count": len(items),
            "canonical_bounds_requirement_count": 0,
            "existing_final_mesh_bounds_capability": True,
            "scalar_verification_policy_count": sum(bool(item["verifier_policy"]) for item in items),
            "loss_boundary": "requirement_normalization_or_contract_materialization",
        })
    return {
        "source_statement_group_count": len(records),
        "scalarized_requirement_count": sum(item["scalar_count"] for item in records),
        "records": records,
        "conclusion": "A canonical bounds tuple was not preserved; scalar expected.value fields did not route to final_mesh_bounds.",
    }


def build_report(
    evidence_root: Path | str = DEFAULT_EVIDENCE_ROOT,
    specs_path: Path | str = DEFAULT_SPECS,
) -> dict[str, Any]:
    cells = load_semantic_cells(evidence_root)
    projects = _spec_projects(Path(specs_path))
    requirement_records: list[dict[str, Any]] = []
    cell_records = []
    for cell in cells:
        project = projects.get(cell["benchmark_project_id"], {})
        contract = cell.get("executable_contract", {}).get("contract", {})
        ledger = cell.get("requirement_ledger", {})
        audit = _output_audit(cell, project)
        records = [
            _requirement_record(req, ledger, contract, cell, project, audit)
            for req in contract.get("requirements", [])
        ]
        requirement_records.extend(records)
        cell_records.append({
            "benchmark_project_id": cell["benchmark_project_id"],
            "mode": cell["mode"],
            "category": cell.get("category"),
            "observed_stage": cell.get("observed_stage"),
            "failure_class": cell.get("failure_class"),
            "first_incorrect_owner": cell.get("first_incorrect_owner"),
            "semantic_aggregate": cell.get("semantic"),
            "requirement_extraction_record": cell.get("requirement_extraction"),
            "output_identity_audit": audit,
            "unsupported_requirement_ids": [item["requirement_id"] for item in records if item["classification"] == MACHINE_REQUIRED],
            "primary_category_counts": dict(Counter(item["primary_category"] for item in records if item["classification"] == MACHINE_REQUIRED)),
            "available_evidence": {
                "topology_valid": (cell.get("topology") or {}).get("valid"),
                "worker_execution_count": (cell.get("worker") or {}).get("execution_count"),
                "analytic_brep_outputs": sum(item.get("geometry", {}).get("authority") == "analytic_brep" for item in (cell.get("worker") or {}).get("outputs", [])),
                "semantic_finding_payload_persisted": False,
            },
            "counterfactual_completion_gate": None,
        })

    machine = [item for item in requirement_records if item["classification"] == MACHINE_REQUIRED]
    reviews = [item for item in requirement_records if item["classification"] == REVIEW_REQUIRED]
    category_counts = Counter(item["primary_category"] for item in machine)
    by_kind = Counter(item.get("kind") for item in machine)
    by_operator = Counter(item.get("operator") for item in machine)
    by_mode = Counter(item.get("mode") + ":" + item["primary_category"] for item in machine)
    by_category = Counter(item.get("category") + ":" + item["primary_category"] for item in machine)
    multi_projects = {
        cell["benchmark_project_id"]
        for cell in cell_records
        if cell["output_identity_audit"]["expected_printed_output_count"] > 1
    }
    single_multi = Counter(
        ("multi_part" if item["benchmark_project_id"] in multi_projects else "single_part") + ":" + item["primary_category"]
        for item in machine
    )
    counterfactual = []
    for cell in cell_records:
        categories = Counter(cell["primary_category_counts"])
        output_loss = cell["output_identity_audit"]["output_loss"]
        if output_loss or categories.get("C") or categories.get("E"):
            state = "candidate_blocked"
        elif categories.get("A") or categories.get("B"):
            state = "candidate_ready_for_review"
        else:
            state = "candidate_fully_verified"
        cell["counterfactual_completion_gate"] = {
            "representation_and_classification_only": True,
            "generated_geometry_preserved": True,
            "state": state,
            "not_a_mutation_of_persisted_run": True,
        }
        counterfactual.append({"benchmark_project_id": cell["benchmark_project_id"], "mode": cell["mode"], "state": state})

    return {
        "schema_version": "phase-1b-external-cad-semantic-unverifiable-reconstruction-v1",
        "scope": {
            "evidence_root": str(Path(evidence_root)),
            "selection": {"failure_class": FAILURE_CLASS, "development_cells_only": True, "holdout_details_loaded": False, "validation_details_loaded": False},
        },
        "inventory": {
            "cell_count": len(cell_records),
            "total_authoritative_requirements": len(requirement_records),
            "unsupported_requirement_count": len(machine),
            "review_requirement_count": len(reviews),
            "machine_pass": 0,
            "machine_fail": 0,
            "semantic_finding_payload_present": False,
        },
        "provider_calls": 0,
        "worker_executions": 0,
        "cells": cell_records,
        "requirements": requirement_records,
        "output_identity_audit": {
            "cells_with_expected_multi_part_output": sum(item["output_identity_audit"]["expected_printed_output_count"] > 1 for item in cell_records),
            "cells_with_contract_output_loss": sum(item["output_identity_audit"]["output_loss"] for item in cell_records),
            "records": [{"benchmark_project_id": item["benchmark_project_id"], "mode": item["mode"], **item["output_identity_audit"]} for item in cell_records],
            "conclusion": "Seven expected multi-part cells materialized one contract output; compact evidence cannot prove whether the missing outputs originated in extraction, DesignSpecification, ledger, or contract materialization.",
        },
        "envelope_canonicalization_audit": _envelope_audit(requirement_records),
        "qualitative_policy_audit": {
            "machine_required_qualitative_or_nongeometric_count": sum(item["kind"] in {"qualitative", "feature", "capacity", "clearance"} for item in machine),
            "flexible_machine_required_count": sum(item["authority"] == "flexible" for item in machine),
            "analysis_review_judgment_ids": sorted(QUALITATIVE_REVIEW_REQUIREMENTS),
            "conclusion": "Generic qualitative/non-geometric claims and flexible model choices require policy/authority review; legitimate explicit machine claims remain unsupported rather than being silently downgraded.",
        },
        "available_evidence_audit": {
            "topology_valid_cells": sum(bool((cell.get("topology") or {}).get("valid")) for cell in cells),
            "analytic_brep_cells": sum(any(item.get("geometry", {}).get("authority") == "analytic_brep" for item in (cell.get("worker") or {}).get("outputs", [])) for cell in cells),
            "requirement_specific_measurement_evidence_cells": 0,
            "existing_evidence_routing_failure_proven": False,
            "true_geometry_failure_proven": False,
            "conclusion": "Valid global topology/B-Rep evidence exists, but no requirement-specific measurement evidence was persisted for the unsupported findings; D and G are not established.",
        },
        "classification_methodology": {
            "A": "scalarized envelope dimension with existing final_mesh_bounds capability",
            "B": "flexible model choice or semantically qualitative/non-geometric claim emitted as machine-required",
            "C": "explicit output/part structure or part-scoped requirement lost with multi-output collapse",
            "D": "not assigned without proof that existing requirement-specific evidence was ignored",
            "E": "correctly machine-required representation with no trustworthy registered verifier",
            "F": "correct review obligation; distinguish from machine blocker",
            "G": "not assigned without supported deterministic verification and an actual geometry mismatch",
            "note": "A-G are evidence classifications only; no project-specific production rules were added.",
        },
        "classification_counts": dict(category_counts),
        "by_kind": dict(by_kind),
        "by_operator": dict(by_operator),
        "by_mode": dict(by_mode),
        "by_category": dict(by_category),
        "single_part_vs_multi_part": dict(single_multi),
        "legitimate_missing_verifiers": [
            {"requirement_id": item["requirement_id"], "benchmark_project_id": item["benchmark_project_id"], "mode": item["mode"], "kind": item["requirement_ledger_entry"].get("kind"), "basis": item["classification_basis"]}
            for item in machine if item["primary_category"] == "E"
        ],
        "completion_gate_counterfactual": {
            "states": dict(Counter(item["state"] for item in counterfactual)),
            "records": counterfactual,
            "interpretation": "Representation/classification corrections alone do not establish machine PASS; multi-output loss and legitimate missing verifiers leave blocked cells.",
        },
        "router_action_mapping": {
            "A": "normalize and re-evaluate locally",
            "B": "correct policy/contract classification; no provider geometry repair",
            "C": "return to requirement/DesignSpecification/contract boundary",
            "D": "rerun deterministic verification locally",
            "E": "block or route to review according to product policy; do not ask Gemini to blindly rewrite geometry",
            "F": "candidate review obligation",
            "G": "geometry revision may be appropriate",
        },
        "recommended_generic_recovery_order": [
            {"category": "A", "priority": 1, "reason": "existing verifier and earliest representation boundary; broad scalar envelope coverage"},
            {"category": "B", "priority": 2, "reason": "policy/authority correction can remove false machine blockers without geometry changes"},
            {"category": "C", "priority": 3, "reason": "multi-output loss is early-stage and cross-category"},
            {"category": "E", "priority": 4, "reason": "requires capability-specific evidence and should be developed by generic subcluster"},
            {"category": "D", "priority": 5, "reason": "not currently proven; audit again only when requirement-specific evidence exists"},
            {"category": "F", "priority": 6, "reason": "review obligation, not a machine recovery target"},
            {"category": "G", "priority": 7, "reason": "not established in this cluster"},
        ],
        "anti_overfitting_precheck": {
            "project_specific_production_logic_added": False,
            "frozen_dimensions_added_to_application": False,
            "prompts_or_models_changed": False,
            "provider_calls": 0,
            "worker_executions": 0,
            "validation_or_holdout_inspected": False,
            "historical_run_evidence_mutated": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--development-specs", type=Path, default=DEFAULT_SPECS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.evidence_root, args.development_specs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
