import json
from pathlib import Path

from app.services.gemini_consistency.replay import (
    OfflineReplayEngine,
    ReplayConfig,
)


def _write_call(root: Path) -> None:
    path = root / "baseline" / "repetition-01" / "projects" / "case-001" / "project-001" / "provider-calls" / "call-001.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "fixture_version": "gemini-live-response-v1",
                "study_id": "study",
                "round": "baseline",
                "repetition": 1,
                "case_id": "case-001",
                "project_id": "project-001",
                "provider_call_id": "call-001",
                "stage": "requirements",
                "response": {"raw_text": "```json\n{\"ready\": true,}\n```"},
                "processing": {"parse_classification": "invalid_json", "accepted": False},
                "downstream": {"final_blocker": "invalid_json"},
            }
        ),
        encoding="utf-8",
    )


def test_replay_from_raw_is_offline_and_records_provenance(tmp_path: Path) -> None:
    root = tmp_path / "study"
    _write_call(root)

    result = OfflineReplayEngine(
        ReplayConfig(study_root=root, offline_required=True, start_from="raw_provider_response")
    ).run()

    assert result["provider_calls"] == 0
    assert result["replayed_count"] == 1
    record = result["results"][0]
    assert record["replay_starting_point"] == "raw_provider_response"
    assert record["original_classification"] == "invalid_json"
    assert record["replay_classification"] == "valid_after_normalization"
    assert record["regression_improvement"] == "correctly_normalized"
    assert record["source_live_record"] == "call-001"


def test_replay_from_worker_result_does_not_reparse_or_call_provider(tmp_path: Path) -> None:
    root = tmp_path / "study"
    _write_call(root)

    result = OfflineReplayEngine(
        ReplayConfig(study_root=root, offline_required=True, start_from="worker_result")
    ).run()

    record = result["results"][0]
    assert record["replay_starting_point"] == "worker_result"
    assert record["replay_classification"] == "worker_result_replayed"
    assert record["provider_calls"] == 0
