from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.services.cad.cadquery_contract import validate_cadquery_source
from app.services.executable_cadquery.contract import (
    ExecutableCadQueryContractError,
    parse_executable_cadquery_response,
)
from app.services.executable_cadquery.dialect import (
    CADQUERY_V1_SOURCE_SKELETON,
    CADQUERY_V1_SOURCE_DIALECT_VERSION,
    cadquery_v1_source_dialect,
    cadquery_v1_source_dialect_hash,
)
from app.services.executable_cadquery.fixtures import FROZEN_MOUNTING_BRACKET_CONTRACT


def test_dialect_policy_is_versioned_hashed_and_skeleton_matches_validator() -> None:
    policy = cadquery_v1_source_dialect()

    assert policy["version"] == CADQUERY_V1_SOURCE_DIALECT_VERSION
    assert policy["hash"] == cadquery_v1_source_dialect_hash()
    assert policy["allowed_top_level_statements"]
    assert "If" in policy["forbidden_top_level_statements"]
    assert policy["control_flow_inside_functions"]["if"] is True
    assert policy["control_flow_inside_functions"]["try"] is False
    assert validate_cadquery_source(CADQUERY_V1_SOURCE_SKELETON).output_ids == [
        "mounting_bracket"
    ]


def test_validator_calibration_matches_advertised_dialect() -> None:
    valid = CADQUERY_V1_SOURCE_SKELETON
    local_if = valid.replace(
        "def _make_model():\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
        "def _make_model():\n    if True:\n        return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
    )
    local_loop = valid.replace(
        "def _make_model():\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
        "def _make_model():\n    for _ in range(1):\n        pass\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
    )

    assert validate_cadquery_source(local_if).output_ids == ["mounting_bracket"]
    assert validate_cadquery_source(local_loop).output_ids == ["mounting_bracket"]

    cases = {
        "top_level_if_forbidden": valid + '\nif __name__ == "__main__":\n    pass\n',
        "try_statement_forbidden": valid.replace(
            "def _make_model():\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
            "def _make_model():\n    try:\n        return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)\n    except Exception:\n        return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
        ),
        "unsafe_call_forbidden": valid.replace(
            "def _make_model():\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
            'def _make_model():\n    open("blocked")\n    return cq.Workplane("XY").box(1.0, 1.0, 1.0)',
        ),
        "artifact_export_forbidden": valid.replace(
            "def _make_model():\n    return cq.Workplane(\"XY\").box(1.0, 1.0, 1.0)",
            'def _make_model():\n    cq.exporters.export(cq.Workplane("XY"), "blocked.step")\n    return cq.Workplane("XY").box(1.0, 1.0, 1.0)',
        ),
    }

    for code, source in cases.items():
        with pytest.raises(ExecutableCadQueryContractError) as exc_info:
            parse_executable_cadquery_response(source, FROZEN_MOUNTING_BRACKET_CONTRACT)
        assert exc_info.value.diagnostic["code"] == code
        assert exc_info.value.diagnostic["line"] >= 1
        assert exc_info.value.diagnostic["node_type"]
        assert exc_info.value.diagnostic["ast_path"]


def _historical_response_paths() -> list[Path]:
    return sorted(
        path
        for root in Path("/tmp").glob("volundr-live-e2e.*")
        for path in root.rglob("attempt-*-provider-response.txt")
    )


def test_historical_provider_responses_replay_with_hashes_and_progress() -> None:
    paths = _historical_response_paths()
    if len(paths) < 2:
        pytest.skip("protected live responses are not available in this workspace")

    first, second = (path.read_text(encoding="utf-8") for path in paths[:2])
    errors: list[ExecutableCadQueryContractError] = []
    for response in (first, second):
        with pytest.raises(ExecutableCadQueryContractError) as exc_info:
            parse_executable_cadquery_response(response, FROZEN_MOUNTING_BRACKET_CONTRACT)
        errors.append(exc_info.value)

    first_error, second_error = errors
    assert first_error.diagnostic["code"] == "try_statement_forbidden"
    assert second_error.diagnostic["code"] == "top_level_if_forbidden"
    assert first_error.extracted_source_hash
    assert second_error.extracted_source_hash
    assert first_error.extracted_source_hash != second_error.extracted_source_hash
    assert hashlib.sha256(first.encode()).hexdigest() != hashlib.sha256(second.encode()).hexdigest()
    assert second_error.extracted_source


def test_dialect_summary_is_json_safe_and_contains_no_geometry_strategy() -> None:
    rendered = json.dumps(cadquery_v1_source_dialect(), sort_keys=True).lower()

    assert "workplane" not in rendered
    assert "boolean" not in rendered
    assert "sketch order" not in rendered
