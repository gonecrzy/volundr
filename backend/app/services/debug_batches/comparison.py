from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.debug_batch import DebugBatch, DebugBatchMembership
from app.services.debug_batches.reports import DebugBatchReportService


IDENTITY_FIELDS = (
    "git_head",
    "migration_head",
    "provider",
    "configured_default_model",
    "stage_model_policy_json",
    "prompt_versions_json",
    "configuration_hash",
    "backend_build_identity",
    "frontend_build_identity",
    "worker_build_identity",
)


class DebugBatchComparisonService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir

    def compare(self, candidate_batch_id: str) -> dict[str, Any]:
        candidate = self.db.get(DebugBatch, candidate_batch_id)
        if candidate is None:
            raise LookupError("debug batch not found")
        if candidate.state != "frozen":
            raise ValueError("comparison requires a frozen candidate batch")
        if not candidate.baseline_batch_id:
            raise ValueError("candidate batch has no frozen baseline")
        baseline = self.db.get(DebugBatch, candidate.baseline_batch_id)
        if baseline is None or baseline.state != "frozen":
            raise ValueError("comparison requires a frozen baseline batch")

        mismatches: dict[str, dict[str, Any]] = {}
        for field in IDENTITY_FIELDS:
            baseline_value = getattr(baseline, field)
            candidate_value = getattr(candidate, field)
            if field.endswith("_json"):
                baseline_value = json.loads(baseline_value)
                candidate_value = json.loads(candidate_value)
            if baseline_value != candidate_value:
                mismatches[field.removesuffix("_json")] = {
                    "baseline": baseline_value,
                    "candidate": candidate_value,
                }
        status = "controlled" if not mismatches else "uncontrolled"
        project_comparisons = self._project_comparisons(baseline, candidate)
        result = {
            "batch_id": candidate.id,
            "baseline_batch_id": baseline.id,
            "status": status,
            "identity_match": not mismatches,
            "mismatches": mismatches,
            "project_comparisons": project_comparisons,
        }
        comparison_path = self.data_dir / "debug-sessions" / candidate.id / "comparison" / "comparison.json"
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison_path.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        candidate.comparison_status = status
        self.db.commit()
        return result

    def _project_comparisons(self, baseline: DebugBatch, candidate: DebugBatch) -> list[dict[str, Any]]:
        baseline_members = list(
            self.db.scalars(
                select(DebugBatchMembership)
                .where(DebugBatchMembership.batch_id == baseline.id)
                .order_by(DebugBatchMembership.position.asc())
            )
        )
        candidate_members = list(
            self.db.scalars(
                select(DebugBatchMembership)
                .where(DebugBatchMembership.batch_id == candidate.id)
                .order_by(DebugBatchMembership.position.asc())
            )
        )
        result: list[dict[str, Any]] = []
        for position in range(max(len(baseline_members), len(candidate_members))):
            left = baseline_members[position] if position < len(baseline_members) else None
            right = candidate_members[position] if position < len(candidate_members) else None
            result.append(
                {
                    "position": position,
                    "baseline_project_id": left.project_id if left else None,
                    "candidate_project_id": right.project_id if right else None,
                    "membership_match": left is not None and right is not None,
                }
            )
        return result
