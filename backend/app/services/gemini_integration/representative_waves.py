from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.services.gemini_integration.corpus import IntegrationProject
from app.services.gemini_integration.forensics import CausalGraph, IssueRecord
from app.services.gemini_integration.profile import INTEGRATION_PROFILE_ID
from app.services.workflow.redaction import RedactionService


WAVE_SCHEMA_VERSION = "volundr-representative-wave-v1"
WAVE_PROVENANCE_MARKER = "volundr-representative-workflow-wave"
REQUIRED_WAVE_DIRECTORIES = (
    "captures",
    "projects",
    "provider-attempts",
    "worker-jobs",
    "artifacts",
    "replays",
    "counterfactuals",
    "issues",
    "reports",
)
REQUIRED_WAVE_REPORTS = (
    "wave-preregistration.json",
    "repository-snapshot.json",
    "frozen-project-corpus.json",
    "project-diversity-matrix.json",
    "provider-attempts.json",
    "worker-jobs.json",
    "project-outcomes.json",
    "issue-register.json",
    "issue-causal-graph.json",
    "cross-project-issue-clusters.json",
    "counterfactual-replays.json",
    "differential-replays.json",
    "ownership-summary.json",
    "unresolved-unknowns.json",
    "issue-priority-ranking.json",
    "corrections-applied.json",
    "regression-replay.json",
    "live-rerun-decision.json",
    "wave-decision.json",
    "next-wave-recommendation.json",
    "rate-limit-report.json",
    "retry-report.json",
    "combined-wave-evidence.json",
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "as_dict"):
        return value.as_dict()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class WaveManifest:
    schema_version: str
    wave_id: str
    provider_profile: str
    projects: tuple[IntegrationProject, ...]
    execution_policy: dict[str, Any] = field(default_factory=dict)
    diagnostic_policy: dict[str, Any] = field(default_factory=dict)
    call_caps: dict[str, Any] = field(default_factory=dict)
    stopping_rules: dict[str, Any] = field(default_factory=dict)
    coverage_matrix: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WaveManifest":
        if not isinstance(payload, dict):
            raise ValueError("wave manifest must be a JSON object")
        if payload.get("schema_version") != WAVE_SCHEMA_VERSION:
            raise ValueError(f"wave manifest schema_version must be {WAVE_SCHEMA_VERSION!r}")
        wave_id = str(payload.get("wave_id") or "").strip()
        if not wave_id:
            raise ValueError("wave manifest requires a wave_id")
        provider_profile = str(payload.get("provider_profile") or "").strip()
        if provider_profile != INTEGRATION_PROFILE_ID:
            raise ValueError(f"wave manifest provider_profile must be {INTEGRATION_PROFILE_ID!r}")
        raw_projects = payload.get("projects")
        if not isinstance(raw_projects, list) or not raw_projects:
            raise ValueError("wave manifest requires a non-empty projects list")

        projects: list[IntegrationProject] = []
        seen: set[str] = set()
        project_pattern = re.compile(rf"^{re.escape(wave_id)}-project-\d{{2}}$")
        for index, raw_project in enumerate(raw_projects, start=1):
            if not isinstance(raw_project, dict):
                raise ValueError(f"project {index} must be an object")
            project_id = str(raw_project.get("project_id") or "").strip()
            if not project_id:
                raise ValueError(f"project {index} requires a project_id")
            if project_id in seen:
                raise ValueError("project_id values must be unique")
            if not project_pattern.match(project_id):
                raise ValueError(f"project_id {project_id!r} must be stable under wave_id {wave_id!r}")
            seen.add(project_id)
            missing = [key for key in ("title", "user_request", "frozen_facts") if key not in raw_project]
            if missing:
                raise ValueError(f"project {project_id} is missing required fields: {', '.join(missing)}")
            projects.append(
                IntegrationProject(
                    project_id=project_id,
                    title=str(raw_project["title"]),
                    user_request=str(raw_project["user_request"]),
                    frozen_facts=dict(raw_project.get("frozen_facts") or {}),
                    clarification_answers=tuple(raw_project.get("clarification_answers") or ()),
                    fit_critical_missing=tuple(str(item) for item in raw_project.get("fit_critical_missing") or ()),
                    expected_output_count=int(raw_project.get("expected_output_count", 1)),
                    expected_solid_counts=dict(raw_project.get("expected_solid_counts") or {}),
                    semantic_obligations=tuple(str(item) for item in raw_project.get("semantic_obligations") or ()),
                    unsafe_claims=tuple(str(item) for item in raw_project.get("unsafe_claims") or IntegrationProject.__dataclass_fields__["unsafe_claims"].default),
                    revision_of=raw_project.get("revision_of"),
                    requirement_delta=tuple(raw_project.get("requirement_delta") or ()),
                    protected_facts=tuple(str(item) for item in raw_project.get("protected_facts") or ()),
                )
            )
        return cls(
            schema_version=WAVE_SCHEMA_VERSION,
            wave_id=wave_id,
            provider_profile=provider_profile,
            projects=tuple(projects),
            execution_policy=dict(payload.get("execution_policy") or {}),
            diagnostic_policy=dict(payload.get("diagnostic_policy") or {}),
            call_caps=dict(payload.get("call_caps") or {}),
            stopping_rules=dict(payload.get("stopping_rules") or {}),
            coverage_matrix=dict(payload.get("coverage_matrix") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "wave_id": self.wave_id,
            "provider_profile": self.provider_profile,
            "projects": [_json_value(project) for project in self.projects],
            "execution_policy": _json_value(self.execution_policy),
            "diagnostic_policy": _json_value(self.diagnostic_policy),
            "call_caps": _json_value(self.call_caps),
            "stopping_rules": _json_value(self.stopping_rules),
            "coverage_matrix": _json_value(self.coverage_matrix),
        }

    def manifest_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def load_wave_manifest(path: Path) -> WaveManifest:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read wave manifest {path}: {exc}") from exc
    return WaveManifest.from_dict(payload)


@dataclass
class WaveBaselineState:
    completed_project_ids: tuple[str, ...] = ()
    analyzed: bool = False
    issues_registered: bool = False
    clusters_complete: bool = False
    priority_complete: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "completed_project_ids": list(self.completed_project_ids),
            "analyzed": self.analyzed,
            "issues_registered": self.issues_registered,
            "clusters_complete": self.clusters_complete,
            "priority_complete": self.priority_complete,
        }


class WaveRunner:
    def __init__(self, manifest: WaveManifest, root: Path) -> None:
        self.manifest = manifest
        self.root = Path(root)
        self.state = WaveBaselineState()

    def authorize_corrections(self) -> dict[str, Any]:
        expected = {project.project_id for project in self.manifest.projects}
        completed = set(self.state.completed_project_ids)
        missing = sorted(expected - completed)
        if missing or not self.state.analyzed or not self.state.issues_registered or not self.state.clusters_complete or not self.state.priority_complete:
            raise RuntimeError(
                "corrections require complete baseline execution and analysis; "
                f"missing_projects={missing} analyzed={self.state.analyzed} "
                f"issues_registered={self.state.issues_registered} "
                f"clusters_complete={self.state.clusters_complete} priority_complete={self.state.priority_complete}"
            )
        return {"authorized": True, "wave_id": self.manifest.wave_id, "project_ids": sorted(expected)}

    def record_baseline_project(self, project_id: str) -> None:
        expected = {project.project_id for project in self.manifest.projects}
        if project_id not in expected:
            raise ValueError(f"project {project_id!r} is not registered in wave {self.manifest.wave_id!r}")
        completed = set(self.state.completed_project_ids)
        completed.add(project_id)
        self.state.completed_project_ids = tuple(
            project.project_id for project in self.manifest.projects if project.project_id in completed
        )

    def save_state(self) -> None:
        _write_report(self.root / "reports/wave-state.json", {
            "schema_version": WAVE_SCHEMA_VERSION,
            "wave_id": self.manifest.wave_id,
            "manifest_hash": self.manifest.manifest_hash(),
            "baseline": self.state.as_dict(),
        })

    def mark_analysis_complete(self, *, issues_registered: bool, clusters_complete: bool, priority_complete: bool) -> None:
        expected = {project.project_id for project in self.manifest.projects}
        if set(self.state.completed_project_ids) != expected:
            raise RuntimeError("cannot analyze a wave before every preregistered baseline project has completed")
        self.state.analyzed = True
        self.state.issues_registered = issues_registered
        self.state.clusters_complete = clusters_complete
        self.state.priority_complete = priority_complete
        self.save_state()


def load_wave_state(runner: WaveRunner) -> WaveBaselineState:
    path = runner.root / "reports/wave-state.json"
    if not path.is_file():
        return runner.state
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to read wave state {path}: {exc}") from exc
    if payload.get("wave_id") != runner.manifest.wave_id or payload.get("manifest_hash") != runner.manifest.manifest_hash():
        raise ValueError("wave state does not match the manifest")
    baseline = payload.get("baseline") or {}
    runner.state = WaveBaselineState(
        completed_project_ids=tuple(str(item) for item in baseline.get("completed_project_ids") or ()),
        analyzed=bool(baseline.get("analyzed")),
        issues_registered=bool(baseline.get("issues_registered")),
        clusters_complete=bool(baseline.get("clusters_complete")),
        priority_complete=bool(baseline.get("priority_complete")),
    )
    return runner.state


class WaveEvidenceStore:
    """Immutable, redacted evidence storage for a representative wave."""

    def __init__(self, root: Path, *, wave_id: str) -> None:
        self.root = Path(root)
        self.wave_id = wave_id
        self.redactor = RedactionService()
        for directory in REQUIRED_WAVE_DIRECTORIES:
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(identity: str) -> str:
        return "".join(character if character.isalnum() or character in "._-" else "_" for character in identity)

    def _record(self, category: str, identity: str, value: dict[str, Any]) -> dict[str, Any]:
        if not identity:
            raise ValueError(f"{category} evidence requires an identity")
        path = self.root / category / f"{self._safe(identity)}.json"
        redacted = self.redactor.redact_mapping({**value, "wave_id": self.wave_id}, artifact_type="integration_evidence")
        if category == "provider-attempts":
            redacted = self._redact_provider_secrets(redacted)
        encoded = json.dumps(redacted, indent=2, sort_keys=True, default=str) + "\n"
        if path.is_file():
            if path.read_text(encoding="utf-8") != encoded:
                raise RuntimeError(f"immutable wave evidence already exists with different content: {path}")
            return json.loads(encoded)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded, encoding="utf-8")
        return redacted

    @classmethod
    def _redact_provider_secrets(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if str(key).lower() in {"key", "api_key", "credential_value"} else cls._redact_provider_secrets(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact_provider_secrets(item) for item in value]
        return value

    def record_provider_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        return self._record("provider-attempts", str(attempt.get("attempt_id") or ""), attempt)

    def record_boundary(self, boundary: dict[str, Any]) -> dict[str, Any]:
        identity = str(boundary.get("boundary_id") or boundary.get("operation_id") or "")
        return self._record("captures", identity, boundary)

    def record_worker_job(self, job: dict[str, Any]) -> dict[str, Any]:
        return self._record("worker-jobs", str(job.get("job_id") or job.get("worker_job_id") or ""), job)

    def record_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        identity = str(artifact.get("artifact_id") or artifact.get("output_id") or "")
        return self._record("artifacts", identity, artifact)

    def provider_attempts(self) -> list[dict[str, Any]]:
        return self._read_category("provider-attempts")

    def boundaries(self) -> list[dict[str, Any]]:
        return self._read_category("captures")

    def worker_jobs(self) -> list[dict[str, Any]]:
        return self._read_category("worker-jobs")

    def artifacts(self) -> list[dict[str, Any]]:
        return self._read_category("artifacts")

    def _read_category(self, category: str) -> list[dict[str, Any]]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted((self.root / category).glob("*.json"))]


def _write_report(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_value(value), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_wave_report(root: Path, name: str, value: Any) -> None:
    if name not in REQUIRED_WAVE_REPORTS and name != "wave-state.json":
        raise ValueError(f"unknown representative-wave report: {name}")
    _write_report(Path(root) / "reports" / name, value)


def read_wave_report(root: Path, name: str, fallback: Any) -> Any:
    path = Path(root) / "reports" / name
    if not path.is_file():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid representative-wave report {path}: {exc}") from exc


def _finding_records(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        findings = value.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if isinstance(finding, dict):
                    yield finding
        for child in value.values():
            yield from _finding_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _finding_records(child)


_OWNER_BY_BOUNDARY = {
    "provider_requirements": "provider_requirements",
    "provider_plan": "provider_plan",
    "provider_geometry": "provider_geometry",
    "requirements_adapter": "requirements_adapter",
    "plan_adapter": "plan_adapter",
    "geometry_adapter": "geometry_adapter",
    "static_validator": "static_validator",
    "static_validation": "static_validator",
    "worker": "worker_runtime",
    "worker_runtime": "worker_runtime",
    "artifacts": "artifact_export",
    "topology": "topology",
    "verification": "verification",
    "candidate": "candidate_decision",
    "transport": "transport",
}


def analyze_wave_issues(
    manifest: WaveManifest,
    outcomes: Iterable[dict[str, Any]],
    evidence_store: WaveEvidenceStore,
) -> dict[str, Any]:
    """Create a multi-issue register from preserved boundary findings.

    This intentionally reports every captured finding independently; the
    earliest blocker is only one record and never replaces later findings.
    """

    outcome_by_project = {str(item.get("project_id")): item for item in outcomes}
    boundaries_by_project: dict[str, list[dict[str, Any]]] = {}
    for boundary in evidence_store.boundaries():
        boundaries_by_project.setdefault(str(boundary.get("project_id") or ""), []).append(boundary)

    issues: list[IssueRecord] = []
    causal = CausalGraph()
    for project in manifest.projects:
        project_id = project.project_id
        outcome = outcome_by_project.get(project_id) or {}
        project_boundaries = boundaries_by_project.get(project_id, [])
        blocker = str(outcome.get("earliest_blocker") or "")
        project_issue_ids: list[str] = []
        index = 1

        if blocker:
            matching = [item for item in project_boundaries if str(item.get("boundary") or "") in {blocker, f"provider_{blocker}"}]
            evidence_paths = tuple(str(item.get("boundary_id")) for item in matching)
            issue = IssueRecord(
                issue_id=f"{project_id}-issue-{index:02d}",
                project_id=project_id,
                stage=blocker,
                primary_owner=_OWNER_BY_BOUNDARY.get(blocker, "unknown"),
                secondary_factors=(),
                classification="root_cause",
                symptom=f"workflow stopped at {blocker}",
                incorrect_behavior="the boundary did not produce an authoritative valid result",
                expected_behavior="the boundary should produce an authoritative valid result or an explicit safe clarification",
                evidence_paths=evidence_paths,
                input_hashes=tuple(str(item.get("input_hash")) for item in matching if item.get("input_hash")),
                output_hashes=tuple(str(item.get("output_hash")) for item in matching if item.get("output_hash")),
                confidence="possible",
                recommended_fix_boundary=_OWNER_BY_BOUNDARY.get(blocker, "unknown"),
                provider_call_required=_OWNER_BY_BOUNDARY.get(blocker, "unknown").startswith("provider_"),
            )
            issues.append(issue)
            project_issue_ids.append(issue.issue_id)
            index += 1

        seen_findings: set[tuple[str, str, str]] = set()
        for boundary in project_boundaries:
            boundary_name = str(boundary.get("boundary") or "unknown")
            for finding in _finding_records(boundary.get("output")):
                key = (boundary_name, str(finding.get("rule_id") or finding.get("message") or ""), str(finding.get("message") or ""))
                if key in seen_findings:
                    continue
                seen_findings.add(key)
                issue_id = f"{project_id}-issue-{index:02d}"
                issue = IssueRecord(
                    issue_id=issue_id,
                    project_id=project_id,
                    stage=boundary_name,
                    primary_owner=_OWNER_BY_BOUNDARY.get(boundary_name, "unknown"),
                    secondary_factors=(),
                    classification="root_cause" if not project_issue_ids else "latent_independent_defect",
                    symptom=str(finding.get("message") or finding.get("rule_id") or "captured validation finding"),
                    incorrect_behavior=str(finding.get("message") or "boundary finding was reported"),
                    expected_behavior="the boundary contract should be satisfied",
                    evidence_paths=(str(boundary.get("boundary_id")),),
                    input_hashes=(str(boundary.get("input_hash")),) if boundary.get("input_hash") else (),
                    output_hashes=(str(boundary.get("output_hash")),) if boundary.get("output_hash") else (),
                    confidence="confirmed" if finding.get("deterministic") is True else "possible",
                    recommended_fix_boundary=_OWNER_BY_BOUNDARY.get(boundary_name, "unknown"),
                    provider_call_required=_OWNER_BY_BOUNDARY.get(boundary_name, "unknown").startswith("provider_"),
                )
                issues.append(issue)
                project_issue_ids.append(issue_id)
                index += 1
        for left, right in zip(project_issue_ids, project_issue_ids[1:]):
            causal.add(left, right, "independent_of")

    return {"issues": [issue.as_dict() for issue in issues], "causal_graph": causal.as_dict()}


def cluster_wave_issues(issues: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for issue in issues:
        key = (
            str(issue.get("primary_owner") or "unknown"),
            str(issue.get("stage") or "unknown"),
            str(issue.get("recommended_fix_boundary") or "unknown"),
        )
        groups.setdefault(key, []).append(issue)
    clusters: list[dict[str, Any]] = []
    for index, (key, members) in enumerate(sorted(groups.items()), start=1):
        owner, stage, boundary = key
        clusters.append({
            "cluster_id": f"cluster-{index:02d}",
            "primary_owner": owner,
            "stage": stage,
            "recommended_fix_boundary": boundary,
            "issue_ids": sorted(str(item.get("issue_id")) for item in members),
            "project_ids": sorted({str(item.get("project_id")) for item in members}),
            "frequency": len(members),
            "classification_counts": {
                classification: sum(1 for item in members if item.get("classification") == classification)
                for classification in sorted({str(item.get("classification")) for item in members})
            },
        })
    return clusters


def rank_wave_issues(issues: Iterable[dict[str, Any]], clusters: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    issues_by_id = {str(issue.get("issue_id")): issue for issue in issues}
    ranked: list[dict[str, Any]] = []
    severity_by_classification = {
        "root_cause": 5.0,
        "latent_independent_defect": 4.0,
        "contributing_factor": 3.0,
        "consequence": 2.0,
    }
    for cluster in clusters:
        member_ids = [str(item) for item in cluster.get("issue_ids") or ()]
        members = [issues_by_id[item] for item in member_ids if item in issues_by_id]
        if not members:
            continue
        confidence = max({
            "confirmed": 1.0,
            "high_confidence": 0.8,
            "probable": 0.6,
            "possible": 0.35,
            "unknown": 0.1,
        }.get(str(item.get("confidence")), 0.1) for item in members)
        factors = {
            "frequency": float(cluster.get("frequency", len(members))),
            "severity": max(severity_by_classification.get(str(item.get("classification")), 1.0) for item in members),
            "confidence": confidence,
            "downstream_impact": float(max(1, len(member_ids))),
            "generalization_value": float(max(1, len(cluster.get("project_ids") or []))),
            "estimated_correction_cost": 1.0,
        }
        factors["raw_priority_numerator"] = (
            factors["frequency"]
            * factors["severity"]
            * factors["confidence"]
            * factors["downstream_impact"]
            * factors["generalization_value"]
        )
        score = factors["raw_priority_numerator"] / factors["estimated_correction_cost"]
        ranked.append({
            "cluster_id": cluster["cluster_id"],
            "issue_ids": member_ids,
            "raw_factors": factors,
            "priority_score": round(score, 6),
        })
    return sorted(ranked, key=lambda item: (-item["priority_score"], item["cluster_id"]))


def build_wave_bundle(
    manifest: WaveManifest,
    evidence_store: WaveEvidenceStore,
    *,
    outcomes: Iterable[dict[str, Any]] = (),
    issues: Iterable[dict[str, Any]] = (),
    causal_graph: dict[str, Any] | None = None,
    counterfactuals: Any = None,
    differential_replays: Any = None,
    clusters: Any = None,
    ranking: Any = None,
    rate_limit: Any = None,
    retry_summary: Any = None,
) -> dict[str, Any]:
    return {
        "schema_version": WAVE_SCHEMA_VERSION,
        "wave_id": manifest.wave_id,
        "provider_profile": manifest.provider_profile,
        "manifest_hash": manifest.manifest_hash(),
        "projects": manifest.projects,
        "provider_attempts": evidence_store.provider_attempts(),
        "worker_jobs": evidence_store.worker_jobs(),
        "artifacts": evidence_store.artifacts(),
        "captures": evidence_store.boundaries(),
        "project_outcomes": list(outcomes),
        "issues": list(issues),
        "causal_graph": causal_graph or {"nodes": [], "edges": []},
        "cross_project_issue_clusters": clusters or [],
        "counterfactuals": counterfactuals or [],
        "differential_replays": differential_replays or [],
        "priority_ranking": ranking or [],
        "rate_limit": rate_limit or {},
        "retry_summary": retry_summary or {},
        "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"},
    }


def _write_once(path: Path, value: Any) -> None:
    encoded = json.dumps(_json_value(value), indent=2, sort_keys=True, default=str) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != encoded:
            raise RuntimeError(f"immutable wave evidence already exists with different content: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _repository_snapshot(repository_root: Path) -> dict[str, Any]:
    repository_root = Path(repository_root).resolve()

    def git(*args: str) -> str | None:
        try:
            return subprocess.check_output(["git", "-C", str(repository_root), *args], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    migration_head: str | None = None
    alembic = repository_root / "backend/.venv/bin/alembic"
    if alembic.is_file():
        try:
            migration_head = subprocess.check_output([str(alembic), "heads"], cwd=repository_root / "backend", text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            migration_head = None
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "origin_main": git("rev-parse", "origin/main"),
        "divergence": git("rev-list", "--left-right", "--count", "HEAD...origin/main"),
        "worktree": git("status", "--short"),
        "migration_head": migration_head,
    }


def _default_diversity_matrix(manifest: WaveManifest) -> dict[str, Any]:
    dimensions = (
        "clarification_behavior",
        "output_count",
        "new_design_or_revision",
        "layout_regularity",
        "additive_subtractive_operations",
        "fit_critical_geometry",
        "hollow_or_solid_geometry",
        "loft_sweep_revolve_capability",
        "output_identity",
        "topology_expectations",
        "requirement_verification",
    )
    return {
        "schema_version": WAVE_SCHEMA_VERSION,
        "wave_id": manifest.wave_id,
        "dimensions": list(dimensions),
        "projects": {
            project.project_id: {dimension: "preregistered" for dimension in dimensions}
            for project in manifest.projects
        },
        "coverage_matrix_source": "manifest.coverage_matrix" if manifest.coverage_matrix else "project_obligations",
        "coverage_matrix": manifest.coverage_matrix,
    }


def initialize_wave(root: Path, manifest: WaveManifest, *, repository_root: Path) -> dict[str, Any]:
    root = Path(root)
    for directory in REQUIRED_WAVE_DIRECTORIES:
        (root / directory).mkdir(parents=True, exist_ok=True)
    snapshot = _repository_snapshot(repository_root)
    preregistration = {
        "schema_version": WAVE_SCHEMA_VERSION,
        "wave_id": manifest.wave_id,
        "provider_profile": manifest.provider_profile,
        "manifest_hash": manifest.manifest_hash(),
        "projects": [project.project_id for project in manifest.projects],
        "execution_policy": manifest.execution_policy,
        "diagnostic_policy": manifest.diagnostic_policy,
        "call_caps": manifest.call_caps,
        "stopping_rules": manifest.stopping_rules,
        "baseline_before_corrections": bool(manifest.execution_policy.get("baseline_before_corrections", True)),
        "production_routing_changed": False,
        "deployed": False,
    }
    _write_once(root / "reports/wave-preregistration.json", preregistration)
    _write_once(root / "reports/repository-snapshot.json", snapshot)
    _write_once(root / "reports/frozen-project-corpus.json", {
        "schema_version": WAVE_SCHEMA_VERSION,
        "wave_id": manifest.wave_id,
        "manifest_hash": manifest.manifest_hash(),
        "projects": manifest.projects,
    })
    _write_once(root / "reports/project-diversity-matrix.json", _default_diversity_matrix(manifest))
    for project in manifest.projects:
        _write_once(root / "projects" / f"{project.project_id}.json", project)
    defaults = {
        "provider-attempts.json": [],
        "worker-jobs.json": [],
        "project-outcomes.json": [],
        "issue-register.json": [],
        "issue-causal-graph.json": {"nodes": [], "edges": []},
        "cross-project-issue-clusters.json": [],
        "counterfactual-replays.json": [],
        "differential-replays.json": [],
        "ownership-summary.json": {},
        "unresolved-unknowns.json": [],
        "issue-priority-ranking.json": [],
        "corrections-applied.json": [],
        "regression-replay.json": [],
        "live-rerun-decision.json": {},
        "wave-decision.json": {"decision": "insufficient_evidence"},
        "next-wave-recommendation.json": {},
        "rate-limit-report.json": {},
        "retry-report.json": {},
        "combined-wave-evidence.json": {
            "schema_version": WAVE_SCHEMA_VERSION,
            "wave_id": manifest.wave_id,
            "provider_attempts": [],
            "worker_jobs": [],
            "projects": manifest.projects,
            "redaction": {"credential_values_serialized": False, "credential_source": "GEMINI_API_KEY_2"},
        },
    }
    for name, value in defaults.items():
        report_path = root / "reports" / name
        if not report_path.is_file():
            _write_report(report_path, value)
    return {"wave_id": manifest.wave_id, "manifest_hash": manifest.manifest_hash(), "repository": snapshot}


__all__ = [
    "REQUIRED_WAVE_DIRECTORIES",
    "REQUIRED_WAVE_REPORTS",
    "WAVE_PROVENANCE_MARKER",
    "WAVE_SCHEMA_VERSION",
    "WaveBaselineState",
    "WaveEvidenceStore",
    "WaveManifest",
    "WaveRunner",
    "analyze_wave_issues",
    "build_wave_bundle",
    "cluster_wave_issues",
    "initialize_wave",
    "load_wave_state",
    "load_wave_manifest",
    "read_wave_report",
    "rank_wave_issues",
    "write_wave_report",
]
