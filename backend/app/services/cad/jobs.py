import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


CAD_EXECUTION_JOB_SCHEMA_VERSION = "cad-execution-job-v1"
CAD_EXECUTION_RESULT_SCHEMA_VERSION = "cad-execution-result-v1"

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class JobManifestError(ValueError):
    pass


class DuplicateJobCompletionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CadExecutionLimits:
    timeout_seconds: int = 60


@dataclass(frozen=True)
class CadExecutionJob:
    schema_version: str
    job_id: str
    cad_backend: str
    source_language: str
    source_path: Path
    source_hash: str
    parameter_values: dict[str, Any] = field(default_factory=dict)
    requested_outputs: list[dict[str, Any]] = field(default_factory=list)
    execution_limits: CadExecutionLimits = field(default_factory=CadExecutionLimits)

    def source_file(self, job_dir: Path) -> Path:
        path = _resolve_job_relative_path(job_dir, self.source_path, field_name="source_path")
        if not path.is_file():
            raise JobManifestError("source_path does not exist")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != self.source_hash:
            raise JobManifestError("source_hash does not match source_path")
        return path


class FilesystemCadJobQueue:
    def __init__(self, jobs_root: Path) -> None:
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)

    def submit_cadquery_source(
        self,
        *,
        source: str,
        job_id: str,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
        timeout_seconds: int = 60,
    ) -> Path:
        _validate_job_id(job_id)
        job_dir = self.jobs_root / job_id
        tmp_dir = self.jobs_root / f".{job_id}.tmp-{os.getpid()}"
        if job_dir.exists() or tmp_dir.exists():
            raise FileExistsError(f"CAD job already exists: {job_id}")

        input_dir = tmp_dir / "input"
        input_dir.mkdir(parents=True)
        tmp_dir.chmod(0o1777)
        source_path = input_dir / "model.py"
        source_path.write_text(source, encoding="utf-8")
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        manifest = {
            "schema_version": CAD_EXECUTION_JOB_SCHEMA_VERSION,
            "job_id": job_id,
            "cad_backend": "cadquery",
            "source_language": "python",
            "source_path": "input/model.py",
            "source_hash": source_hash,
            "parameter_values": parameter_values or {},
            "requested_outputs": requested_outputs or [],
            "execution_limits": {"timeout_seconds": timeout_seconds},
        }
        (tmp_dir / "job.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_dir, job_dir)
        return job_dir


def load_job_manifest(job_dir: Path) -> CadExecutionJob:
    manifest_path = job_dir / "job.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobManifestError("job manifest is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise JobManifestError("job manifest must be an object")

    schema_version = _require_str(payload, "schema_version")
    if schema_version != CAD_EXECUTION_JOB_SCHEMA_VERSION:
        raise JobManifestError("unsupported job schema_version")
    job_id = _require_str(payload, "job_id")
    _validate_job_id(job_id)
    cad_backend = _require_str(payload, "cad_backend")
    if cad_backend != "cadquery":
        raise JobManifestError("cad_backend must be cadquery")
    source_language = _require_str(payload, "source_language")
    if source_language != "python":
        raise JobManifestError("source_language must be python")
    source_path = Path(_require_str(payload, "source_path"))
    _resolve_job_relative_path(job_dir, source_path, field_name="source_path")
    source_hash = _require_str(payload, "source_hash")
    if not re.fullmatch(r"[a-fA-F0-9]{64}", source_hash):
        raise JobManifestError("source_hash must be a sha256 hex digest")
    parameter_values = payload.get("parameter_values", {})
    if not isinstance(parameter_values, dict):
        raise JobManifestError("parameter_values must be an object")
    requested_outputs = payload.get("requested_outputs", [])
    if not isinstance(requested_outputs, list):
        raise JobManifestError("requested_outputs must be a list")
    limits_payload = payload.get("execution_limits", {})
    if not isinstance(limits_payload, dict):
        raise JobManifestError("execution_limits must be an object")
    timeout_seconds = int(limits_payload.get("timeout_seconds", 60))
    if timeout_seconds <= 0 or timeout_seconds > 3600:
        raise JobManifestError("execution_limits.timeout_seconds is out of range")

    job = CadExecutionJob(
        schema_version=schema_version,
        job_id=job_id,
        cad_backend=cad_backend,
        source_language=source_language,
        source_path=source_path,
        source_hash=source_hash.lower(),
        parameter_values=parameter_values,
        requested_outputs=requested_outputs,
        execution_limits=CadExecutionLimits(timeout_seconds=timeout_seconds),
    )
    job.source_file(job_dir)
    return job


def complete_job_atomic(job_dir: Path, result: dict[str, Any]) -> Path:
    result_path = job_dir / "result.json"
    if result_path.exists():
        raise DuplicateJobCompletionError(f"CAD job already completed: {job_dir.name}")
    tmp_path = job_dir / ".result.json.tmp"
    tmp_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, result_path)
    return result_path


def load_job_result(job_dir: Path) -> dict[str, Any]:
    return json.loads((job_dir / "result.json").read_text(encoding="utf-8"))


def result_payload(
    *,
    job_id: str,
    success: bool,
    failure_class: str | None,
    duration_seconds: float,
    outputs: list[dict[str, Any]] | None = None,
    diagnostics: dict[str, Any] | None = None,
    worker_version: str = "cad-worker-v1",
) -> dict[str, Any]:
    return {
        "schema_version": CAD_EXECUTION_RESULT_SCHEMA_VERSION,
        "job_id": job_id,
        "success": success,
        "failure_class": failure_class,
        "duration_seconds": duration_seconds,
        "outputs": outputs or [],
        "diagnostics": diagnostics or {},
        "worker_version": worker_version,
    }


def _require_str(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise JobManifestError(f"{field_name} is required")
    return value


def _validate_job_id(job_id: str) -> None:
    if not _JOB_ID_RE.fullmatch(job_id) or job_id.strip(".-") != job_id:
        raise JobManifestError("job_id contains unsafe characters")


def _resolve_job_relative_path(job_dir: Path, path: Path, *, field_name: str) -> Path:
    if path.is_absolute() or ".." in path.parts:
        raise JobManifestError(f"{field_name} must stay inside the job directory")
    resolved_job_dir = job_dir.resolve()
    resolved_path = (job_dir / path).resolve()
    try:
        resolved_path.relative_to(resolved_job_dir)
    except ValueError as exc:
        raise JobManifestError(f"{field_name} must stay inside the job directory") from exc
    return resolved_path
