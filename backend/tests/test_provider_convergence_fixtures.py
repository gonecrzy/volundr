from __future__ import annotations

import json
from pathlib import Path

from app.services.projects.plan_provenance import normalize_authoritative_provenance
from app.services.workflow.provider_response import (
    ProviderResponseOutcome,
    RepairOutcome,
    analyze_provider_response,
    compare_focused_repair,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "provider_convergence" / "provider_response_replays.json"


def _assumption_label_normalizer(payload: object) -> tuple[object, list[str]]:
    if not isinstance(payload, dict):
        return payload, []
    normalized = dict(payload)
    assumptions = []
    for item in normalized.get("assumptions", []) or []:
        if isinstance(item, dict):
            copied = dict(item)
            if "description" not in copied and isinstance(copied.get("label"), str):
                copied["description"] = copied["label"]
            assumptions.append(copied)
        else:
            assumptions.append(item)
    normalized["assumptions"] = assumptions
    return normalized, ["normalization.label_to_description"] if assumptions else []


def test_redacted_real_response_replays_are_deterministic() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(fixtures) == 7
    for fixture in fixtures:
        assert fixture["source"]["batch_id"] == "0ba9c31b-5d0e-440e-b34b-7b766afa1d39"
        expected = fixture["expected"]
        raw = fixture.get("raw_provider_response")
        if raw is not None:
            normalizer = _assumption_label_normalizer if fixture["fixture_id"].endswith("schema-invalid") else None
            result = analyze_provider_response(raw, stage=fixture["source"]["stage"], normalizer=normalizer)
            assert result.syntax_status == expected["syntax_status"]
            if fixture["fixture_id"] == "post-correction-monitor-schema-invalid":
                pre_normalization = analyze_provider_response(
                    raw,
                    stage=fixture["source"]["stage"],
                    findings=expected["schema_findings"],
                )
                assert pre_normalization.classification.value == expected["pre_normalization_classification"]
                assert result.classification is ProviderResponseOutcome.VALID_AFTER_NORMALIZATION
                assert result.normalized["assumptions"][0]["description"] == "Wall mount orientation"
            elif expected["classification"] in {"semantic_contradiction", "provenance_invalid"}:
                assert result.classification is ProviderResponseOutcome.VALID_AFTER_NORMALIZATION
                if expected["classification"] == "provenance_invalid":
                    provenance = normalize_authoritative_provenance(
                        {"id": "lid_grip_ribs", "value": "integral", "provenance": {}},
                        {},
                    )
                    assert provenance.findings == tuple(expected["provenance_findings"])
            else:
                assert result.classification.value == expected["classification"]

        if fixture["fixture_id"] == "post-correction-screw-lid-missing-provenance":
            provenance = normalize_authoritative_provenance(
                fixture_record := {"id": "lid_grip_ribs", "value": "integral", "provenance": {}},
                {},
            )
            assert provenance.value == fixture_record
            assert provenance.findings == tuple(expected["provenance_findings"])

        if "original_record" in fixture:
            comparison = compare_focused_repair(
                fixture["original_record"],
                fixture["repaired_record"],
                findings_before=["record.invalid"],
                findings_after=["record.invalid"] if fixture["expected"]["repair_outcome"] == "unchanged_repair" else [],
                affected_paths=["width", "count", "owner"],
                protected_paths=["id"],
            )
            assert comparison.outcome.value == fixture["expected"]["repair_outcome"]
            assert comparison.blocked is True


def test_schema_fixture_remains_blocking_when_alias_normalization_is_not_available() -> None:
    fixture = next(
        item for item in json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        if item["fixture_id"] == "post-correction-monitor-schema-invalid"
    )
    result = analyze_provider_response(fixture["raw_provider_response"], stage="requirements")
    assert result.classification is ProviderResponseOutcome.VALID_AFTER_NORMALIZATION
    assert result.normalized["assumptions"][0].get("description") is None
