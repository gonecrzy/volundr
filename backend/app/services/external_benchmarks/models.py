"""Validated, JSON-serializable contracts for external CAD benchmark data."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any


_PROJECT_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_PART_ID_RE = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")
_FILE_TYPE_VALUES = {"stl", "step", "brep"}
_PROVENANCE_FILE_TYPE_VALUES = {"3mf", "dwg", "f3d", "pdf", "stl", "step", "brep", "unknown"}
_SPLIT_VALUES = {"pilot", "development", "validation", "holdout"}
_STATUS_VALUES = {"placeholder", "imported", "ready", "retired"}
_RUN_MODE_VALUES = {"premise_only", "reference_specification"}


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string when supplied")
    return value.strip()


def _optional_hash(payload: dict[str, Any], key: str) -> str | None:
    value = _optional_string(payload, key)
    if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError(f"{key} must be a SHA-256 hex digest")
    return value.lower() if value is not None else None


@dataclass(frozen=True)
class ReferenceFileRecord:
    part_id: str
    relative_path: str
    file_type: str
    sha256: str
    original_filename: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ReferenceFileRecord":
        part_id = _required_string(payload, "part_id")
        if not _PART_ID_RE.fullmatch(part_id):
            raise ValueError("part_id must be a neutral lowercase identifier")
        file_type = _required_string(payload, "file_type").lower()
        if file_type not in _FILE_TYPE_VALUES:
            raise ValueError(f"unsupported reference file type: {file_type}")
        sha256 = _optional_hash(payload, "sha256")
        if sha256 is None:
            raise ValueError("reference file sha256 is required")
        return cls(
            part_id=part_id,
            relative_path=_required_string(payload, "relative_path"),
            file_type=file_type,
            sha256=sha256,
            original_filename=_required_string(payload, "original_filename"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProvenanceFileRecord:
    relative_path: str
    file_type: str
    sha256: str
    original_filename: str
    role: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProvenanceFileRecord":
        file_type = _required_string(payload, "file_type").lower()
        if file_type not in _PROVENANCE_FILE_TYPE_VALUES:
            raise ValueError(f"unsupported provenance file type: {file_type}")
        sha256 = _optional_hash(payload, "sha256")
        if sha256 is None:
            raise ValueError("provenance file sha256 is required")
        return cls(
            relative_path=_required_string(payload, "relative_path"),
            file_type=file_type,
            sha256=sha256,
            original_filename=_required_string(payload, "original_filename"),
            role=_required_string(payload, "role"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkProject:
    benchmark_id: str
    category: str
    benchmark_version: str = "1.0.0"
    source_site: str | None = None
    source_url: str | None = None
    creator: str | None = None
    source_title: str | None = None
    license: str | None = None
    acquired_at: str | None = None
    reference_files: tuple[ReferenceFileRecord, ...] = ()
    provenance_files: tuple[ProvenanceFileRecord, ...] = ()
    canonical_part_count: int | None = None
    reference_set_sha256: str | None = None
    reference_output_mapping: dict[str, str] = field(default_factory=dict)
    premise: str = ""
    reference_spec: dict[str, Any] = field(default_factory=dict)
    split_assignment: str = "pilot"
    status: str = "placeholder"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkProject":
        benchmark_id = _required_string(payload, "benchmark_id")
        if not _PROJECT_ID_RE.fullmatch(benchmark_id):
            raise ValueError("benchmark_id must be a neutral lowercase hyphenated identifier")
        category = _required_string(payload, "category")
        split_assignment = str(payload.get("split_assignment", "pilot"))
        if split_assignment not in _SPLIT_VALUES:
            raise ValueError(f"unsupported split_assignment: {split_assignment}")
        status = str(payload.get("status", "placeholder"))
        if status not in _STATUS_VALUES:
            raise ValueError(f"unsupported project status: {status}")
        premise = payload.get("premise", "")
        if not isinstance(premise, str):
            raise ValueError("premise must be a string")
        reference_spec = payload.get("reference_spec", {})
        if not isinstance(reference_spec, dict):
            raise ValueError("reference_spec must be an object")
        files = payload.get("reference_files", [])
        if not isinstance(files, list):
            raise ValueError("reference_files must be a list")
        provenance_files = payload.get("provenance_files", [])
        if not isinstance(provenance_files, list):
            raise ValueError("provenance_files must be a list")
        canonical_part_count = payload.get("canonical_part_count")
        if canonical_part_count is not None:
            canonical_part_count = int(canonical_part_count)
            if canonical_part_count < 0:
                raise ValueError("canonical_part_count cannot be negative")
        reference_output_mapping = payload.get("reference_output_mapping", {})
        if not isinstance(reference_output_mapping, dict) or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or not value.strip()
            for key, value in reference_output_mapping.items()
        ):
            raise ValueError("reference_output_mapping must map non-empty strings to non-empty strings")
        if len(set(reference_output_mapping.values())) != len(reference_output_mapping):
            raise ValueError("reference_output_mapping values must be unique")
        return cls(
            benchmark_id=benchmark_id,
            benchmark_version=str(payload.get("benchmark_version", "1.0.0")),
            category=category,
            source_site=_optional_string(payload, "source_site"),
            source_url=_optional_string(payload, "source_url"),
            creator=_optional_string(payload, "creator"),
            source_title=_optional_string(payload, "source_title"),
            license=_optional_string(payload, "license"),
            acquired_at=_optional_string(payload, "acquired_at"),
            reference_files=tuple(ReferenceFileRecord.from_dict(item) for item in files),
            provenance_files=tuple(ProvenanceFileRecord.from_dict(item) for item in provenance_files),
            canonical_part_count=canonical_part_count,
            reference_set_sha256=_optional_hash(payload, "reference_set_sha256"),
            reference_output_mapping={
                str(key): str(value) for key, value in reference_output_mapping.items()
            },
            premise=premise,
            reference_spec=reference_spec,
            split_assignment=split_assignment,
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reference_files"] = [item.to_dict() for item in self.reference_files]
        payload["provenance_files"] = [item.to_dict() for item in self.provenance_files]
        return payload


@dataclass(frozen=True)
class BenchmarkManifest:
    schema_version: str
    benchmark_id: str
    benchmark_version: str
    target_project_count: int
    target_category_count: int
    projects: tuple[BenchmarkProject, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkManifest":
        if not isinstance(payload, dict):
            raise ValueError("benchmark manifest must be an object")
        schema_version = _required_string(payload, "schema_version")
        benchmark_id = _required_string(payload, "benchmark_id")
        projects_payload = payload.get("projects")
        if not isinstance(projects_payload, list):
            raise ValueError("projects must be a list")
        projects = tuple(BenchmarkProject.from_dict(item) for item in projects_payload)
        ids = [item.benchmark_id for item in projects]
        if len(ids) != len(set(ids)):
            raise ValueError("project IDs must be unique")
        target_project_count = int(payload.get("target_project_count", 50))
        target_category_count = int(payload.get("target_category_count", 10))
        if target_project_count <= 0 or target_category_count <= 0:
            raise ValueError("benchmark targets must be positive")
        if len(projects) > target_project_count:
            raise ValueError("manifest contains more projects than its target")
        known_keys = {
            "schema_version",
            "benchmark_id",
            "benchmark_version",
            "target_project_count",
            "target_category_count",
            "projects",
        }
        return cls(
            schema_version=schema_version,
            benchmark_id=benchmark_id,
            benchmark_version=_required_string(payload, "benchmark_version"),
            target_project_count=target_project_count,
            target_category_count=target_category_count,
            projects=projects,
            metadata={key: value for key, value in payload.items() if key not in known_keys},
        )

    @classmethod
    def from_path(cls, path: Path) -> "BenchmarkManifest":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"benchmark manifest does not exist: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"benchmark manifest is not valid JSON: {path}") from exc
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "target_project_count": self.target_project_count,
            "target_category_count": self.target_category_count,
            "projects": [project.to_dict() for project in self.projects],
        }
        payload.update(self.metadata)
        return payload

    def project(self, benchmark_id: str) -> BenchmarkProject:
        for project in self.projects:
            if project.benchmark_id == benchmark_id:
                return project
        raise ValueError(f"benchmark project is not in manifest: {benchmark_id}")

    def with_project(self, replacement: BenchmarkProject) -> "BenchmarkManifest":
        if replacement.benchmark_id not in {item.benchmark_id for item in self.projects}:
            raise ValueError(f"cannot replace unknown benchmark project: {replacement.benchmark_id}")
        return replace(
            self,
            projects=tuple(
                replacement if item.benchmark_id == replacement.benchmark_id else item
                for item in self.projects
            ),
        )


@dataclass(frozen=True)
class BenchmarkRunRecord:
    schema_version: str
    benchmark_project_id: str
    mode: str
    provider_model_profile: dict[str, Any]
    prompt_hashes: dict[str, str]
    workflow_id: str | None
    revision_id: str | None
    provider_attempt_ids: tuple[str, ...]
    generated_source_hash: str | None
    worker_result: dict[str, Any]
    brep_topology_result: dict[str, Any]
    semantic_verification_result: dict[str, Any]
    artifact_hashes: dict[str, str]
    reference_metrics: dict[str, Any]
    failure_stage: str | None
    failure_class: str | None
    first_incorrect_owner: str | None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BenchmarkRunRecord":
        mode = _required_string(payload, "mode")
        if mode not in _RUN_MODE_VALUES:
            raise ValueError(f"unsupported benchmark run mode: {mode}")
        project_id = _required_string(payload, "benchmark_project_id")
        if not _PROJECT_ID_RE.fullmatch(project_id):
            raise ValueError("benchmark_project_id must be a neutral lowercase hyphenated identifier")
        return cls(
            schema_version=_required_string(payload, "schema_version"),
            benchmark_project_id=project_id,
            mode=mode,
            provider_model_profile=dict(payload.get("provider_model_profile") or {}),
            prompt_hashes=dict(payload.get("prompt_hashes") or {}),
            workflow_id=payload.get("workflow_id"),
            revision_id=payload.get("revision_id"),
            provider_attempt_ids=tuple(str(item) for item in payload.get("provider_attempt_ids", [])),
            generated_source_hash=_optional_hash(payload, "generated_source_hash"),
            worker_result=dict(payload.get("worker_result") or {}),
            brep_topology_result=dict(payload.get("brep_topology_result") or {}),
            semantic_verification_result=dict(payload.get("semantic_verification_result") or {}),
            artifact_hashes=dict(payload.get("artifact_hashes") or {}),
            reference_metrics=dict(payload.get("reference_metrics") or {}),
            failure_stage=payload.get("failure_stage"),
            failure_class=payload.get("failure_class"),
            first_incorrect_owner=payload.get("first_incorrect_owner"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provider_attempt_ids"] = list(self.provider_attempt_ids)
        return payload
