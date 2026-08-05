from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from app.services.gemini_integration.corpus import IntegrationProject, corpus_hash
from app.services.gemini_integration.profile import GeminiFlashLiteContractV1
from app.services.workflow.redaction import RedactionService


REQUIRED_REPORTS = (
    "study-preregistration.json",
    "repository-snapshot.json",
    "provider-profile-v1.json",
    "adapter-contracts.json",
    "frozen-project-corpus.json",
    "project-outcomes.json",
    "issue-register.json",
    "issue-causal-graph.json",
    "counterfactual-replays.json",
    "differential-replays.json",
    "ownership-summary.json",
    "unresolved-unknowns.json",
    "next-action-ranking.json",
    "integration-decision.json",
    "rate-limit-report.json",
    "retry-report.json",
    "all-integration-loop-evidence.json",
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


class IntegrationReportWriter:
    def __init__(self, root: Path, repository_root: Path) -> None:
        self.root = Path(root)
        self.repository_root = Path(repository_root).resolve()
        self.reports_root = self.root / "reports"
        self.redactor = RedactionService()

    def _write(self, name: str, value: Any) -> None:
        path = self.reports_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_json_value(value), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    def prepare(self, profile: GeminiFlashLiteContractV1, corpus: Iterable[IntegrationProject]) -> dict[str, Any]:
        for directory in ("captures", "projects", "replays", "issues", "counterfactuals", "reports"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        corpus = tuple(corpus)
        snapshot = self._repository_snapshot()
        self._write("repository-snapshot.json", snapshot)
        self._write("provider-profile-v1.json", profile.as_dict())
        self._write("adapter-contracts.json", {
            "schema_version": "volundr-provider-contract-integration-v1",
            "stages": {
                "requirements": "GeminiRequirementsContractAdapter",
                "plan": "GeminiPlanContractAdapter",
                "geometry": "GeminiGeometryContractAdapter",
            },
            "normalization_policy": "deterministic-only",
            "repair_prerequisite": False,
        })
        self._write("frozen-project-corpus.json", {"corpus_hash": corpus_hash(corpus), "projects": corpus})
        self._write("study-preregistration.json", {
            "schema_version": "volundr-provider-contract-integration-v1",
            "study_id": "gemini-provider-contract-integration-01",
            "profile_id": profile.profile_id,
            "projects": corpus,
            "provider_call_cap": 50,
            "worker_call_cap": 15,
            "retry_policy": {
                "max_attempts_per_logical_operation": 2,
                "429_wait_seconds_minimum": 30,
                "transport_wait_seconds_minimum": 10,
                "no_third_attempt": True,
            },
            "rate_limit": {"default_requests_per_minute": 12, "hard_max_requests_per_rolling_60_seconds": 15, "minimum_gap_seconds": 5, "concurrency": 1},
            "issue_taxonomy": ["root_cause", "contributing_factor", "consequence", "latent_independent_defect"],
            "stopping_rules": ["stop normal execution at unsafe blockers", "continue forensic analysis through preserved evidence"],
            "final_decision_options": ["integration_foundation_ready", "integration_foundation_requires_narrow_fix", "provider_contract_requires_revision", "insufficient_evidence"],
            "provider_calls": 0,
            "worker_calls": 0,
        })
        return {"provider_calls": 0, "worker_calls": 0, "snapshot": snapshot}

    def write_final(
        self,
        *,
        profile: GeminiFlashLiteContractV1,
        projects: Iterable[IntegrationProject],
        project_outcomes: list[dict[str, Any]],
        provider_attempts: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        causal_graph: dict[str, Any] | None = None,
        counterfactuals: list[dict[str, Any]] | None = None,
        differential_replays: list[dict[str, Any]] | None = None,
        ownership_summary: dict[str, Any] | None = None,
        priority_ranking: list[dict[str, Any]] | None = None,
        next_action: dict[str, Any] | None = None,
        rate_limit: dict[str, Any] | None = None,
        retry_summary: dict[str, Any] | None = None,
        decision: str = "insufficient_evidence",
    ) -> None:
        projects = tuple(projects)
        self._write("frozen-project-corpus.json", {"corpus_hash": corpus_hash(projects), "projects": projects})
        self._write("project-outcomes.json", project_outcomes)
        self._write("issue-register.json", issues)
        self._write("issue-causal-graph.json", causal_graph or {"nodes": [], "edges": []})
        self._write("counterfactual-replays.json", counterfactuals or [])
        self._write("differential-replays.json", differential_replays or [])
        self._write("ownership-summary.json", ownership_summary or {})
        self._write("unresolved-unknowns.json", [])
        self._write("next-action-ranking.json", priority_ranking or [])
        self._write("integration-decision.json", {"decision": decision, "production_default_changed": False})
        self._write("rate-limit-report.json", rate_limit or {})
        self._write("retry-report.json", retry_summary or {})
        safe_attempts = [self.redactor.redact_mapping(_json_value(item), artifact_type="integration_evidence") for item in provider_attempts]
        self._write("all-integration-loop-evidence.json", {
            "schema_version": "volundr-provider-contract-integration-v1",
            "study": {"study_id": "gemini-provider-contract-integration-01"},
            "repository": json.loads((self.reports_root / "repository-snapshot.json").read_text(encoding="utf-8")) if (self.reports_root / "repository-snapshot.json").is_file() else {},
            "provider_profile": profile,
            "projects": projects,
            "provider_attempts": safe_attempts,
            "worker_jobs": [item.get("worker_jobs", []) for item in project_outcomes],
            "project_outcomes": project_outcomes,
            "issues": issues,
            "causal_graph": causal_graph or {"nodes": [], "edges": []},
            "counterfactuals": counterfactuals or [],
            "differential_replays": differential_replays or [],
            "ownership_summary": ownership_summary or {},
            "priority_ranking": priority_ranking or [],
            "next_action": next_action or {},
            "rate_limit": rate_limit or {},
            "retry_summary": retry_summary or {},
            "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"},
        })

    def _repository_snapshot(self) -> dict[str, Any]:
        def git(*args: str) -> str | None:
            try:
                return subprocess.check_output(["git", "-C", str(self.repository_root), *args], text=True, stderr=subprocess.DEVNULL).strip()
            except (OSError, subprocess.CalledProcessError):
                return None

        historical = []
        for root in (
            "data/debug-sessions/gemini-flash-lite-study/gemini-flash-lite-study-01",
            "data/debug-sessions/gemini-profile-ablation/gemini-profile-ablation-01",
            "data/debug-sessions/gemini-system-boundary-methods/gemini-system-boundary-methods-01",
            "data/debug-sessions/gemini-provider-contract-foundation/gemini-provider-contract-foundation-01",
        ):
            path = self.repository_root / root
            if not path.is_dir():
                continue
            for file in sorted(path.rglob("*.json")):
                historical.append({"path": str(file.relative_to(self.repository_root)), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
        return {
            "head": git("rev-parse", "HEAD"),
            "branch": git("branch", "--show-current"),
            "origin_main": git("rev-parse", "origin/main"),
            "divergence": git("rev-list", "--left-right", "--count", "HEAD...origin/main"),
            "worktree": git("status", "--short"),
            "migration_head": None,
            "historical_evidence_hashes": historical,
        }


__all__ = ["IntegrationReportWriter", "REQUIRED_REPORTS"]

