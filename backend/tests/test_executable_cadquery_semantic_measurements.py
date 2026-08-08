from __future__ import annotations

import json
from pathlib import Path

from app.services.executable_cadquery.semantic import (
    evaluate_executable_cadquery_semantics_for_outputs,
)


ROOT = (
    Path(__file__).resolve().parents[2]
    / "data/debug-sessions/executable-cadquery/recovery-wave-01/frozen-corpus"
)


def _frozen(project: str) -> tuple[dict, dict[str, Path]]:
    envelope = json.loads((ROOT / f"project-{project}" / "prompt-contract.json").read_text())
    contract = envelope["contract"]
    paths = {
        path.stem: path
        for path in (ROOT / f"project-{project}" / "revision" / "stl").glob("*.stl")
    }
    return contract, paths


def test_mesh_measurements_distinguish_authoritative_and_candidate_only_policies() -> None:
    contract, paths = _frozen("02")

    result = evaluate_executable_cadquery_semantics_for_outputs(
        stl_paths=paths,
        design_contract=contract,
    )

    findings = {item["requirement_id"]: item for item in result["findings"]}
    assert set(findings) >= {item["requirement_id"] for item in contract["requirements"]}
    for requirement in contract["requirements"]:
        finding = findings[requirement["requirement_id"]]
        if requirement.get("verification_policy") in {
            "final_mesh_opening_profiles",
            "final_mesh_opening_centers",
            "final_mesh_recess_profile",
        }:
            assert finding["status"] == "unverifiable"
            assert finding["measurement_available"] is False
            assert finding["evidence_source"] == "derived_stl_candidate"
        else:
            assert finding["measurement_available"] is True
    assert findings["coaxial_diameters"]["status"] == "passed"
    assert findings["through_bore"]["status"] == "unverifiable"
    assert findings["bolt_circle"]["status"] == "unverifiable"


def test_generic_mesh_measurements_cover_multi_output_requirement_policies() -> None:
    for project in ("04", "05"):
        contract, paths = _frozen(project)

        result = evaluate_executable_cadquery_semantics_for_outputs(
            stl_paths=paths,
            design_contract=contract,
        )

        findings = {item["requirement_id"]: item for item in result["findings"]}
        assert set(findings) >= {item["requirement_id"] for item in contract["requirements"]}
        for requirement in contract["requirements"]:
            finding = findings[requirement["requirement_id"]]
            if requirement.get("verification_policy") in {
                "final_mesh_opening_profiles",
                "final_mesh_opening_centers",
                "final_mesh_recess_profile",
            }:
                assert finding["status"] == "unverifiable"
                assert finding["measurement_available"] is False
                assert finding["evidence_source"] == "derived_stl_candidate"
            else:
                assert finding["measurement_available"] is True
