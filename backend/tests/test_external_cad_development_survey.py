import json
from pathlib import Path

import pytest

from app.services.external_benchmarks.survey import (
    SURVEY_MODES,
    build_survey_order,
    load_frozen_development_projects,
    reference_similarity_status,
)


ROOT = Path(__file__).resolve().parents[2]
V11_MANIFEST = ROOT / "benchmarks/external/cad-50-v1.1/manifest.json"
V1_MANIFEST = ROOT / "benchmarks/external/cad-50-v1/manifest.json"
V11_SPECS = ROOT / "benchmarks/external/cad-50-v1.1/comparison-specifications-development.json"


def test_frozen_loader_selects_only_the_30_development_projects():
    projects = load_frozen_development_projects(V11_MANIFEST, V1_MANIFEST, V11_SPECS)

    assert len(projects) == 30
    assert {project.split_assignment for project in projects} == {"development"}
    assert len({project.benchmark_id for project in projects}) == 30
    assert all(project.premise for project in projects)
    assert all(project.comparison_prompt for project in projects)


def test_survey_order_has_two_passes_and_six_replacement_exclusions():
    projects = load_frozen_development_projects(V11_MANIFEST, V1_MANIFEST, V11_SPECS)
    order = build_survey_order(projects)

    assert len(order) == 60
    assert [cell.mode for cell in order[:30]] == ["premise_only"] * 30
    assert [cell.mode for cell in order[30:]] == ["comparison_specification"] * 30
    excluded = [cell for cell in order if cell.excluded]
    assert len(excluded) == 6
    assert {cell.benchmark_id for cell in excluded} == {
        "functional-assembly-002",
        "jig-guide-002",
        "stand-support-002",
    }
    assert all(cell.exclusion_reason == "replacement_required" for cell in excluded)


def test_comparison_prompt_is_frozen_and_not_premise_only():
    projects = load_frozen_development_projects(V11_MANIFEST, V1_MANIFEST, V11_SPECS)
    adapter = next(project for project in projects if project.benchmark_id == "adapter-coupler-002")

    assert adapter.premise != adapter.comparison_prompt
    assert adapter.comparison_specification_hash
    assert adapter.reference_set_sha256
    assert adapter.reference_similarity_status == "eligible"


def test_replacement_and_underconstrained_similarity_are_never_eligible():
    assert reference_similarity_status("comparison_ready", generated=True) == "eligible"
    assert reference_similarity_status("needs_spec_enrichment", generated=True) == "specification_underconstrained"
    assert reference_similarity_status("replacement_required", generated=True) == "replacement_required"
    assert reference_similarity_status("comparison_ready", generated=False) == "unavailable"


def test_loader_rejects_manifest_split_or_spec_mismatch(tmp_path):
    payload = json.loads(V11_MANIFEST.read_text())
    payload["projects"] = [item for item in payload["projects"] if item["split_assignment"] != "development"]
    bad_manifest = tmp_path / "manifest.json"
    bad_manifest.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="exactly 30 development"):
        load_frozen_development_projects(bad_manifest, V1_MANIFEST, V11_SPECS)


def test_survey_modes_are_frozen():
    assert SURVEY_MODES == ("premise_only", "comparison_specification")
