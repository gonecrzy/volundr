import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from app.services.cad.cadquery_runner import CadQueryCliRunner
from app.services.cad.jobs import (
    DuplicateJobCompletionError,
    JobManifestError,
    complete_job_atomic,
    load_job_manifest,
    result_payload,
)


_WORKER_CLAIM_FILENAME = ".worker-claim.json"


async def execute_job_directory(
    job_dir: Path,
    *,
    runner: CadQueryCliRunner | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    job_id = job_dir.name
    try:
        job = load_job_manifest(job_dir)
        job_id = job.job_id
        source = job.source_file(job_dir).read_text(encoding="utf-8")
    except JobManifestError as exc:
        result = result_payload(
            job_id=job_id,
            success=False,
            failure_class="invalid_manifest",
            duration_seconds=_duration(started),
            diagnostics={"message": str(exc)},
        )
        _persist_result(job_dir, result)
        return result

    active_runner = runner or CadQueryCliRunner(
        workspace_root=job_dir / "work",
        timeout_seconds=job.execution_limits.timeout_seconds,
    )
    compile_result = await active_runner.compile(
        source,
        job_id=job.job_id,
        source_contract_version=job.source_contract_version,
        parameter_values=job.parameter_values,
        requested_outputs=job.requested_outputs,
    )
    diagnostics: dict[str, Any] = {
        "message": compile_result.error_message,
        "timed_out": compile_result.timed_out,
        "exit_code": compile_result.exit_code,
        "command_args": compile_result.command_args,
    }
    runtime_metadata = _read_runtime_metadata(compile_result.execution_manifest_path)
    if runtime_metadata:
        diagnostics.update(runtime_metadata)
    execution_diagnostics = _worker_execution_diagnostics(job_dir, compile_result)
    if execution_diagnostics:
        diagnostics.update(execution_diagnostics)
    outputs = _result_outputs(job_dir, compile_result)
    output_failure = any(output["required"] and not output["success"] for output in outputs)
    failure_class = None
    success = bool(compile_result.success and not output_failure)
    if not success:
        failure_class = _worker_failure_class(compile_result, diagnostics)
        if failure_class == "worker_environment_failure":
            diagnostics["worker_failure_class"] = failure_class
    result = result_payload(
        job_id=job.job_id,
        success=success,
        failure_class=failure_class,
        duration_seconds=_duration(started),
        outputs=outputs,
        requested_output_ids=[
            str(output.get("output_id"))
            for output in job.requested_outputs
            if isinstance(output, dict) and output.get("output_id")
        ],
        diagnostics=diagnostics,
    )
    _persist_result(job_dir, result)
    return result


async def process_next_job(jobs_root: Path) -> dict[str, Any] | None:
    for job_dir in sorted(path for path in jobs_root.iterdir() if path.is_dir()):
        if (
            job_dir.name.startswith(".")
            or not (job_dir / "job.json").exists()
            or (job_dir / "result.json").exists()
        ):
            continue
        claim_token = _try_claim_job(job_dir)
        if claim_token is None:
            continue
        try:
            return await execute_job_directory(job_dir)
        finally:
            _release_job_claim(job_dir, claim_token)
    return None


def _worker_failure_class(compile_result: Any, diagnostics: dict[str, Any]) -> str:
    if compile_result.timed_out:
        return "timeout"
    if diagnostics.get("worker_setup_failure"):
        return "worker_environment_failure"
    return "execution_failed"


def _try_claim_job(job_dir: Path) -> str | None:
    claim_path = job_dir / _WORKER_CLAIM_FILENAME
    for _ in range(2):
        token = uuid.uuid4().hex
        payload = {
            "pid": os.getpid(),
            "started_at": time.time(),
            "token": token,
        }
        try:
            descriptor = os.open(
                claim_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            if not _claim_is_stale(claim_path):
                return None
            try:
                claim_path.unlink()
            except FileNotFoundError:
                continue
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        return token
    return None


def _claim_is_stale(claim_path: Path) -> bool:
    try:
        payload = json.loads(claim_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if not isinstance(pid, int) or pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    except OSError:
        return True
    return False


def _release_job_claim(job_dir: Path, token: str) -> None:
    claim_path = job_dir / _WORKER_CLAIM_FILENAME
    try:
        payload = json.loads(claim_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(payload, dict) and payload.get("token") == token:
        claim_path.unlink(missing_ok=True)


def _persist_result(job_dir: Path, result: dict[str, Any]) -> None:
    try:
        complete_job_atomic(job_dir, result)
    except DuplicateJobCompletionError:
        raise


def _duration(started: float) -> float:
    return round(time.monotonic() - started, 6)


def _read_runtime_metadata(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    metadata: dict[str, Any] = {}
    for source_key, target_key in (
        ("cadquery_version", "cadquery_version"),
        ("worker_version", "cadquery_worker_version"),
    ):
        value = payload.get(source_key)
        if isinstance(value, str) and value:
            metadata[target_key] = value
    return metadata


def _worker_execution_diagnostics(job_dir: Path, compile_result: Any) -> dict[str, Any]:
    raw = getattr(compile_result, "execution_diagnostics", None)
    if not isinstance(raw, dict):
        return {}
    diagnostics = dict(raw)
    source_path = getattr(compile_result, "source_path", None)
    inner_job_dir = source_path.parent if isinstance(source_path, Path) else None
    for key, path in (
        ("partial_stdout_path", getattr(compile_result, "stdout_path", None)),
        ("partial_stderr_path", getattr(compile_result, "stderr_path", None)),
    ):
        relative = _relative_path(job_dir, path) if isinstance(path, Path) else None
        if relative is not None:
            diagnostics[key] = relative
    if inner_job_dir is not None:
        diagnostic_state_path = inner_job_dir / "diagnostic-state.json"
        relative_state_path = _relative_path(job_dir, diagnostic_state_path)
        if relative_state_path is not None:
            diagnostics["partial_diagnostic_state_path"] = relative_state_path
            diagnostics["partial_timing_record_path"] = relative_state_path
    source_hash = getattr(compile_result, "source_hash", None)
    if isinstance(source_hash, str) and source_hash:
        diagnostics["source_hash"] = source_hash
    return {key: value for key, value in diagnostics.items() if value is not None}


def _relative_path(job_dir: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(job_dir.resolve()))
    except ValueError:
        return None


def _result_outputs(job_dir: Path, compile_result: Any) -> list[dict[str, Any]]:
    if getattr(compile_result, "outputs", None):
        results = []
        for output in compile_result.outputs:
            stl_path = _relative_path(job_dir, output.stl_path)
            step_path = _relative_path(job_dir, output.step_path)
            brep_path = _relative_path(job_dir, output.brep_path)
            metadata_path = _relative_path(job_dir, output.metadata_path)
            topology_metadata_path = _relative_path(job_dir, output.topology_metadata_path)
            success = bool(output.success)
            compile_error = output.compile_error
            if success and any(
                original_path is not None and relative_path is None
                for original_path, relative_path in (
                    (output.stl_path, stl_path),
                    (output.step_path, step_path),
                    (output.brep_path, brep_path),
                    (output.metadata_path, metadata_path),
                    (output.topology_metadata_path, topology_metadata_path),
                )
            ):
                success = False
                compile_error = "output artifact path is outside job directory"
            results.append(
                {
                "output_id": output.output_id,
                "entrypoint": output.entrypoint,
                "required": output.required,
                "success": success,
                "stl_path": stl_path,
                "step_path": step_path,
                "brep_path": brep_path,
                "metadata_path": metadata_path,
                "topology_metadata_path": topology_metadata_path,
                "source_hash": compile_result.source_hash,
                "stl_hash": output.stl_hash,
                "step_hash": output.step_hash,
                "brep_hash": output.brep_hash,
                "stl_size_bytes": output.output_size_bytes,
                "topology_metadata": output.topology_metadata,
                "compile_error": compile_error,
            }
            )
        return results
    if not compile_result.success:
        return []
    return [
        {
            "output_id": "model",
            "entrypoint": "build",
            "required": True,
            "success": True,
            "stl_path": _relative_path(job_dir, compile_result.stl_path),
            "step_path": _relative_path(job_dir, compile_result.step_path),
            "brep_path": None,
            "metadata_path": _relative_path(job_dir, compile_result.metadata_path),
            "topology_metadata_path": None,
            "source_hash": compile_result.source_hash,
            "stl_hash": None,
            "step_hash": None,
            "brep_hash": None,
            "stl_size_bytes": compile_result.output_size_bytes,
            "topology_metadata": None,
            "compile_error": None,
        }
    ]
