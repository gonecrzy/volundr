from pathlib import Path

from backend.scripts.reconstruct_external_cad_semantic_unverifiable import (
    build_report,
    load_semantic_cells,
)


EVIDENCE_ROOT = Path(
    "data/debug-sessions/external-benchmarks/cad-50-v1.1/development-first-pass"
)


def test_selects_exactly_the_sixteen_semantic_cells_without_holdout_details() -> None:
    cells = load_semantic_cells(EVIDENCE_ROOT)

    assert len(cells) == 16
    assert all(cell["failure_class"] == "semantic_requirement_unverifiable" for cell in cells)
    assert not any("validation" in cell["benchmark_project_id"] for cell in cells)
    assert not any("holdout" in cell["benchmark_project_id"] for cell in cells)


def test_reconstruction_is_offline_and_classifies_every_machine_requirement() -> None:
    report = build_report(EVIDENCE_ROOT)

    assert report["inventory"]["cell_count"] == 16
    assert report["inventory"]["unsupported_requirement_count"] == 107
    assert report["provider_calls"] == 0
    assert report["worker_executions"] == 0
    assert len(report["requirements"]) == 135
    machine = [item for item in report["requirements"] if item["classification"] == "machine_required"]
    assert len(machine) == 107
    assert all(item["primary_category"] in set("ABCDEFG") for item in machine)
