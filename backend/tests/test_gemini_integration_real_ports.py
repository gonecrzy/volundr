import json
from pathlib import Path

import pytest

from app.services.cad.geometry_slots import build_geometry_slot_manifest
from app.services.gemini_integration.capture import IntegrationEvidenceStore
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.gemini_integration.real_ports import build_real_boundary_ports


@pytest.mark.asyncio
async def test_real_ports_use_existing_slot_assembly_and_source_validator(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    store = IntegrationEvidenceStore(tmp_path, study_id="gemini-provider-contract-integration-01")
    ports = build_real_boundary_ports(profile=profile, evidence_store=store, jobs_root=tmp_path / "jobs")
    plan = {
        "components": [{"id": "base", "name": "base"}],
        "features": [],
        "printable_outputs": [{"id": "out", "component_id": "base", "expected_solid_count": 1}],
    }
    manifest = build_geometry_slot_manifest(plan, planning_depth="detailed_plan")
    geometry = {
        "slots": [{"slot_id": manifest["slots"][0]["slot_id"], "statements": ["body = cq.Workplane('XY').box(10, 10, 2)"], "result_symbol": "body"}],
    }

    assembled = await ports.assemble_source(
            project=type("Project", (), {"project_id": "project-001", "frozen_facts": {}})(),
        plan=plan,
        geometry=geometry,
        provenance={"study_id": "gemini-provider-contract-integration-01"},
    )
    validation = await ports.static_validate(source=assembled["source"], provenance={"study_id": "gemini-provider-contract-integration-01"})

    assert assembled["scaffold_hash"]
    assert "VOLUNDR_SCAFFOLD_VERSION" in assembled["source"]
    assert validation["valid"] is True
    assert validation["findings"] == []


@pytest.mark.asyncio
async def test_real_ports_fail_closed_on_invalid_geometry_slots(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    profile = GeminiFlashLiteContractV1.from_repository(repo)
    store = IntegrationEvidenceStore(tmp_path, study_id="representative-workflow-wave-02")
    ports = build_real_boundary_ports(profile=profile, evidence_store=store, jobs_root=tmp_path / "jobs")
    plan = {
        "components": [{"id": "base", "name": "base"}],
        "features": [],
        "printable_outputs": [{"id": "out", "component_id": "base", "expected_solid_count": 1}],
    }
    manifest = build_geometry_slot_manifest(plan, planning_depth="detailed_plan")
    geometry = {
        "slots": [
            {
                "slot_id": manifest["slots"][0]["slot_id"],
                "statements": ["body = None"],
                "result_symbol": "body",
            }
        ]
    }

    assembled = await ports.assemble_source(
        project=type("Project", (), {"project_id": "project-001", "frozen_facts": {}})(),
        plan=plan,
        geometry=geometry,
        provenance={"study_id": "representative-workflow-wave-02"},
    )

    assert assembled["source"] == ""
    assert assembled["failure_class"] == "source_assembly_failure"
    assert assembled["geometry_slot_validation"]["valid"] is False
