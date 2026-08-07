from __future__ import annotations

from pathlib import Path

import pytest

from scripts.replay_executable_cadquery_topology import (
    PROJECT_IDS,
    build_repair_gate_decision,
    resolve_authoritative_project,
    validate_authoritative_chain,
)


def test_frozen_projects_resolve_to_matching_authoritative_identity_chains() -> None:
    resolved = {
        project_id: resolve_authoritative_project(project_id)
        for project_id in PROJECT_IDS
    }

    assert resolved["project-02"]["identity"] == {
        "project_id": "project-02",
        "database_project_id": "5b123fad-54a3-440d-82eb-67be6fb492c5",
        "workflow_id": "1b8ef86f-004c-4e57-9a3c-39068f443355",
        "revision_id": "8830450d-882c-4fbd-a6ba-768579d0e9b8",
        "job_id": "8830450d-882c-4fbd-a6ba-768579d0e9b8",
    }
    assert resolved["project-03"]["identity"]["workflow_id"] == (
        "59614cec-7a42-47ea-bda8-8d5a14755695"
    )
    assert resolved["project-04"]["identity"]["revision_id"] == (
        "5bfd8004-9bb3-4527-a1a9-630e0a00d6af"
    )
    assert all(item["hash_verification"]["valid"] for item in resolved.values())


def test_authoritative_chain_rejects_a_superseded_worker_result(tmp_path: Path) -> None:
    resolved = resolve_authoritative_project("project-04")
    stale_result = tmp_path / "stale-result.json"
    stale_result.write_text(
        Path(resolved["worker_result_path"]).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    stale_result.write_text(
        stale_result.read_text(encoding="utf-8").replace(
            '"job_id": "5bfd8004-9bb3-4527-a1a9-630e0a00d6af"',
            '"job_id": "ae32804b-082c-4e73-91d0-219edb79a0b5"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="superseded worker result"):
        validate_authoritative_chain(resolved, result_path=stale_result)


def test_gate_prioritizes_p3_and_does_not_authorize_stale_p2_or_p4() -> None:
    assert build_repair_gate_decision(
        "project-03",
        materially_new=True,
        actionable=True,
        authoritative=True,
    ) == {
        "project_id": "project-03",
        "action": "one_l2_repair",
        "authorized": True,
        "priority": 1,
    }
    assert build_repair_gate_decision(
        "project-02",
        materially_new=True,
        actionable=True,
        authoritative=False,
    )["authorized"] is False
    assert build_repair_gate_decision(
        "project-04",
        materially_new=False,
        actionable=True,
        authoritative=True,
    )["authorized"] is False
