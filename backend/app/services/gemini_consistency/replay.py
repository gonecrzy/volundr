"""Provider-free replay of captured Gemini response lifecycles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.workflow.provider_response import analyze_provider_response
from app.services.workflow.redaction import RedactionService


REPLAY_START_POINTS = {
    "raw_provider_response",
    "parsed_response",
    "normalized_response",
    "assembled_source",
    "worker_result",
}


@dataclass(frozen=True)
class ReplayConfig:
    study_root: Path
    start_from: str = "raw_provider_response"
    stage: str | None = None
    case_id: str | None = None
    offline_required: bool = False
    output_path: Path | None = None


def _changed_fields(left: Any, right: Any, prefix: str = "") -> list[str]:
    if type(left) is not type(right):
        return [prefix or "$"]
    if isinstance(left, dict):
        keys = sorted(set(left) | set(right))
        changes: list[str] = []
        for key in keys:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in left or key not in right:
                changes.append(path)
            else:
                changes.extend(_changed_fields(left[key], right[key], path))
        return changes
    if isinstance(left, list):
        changes: list[str] = []
        for index in range(max(len(left), len(right))):
            path = f"{prefix}[{index}]"
            if index >= len(left) or index >= len(right):
                changes.append(path)
            else:
                changes.extend(_changed_fields(left[index], right[index], path))
        return changes
    return [] if left == right else [prefix or "$"]


def _classification(original: str, replay: str, original_accepted: bool, replay_accepted: bool) -> str:
    if original == replay and original_accepted == replay_accepted:
        return "unchanged"
    if not original_accepted and replay_accepted:
        return "correctly_normalized" if "normal" in replay or "valid" in replay else "correctly_repaired"
    if original_accepted and not replay_accepted:
        return "new_regression"
    return "evidence_insufficient"


class OfflineReplayEngine:
    def __init__(self, config: ReplayConfig) -> None:
        if config.start_from not in REPLAY_START_POINTS:
            raise ValueError(f"unsupported replay start point: {config.start_from}")
        if config.offline_required is not True:
            raise ValueError("offline replay requires --offline-required")
        self.config = config

    def _records(self) -> list[Path]:
        records = sorted(self.config.study_root.rglob("provider-calls/*.json"))
        result: list[Path] = []
        for path in records:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if self.config.case_id and document.get("case_id") != self.config.case_id:
                continue
            if self.config.stage and document.get("stage") != self.config.stage:
                continue
            result.append(path)
        return result

    def _replay_record(self, path: Path) -> dict[str, Any]:
        live = json.loads(path.read_text(encoding="utf-8"))
        processing = live.get("processing") if isinstance(live.get("processing"), dict) else {}
        response = live.get("response") if isinstance(live.get("response"), dict) else {}
        original_classification = str(processing.get("parse_classification") or "unknown")
        original_accepted = bool(processing.get("accepted"))
        if self.config.start_from == "raw_provider_response":
            analysis = analyze_provider_response(response.get("raw_text"), stage=str(live.get("stage") or "provider"))
            replay_classification = analysis.classification.value
            replay_accepted = analysis.final is not None
            replay_value: Any = analysis.normalized
        elif self.config.start_from == "parsed_response":
            parsed = processing.get("parsed_response") or live.get("parsed_response")
            replay_value = parsed
            replay_classification = "parsed_response_replayed"
            replay_accepted = parsed is not None
        elif self.config.start_from == "normalized_response":
            replay_value = processing.get("normalized_response") or live.get("normalized_response")
            replay_classification = "normalized_response_replayed"
            replay_accepted = replay_value is not None
        elif self.config.start_from == "assembled_source":
            replay_value = live.get("assembled_source")
            replay_classification = "assembled_source_replayed"
            replay_accepted = replay_value is not None
        else:
            replay_value = live.get("worker_result") or live.get("downstream", {}).get("worker_result")
            replay_classification = "worker_result_replayed"
            replay_accepted = replay_value is not None
        original_value = processing.get("normalized_response")
        return {
            "source_live_record": live.get("provider_call_id") or path.stem,
            "source_live_path": str(path.relative_to(self.config.study_root)),
            "replay_starting_point": self.config.start_from,
            "original_code_configuration_identity": live.get("configuration_hash"),
            "replay_code_configuration_identity": "offline-replay-v1",
            "original_classification": original_classification,
            "replay_classification": replay_classification,
            "original_downstream_outcome": live.get("downstream"),
            "replay_downstream_outcome": {"classification": replay_classification},
            "changed_fields": _changed_fields(original_value, replay_value),
            "unchanged_fields": [] if original_value is None else ["processing.raw_response"],
            "regression_improvement": _classification(original_classification, replay_classification, original_accepted, replay_accepted),
            "provider_calls": 0,
        }

    def run(self) -> dict[str, Any]:
        # There is deliberately no provider import or construction in this path.
        results = [self._replay_record(path) for path in self._records()]
        output = {
            "fixture_version": "gemini-replay-result-v1",
            "study_root": str(self.config.study_root),
            "offline_required": True,
            "provider_calls": 0,
            "replayed_count": len(results),
            "start_from": self.config.start_from,
            "results": results,
        }
        output_path = self.config.output_path or self.config.study_root / "cleanup" / "replay-results" / f"{self.config.start_from}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        redactor = RedactionService()
        safe, _ = redactor.redact_evidence_value(output, data_root=self.config.study_root, evidence_root=self.config.study_root)
        redactor.assert_json_redacted(safe)
        output_path.write_text(json.dumps(safe, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return output
