"""Execution adapters for recovery decisions.

Recovery policy remains pure in ``recovery.py``.  This module is the
orchestrator-owned bridge to existing verifier and worker retry authorities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from app.services.executable_cadquery.recovery import RecoveryDecision
from app.services.executable_cadquery.semantic import evaluate_executable_cadquery_semantics_for_outputs
from app.services.validated_cadquery_security import safe_relative_artifact_path


@dataclass(frozen=True)
class RecoveryExecutionResult:
    action: str
    executed: bool
    provider_calls: int = 0
    worker_calls: int = 0
    semantic_result: dict[str, Any] = field(default_factory=dict)
    diagnostic: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "executed": self.executed,
            "provider_calls": self.provider_calls,
            "worker_calls": self.worker_calls,
            "semantic_result": self.semantic_result,
            "diagnostic": self.diagnostic,
        }


class RecoveryActionExecutor:
    """Invoke only existing subsystem operations for non-provider actions."""

    def __init__(self, *, data_dir: Path):
        self.data_dir = data_dir

    async def execute(
        self,
        decision: RecoveryDecision,
        *,
        revision: Any | None,
        contract: Mapping[str, Any],
        project_service: Any | None = None,
    ) -> RecoveryExecutionResult:
        action = decision.recommended_action
        if action in {"application_owned_fix", "rerun_verifier"}:
            semantic = self._rerun_verifier(revision, contract)
            return RecoveryExecutionResult(
                action=action,
                executed=True,
                semantic_result=semantic,
                diagnostic=None,
            )
        if action == "rerun_export":
            if project_service is None or revision is None:
                return RecoveryExecutionResult(
                    action=action,
                    executed=False,
                    diagnostic="existing worker retry service is unavailable",
                )
            worker_calls = 0
            for output in getattr(revision, "outputs", ()):
                if getattr(output, "execution_state", None) != "failed":
                    continue
                await project_service.retry_revision_output(output.id)
                worker_calls += 1
            return RecoveryExecutionResult(
                action=action,
                executed=worker_calls > 0,
                worker_calls=worker_calls,
                diagnostic=None if worker_calls else "no failed output is eligible for existing worker retry",
            )
        if action == "require_review":
            return RecoveryExecutionResult(action=action, executed=True)
        return RecoveryExecutionResult(
            action=action,
            executed=False,
            diagnostic="recovery action has no registered execution adapter",
        )

    def _rerun_verifier(self, revision: Any | None, contract: Mapping[str, Any]) -> dict[str, Any]:
        if revision is None:
            return {
                "status": "unverifiable",
                "passed": [],
                "failed": [],
                "unverifiable": ["revision"],
                "findings": [],
            }
        stl_paths: dict[str, Path] = {}
        for output in getattr(revision, "outputs", ()):
            raw_path = getattr(output, "stl_path", None)
            if not raw_path:
                continue
            stl_paths[str(output.output_id)] = safe_relative_artifact_path(self.data_dir, raw_path)
        return evaluate_executable_cadquery_semantics_for_outputs(
            stl_paths=stl_paths,
            design_contract=contract,
        )

