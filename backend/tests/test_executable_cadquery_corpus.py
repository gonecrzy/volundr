from __future__ import annotations

import json

import pytest

from app.services.executable_cadquery.corpus import (
    REPEATABILITY_CORPUS_SCHEMA_VERSION,
    load_repeatability_contract,
)


def _contract() -> dict[str, object]:
    return {
        "schema_version": "executable-cadquery-design-contract-v1",
        "project_id": "fixture-project",
        "workflow_id": "fixture-workflow",
        "revision_id": "fixture-revision",
        "units": "mm",
        "outputs": [
            {
                "output_id": "main_part",
                "required": True,
                "output_type": "printable_component",
                "expected_solid_count": 1,
            }
        ],
        "requirements": [{"requirement_id": "overall_dimensions"}],
        "relationships": [],
        "protected_facts": [],
    }


def test_loads_the_contract_for_one_exact_frozen_prompt(tmp_path) -> None:
    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPEATABILITY_CORPUS_SCHEMA_VERSION,
                "projects": [
                    {
                        "project_id": "project-01",
                        "prompt": "Build the frozen project.",
                        "contract": _contract(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    project_id, contract = load_repeatability_contract(
        manifest_path,
        prompt="Build the frozen project.",
    )

    assert project_id == "project-01"
    assert contract["outputs"][0]["output_id"] == "main_part"


def test_rejects_a_prompt_that_is_not_registered(tmp_path) -> None:
    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": REPEATABILITY_CORPUS_SCHEMA_VERSION,
                "projects": [
                    {
                        "project_id": "project-01",
                        "prompt": "Build the frozen project.",
                        "contract": _contract(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="prompt is not registered"):
        load_repeatability_contract(manifest_path, prompt="A changed prompt.")
