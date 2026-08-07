import asyncio
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.cad.cadquery_contract import (
    CadQueryContractError,
    validate_cadquery_source,
)
from app.services.mesh.inspect import MeshMetadata, inspect_stl


@dataclass(frozen=True)
class CadQueryOutputResult:
    output_id: str
    entrypoint: str
    required: bool
    success: bool
    stl_path: Path | None
    step_path: Path | None
    brep_path: Path | None
    metadata_path: Path | None
    topology_metadata_path: Path | None
    stl_hash: str | None
    step_hash: str | None
    brep_hash: str | None
    output_size_bytes: int
    metadata: MeshMetadata | None
    topology_metadata: dict | None
    feature_trace: list[dict] = field(default_factory=list)
    feature_trace_available: bool = False
    compile_error: str | None = None


@dataclass(frozen=True)
class CadQueryCompileResult:
    job_id: str
    success: bool
    timed_out: bool
    exit_code: int | None
    source_path: Path | None
    stl_path: Path | None
    step_path: Path | None
    stdout_path: Path | None
    stderr_path: Path | None
    metadata_path: Path | None
    source_hash: str
    output_size_bytes: int
    metadata: MeshMetadata | None
    error_message: str | None
    command_args: list[str] | None = None
    outputs: list[CadQueryOutputResult] = field(default_factory=list)
    execution_manifest_path: Path | None = None
    execution_timing: dict | None = None
    execution_diagnostics: dict | None = None


class CadQueryCliRunner:
    def __init__(
        self,
        *,
        python_binary: str | None = None,
        workspace_root: Path | None = None,
        timeout_seconds: int | None = None,
        max_source_bytes: int | None = None,
        max_stl_bytes: int | None = None,
    ) -> None:
        self.python_binary = python_binary or sys.executable
        self.workspace_root = workspace_root or settings.cad_workspace_dir
        self.timeout_seconds = timeout_seconds or settings.cad_timeout_seconds
        self.max_source_bytes = max_source_bytes or settings.max_source_bytes
        self.max_stl_bytes = max_stl_bytes or settings.max_stl_bytes

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        source_contract_version: str = "cadquery-v1",
        parameter_values: dict | None = None,
        requested_outputs: list[dict] | None = None,
    ) -> CadQueryCompileResult:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        rejection = self._screen_source(source, source_contract_version=source_contract_version)
        if rejection is not None:
            return self._failure(
                job_id=job_id,
                source_hash=source_hash,
                error_message=rejection,
            )

        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        source_path = job_dir / "model.py"
        runner_path = job_dir / "_volundr_cadquery_runner.py"
        output_dir = job_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        execution_result_path = job_dir / "execution-manifest.json"
        parameter_values_path = job_dir / "parameter-values.json"
        requested_outputs_path = job_dir / "requested-outputs.json"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        diagnostic_state_path = job_dir / "diagnostic-state.json"
        source_path.write_text(source, encoding="utf-8")
        runner_path.write_text(_CADQUERY_RUNNER_SOURCE, encoding="utf-8")
        parameter_values_path.write_text(
            json.dumps(parameter_values or {}, sort_keys=True),
            encoding="utf-8",
        )
        requested_outputs_path.write_text(
            json.dumps(requested_outputs or [], sort_keys=True),
            encoding="utf-8",
        )

        command_args = [
            self.python_binary,
            str(runner_path.name),
            str(output_dir.name),
            str(execution_result_path.name),
            str(parameter_values_path.name),
            str(requested_outputs_path.name),
        ]
        started_at = time.monotonic()
        timeout_deadline = started_at + self.timeout_seconds
        process = await asyncio.create_subprocess_exec(
            *command_args,
            cwd=job_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._subprocess_env(),
            start_new_session=True,
        )

        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            self._terminate_process_group(process.pid)
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=2,
                )
            except TimeoutError:
                self._kill_process_group(process.pid)
                stdout, stderr = await process.communicate()

        stdout_path.write_bytes(stdout)
        stderr_path.write_bytes(stderr)
        exit_code = process.returncode
        timeout_diagnostics = None
        if timed_out:
            timeout_diagnostics = self._timeout_diagnostics(
                job_dir=job_dir,
                source_hash=source_hash,
                execution_result_path=execution_result_path,
                diagnostic_state_path=diagnostic_state_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                process_pid=process.pid,
                exit_code=exit_code,
                started_at=started_at,
                timeout_deadline=timeout_deadline,
            )

        if timed_out:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=True,
                exit_code=exit_code,
                error_message=f"CadQuery timed out after {self.timeout_seconds} seconds",
                command_args=command_args,
                execution_manifest_path=execution_result_path if execution_result_path.exists() else None,
                execution_diagnostics=timeout_diagnostics,
            )

        if exit_code != 0:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=self._diagnostic(stderr, "CadQuery failed"),
                command_args=command_args,
                execution_manifest_path=execution_result_path if execution_result_path.exists() else None,
            )

        try:
            execution_payload = json.loads(execution_result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=None,
                step_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="CadQuery did not produce an execution result",
                command_args=command_args,
                execution_manifest_path=execution_result_path if execution_result_path.exists() else None,
            )

        outputs = self._collect_output_results(job_dir, execution_payload)
        successful_outputs = [output for output in outputs if output.success]
        required_failures = [output for output in outputs if output.required and not output.success]
        if not outputs or not successful_outputs or required_failures:
            error_message = "CadQuery did not produce required outputs"
            if required_failures and required_failures[0].compile_error:
                error_message = required_failures[0].compile_error
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=successful_outputs[0].stl_path if successful_outputs else None,
                step_path=successful_outputs[0].step_path if successful_outputs else None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message=error_message,
                command_args=command_args,
                outputs=outputs,
                execution_manifest_path=execution_result_path,
            )

        oversized_output = next(
            (
                output
                for output in successful_outputs
                if output.output_size_bytes > self.max_stl_bytes
            ),
            None,
        )
        if oversized_output is not None:
            return self._compile_failure(
                job_id=job_id,
                source_path=source_path,
                stl_path=oversized_output.stl_path,
                step_path=oversized_output.step_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                source_hash=source_hash,
                timed_out=False,
                exit_code=exit_code,
                error_message="generated STL exceeds size limit",
                command_args=command_args,
                outputs=outputs,
                execution_manifest_path=execution_result_path,
            )

        primary_output = successful_outputs[0]
        return CadQueryCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=primary_output.stl_path,
            step_path=primary_output.step_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=primary_output.metadata_path,
            source_hash=source_hash,
            output_size_bytes=sum(output.output_size_bytes for output in successful_outputs),
            metadata=primary_output.metadata,
            error_message=None,
            command_args=self._safe_command_args(command_args),
            outputs=outputs,
            execution_manifest_path=execution_result_path,
            execution_timing=execution_payload.get("execution_timing")
            if isinstance(execution_payload.get("execution_timing"), dict)
            else None,
            execution_diagnostics=self._execution_diagnostics_from_payload(
                job_dir=job_dir,
                execution_payload=execution_payload,
                diagnostic_state_path=diagnostic_state_path,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timed_out=False,
                timeout_seconds=self.timeout_seconds,
                process_pid=process.pid,
                exit_code=exit_code,
                started_at=started_at,
                timeout_deadline=timeout_deadline,
            ),
        )

    def _screen_source(self, source: str, *, source_contract_version: str) -> str | None:
        if not source.strip():
            return "source is empty"
        if len(source.encode("utf-8")) > self.max_source_bytes:
            return "source exceeds size limit"
        if source_contract_version != "cadquery-v1":
            return "unsupported CadQuery source_contract_version"
        try:
            validate_cadquery_source(source, contract_version=source_contract_version)
        except CadQueryContractError as exc:
            return f"CadQuery contract violation: {exc}"
        return None

    def _job_dir(self, job_id: str) -> Path:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", job_id).strip(".-")
        if not safe_id:
            safe_id = "job"
        path = self.workspace_root / safe_id
        if path.exists():
            path = self.workspace_root / f"{safe_id}-{uuid.uuid4().hex}"
        return path

    def _failure(
        self,
        *,
        job_id: str,
        source_hash: str,
        error_message: str,
    ) -> CadQueryCompileResult:
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=False,
            exit_code=None,
            source_path=None,
            stl_path=None,
            step_path=None,
            stdout_path=None,
            stderr_path=None,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=0,
            metadata=None,
            error_message=error_message,
            command_args=None,
            execution_diagnostics=None,
        )

    def _compile_failure(
        self,
        *,
        job_id: str,
        source_path: Path,
        stl_path: Path | None,
        step_path: Path | None,
        stdout_path: Path,
        stderr_path: Path,
        source_hash: str,
        timed_out: bool,
        exit_code: int | None,
        error_message: str,
        command_args: list[str],
        outputs: list[CadQueryOutputResult] | None = None,
        execution_manifest_path: Path | None = None,
        execution_diagnostics: dict | None = None,
    ) -> CadQueryCompileResult:
        execution_timing = None
        payload = None
        if execution_manifest_path is not None and execution_manifest_path.exists():
            try:
                payload = json.loads(execution_manifest_path.read_text(encoding="utf-8"))
                execution_timing = payload.get("execution_timing")
            except (OSError, json.JSONDecodeError):
                execution_timing = None
                payload = None
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=timed_out,
            exit_code=exit_code,
            source_path=source_path,
            stl_path=stl_path if stl_path is not None and stl_path.exists() else None,
            step_path=step_path if step_path is not None and step_path.exists() else None,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=self._file_size(stl_path),
            metadata=None,
            error_message=error_message,
            command_args=self._safe_command_args(command_args),
            outputs=outputs or [],
            execution_manifest_path=execution_manifest_path,
            execution_timing=execution_timing if isinstance(execution_timing, dict) else None,
            execution_diagnostics=execution_diagnostics
            if execution_diagnostics is not None
            else self._execution_diagnostics_from_payload(
                job_dir=source_path.parent,
                execution_payload=payload,
                diagnostic_state_path=source_path.parent / "diagnostic-state.json",
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timed_out=timed_out,
                timeout_seconds=self.timeout_seconds,
                process_pid=None,
                exit_code=exit_code,
                started_at=None,
                timeout_deadline=None,
            ),
        )

    def _timeout_diagnostics(
        self,
        *,
        job_dir: Path,
        source_hash: str,
        execution_result_path: Path,
        diagnostic_state_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        process_pid: int | None,
        exit_code: int | None,
        started_at: float,
        timeout_deadline: float,
    ) -> dict[str, Any]:
        payload = self._read_json(execution_result_path)
        return self._execution_diagnostics_from_payload(
            job_dir=job_dir,
            execution_payload=payload,
            diagnostic_state_path=diagnostic_state_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timed_out=True,
            timeout_seconds=self.timeout_seconds,
            process_pid=process_pid,
            exit_code=exit_code,
            started_at=started_at,
            timeout_deadline=timeout_deadline,
            source_hash=source_hash,
        )

    def _execution_diagnostics_from_payload(
        self,
        *,
        job_dir: Path,
        execution_payload: dict | None,
        diagnostic_state_path: Path,
        stdout_path: Path,
        stderr_path: Path,
        timed_out: bool,
        timeout_seconds: int,
        process_pid: int | None,
        exit_code: int | None,
        started_at: float | None,
        timeout_deadline: float | None,
        source_hash: str | None = None,
    ) -> dict[str, Any]:
        state = self._read_json(diagnostic_state_path)
        if not isinstance(state, dict):
            state = {}
        payload_state = execution_payload.get("diagnostic_state") if isinstance(execution_payload, dict) else None
        if isinstance(payload_state, dict):
            state = {**state, **payload_state}
        per_output = state.get("per_output_results") if isinstance(state.get("per_output_results"), dict) else {}
        completed_output_ids = [
            str(output_id)
            for output_id, result in per_output.items()
            if isinstance(result, dict) and result.get("status") == "completed"
        ]
        incomplete_output_ids = [
            str(output_id)
            for output_id, result in per_output.items()
            if isinstance(result, dict) and result.get("status") not in {"completed"}
        ]
        diagnostics = {
            "timed_out": timed_out,
            "timeout_seconds": timeout_seconds,
            "subprocess_pid": process_pid,
            "subprocess_exit_status": exit_code,
            "started_at_monotonic": started_at,
            "timeout_deadline_monotonic": timeout_deadline,
            "active_phase": state.get("active_phase"),
            "active_output_id": state.get("active_output_id"),
            "active_function": state.get("active_function"),
            "active_operation": state.get("active_operation"),
            "active_export_format": state.get("active_export_format"),
            "operation_started_at_monotonic": state.get("operation_started_at_monotonic"),
            "operation_elapsed_seconds": (
                round(time.monotonic() - float(state["operation_started_at_monotonic"]), 6)
                if isinstance(state.get("operation_started_at_monotonic"), (int, float))
                else None
            ),
            "last_completed_operation": state.get("last_completed_operation"),
            "last_started_incomplete_operation": state.get("last_started_incomplete_operation"),
            "failure_phase": state.get("failure_phase"),
            "failure_output_id": state.get("failure_output_id"),
            "failure_operation": state.get("failure_operation"),
            "failure_operation_before": state.get("failure_operation_before"),
            "failure_exception_type": state.get("failure_exception_type"),
            "failure_message": state.get("failure_message"),
            "normalized_exception": state.get("normalized_exception"),
            "failure_source_function": state.get("failure_source_function"),
            "failure_source_line": state.get("failure_source_line"),
            "completed_output_ids": completed_output_ids,
            "incomplete_output_ids": incomplete_output_ids,
            "per_output_results": per_output,
            "partial_timing_record_path": self._relative_path(job_dir, diagnostic_state_path),
            "partial_diagnostic_state_path": self._relative_path(job_dir, diagnostic_state_path),
            "partial_stdout_path": self._relative_path(job_dir, stdout_path),
            "partial_stderr_path": self._relative_path(job_dir, stderr_path),
            "process_rss_kb": state.get("process_rss_kb"),
            "source_hash": source_hash or state.get("source_hash"),
            "failure_source_hash": state.get("failure_source_hash"),
            "cadquery_version": (
                execution_payload.get("cadquery_version")
                if isinstance(execution_payload, dict)
                else state.get("cadquery_version")
            ) or state.get("cadquery_version"),
            "cadquery_worker_version": (
                execution_payload.get("worker_version")
                if isinstance(execution_payload, dict)
                else state.get("cadquery_worker_version")
            ) or state.get("cadquery_worker_version"),
        }
        if execution_payload is None and not state:
            diagnostics["worker_setup_failure"] = True
            diagnostics["worker_phase"] = "child_initialization"
        return {key: value for key, value in diagnostics.items() if value is not None}

    def _read_json(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _relative_path(self, job_dir: Path, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return str(path.resolve().relative_to(job_dir.resolve()))
        except ValueError:
            return None

    def _collect_output_results(
        self,
        job_dir: Path,
        execution_payload: dict,
    ) -> list[CadQueryOutputResult]:
        raw_outputs = execution_payload.get("outputs", [])
        if not isinstance(raw_outputs, list):
            return []
        outputs: list[CadQueryOutputResult] = []
        for raw_output in raw_outputs:
            if not isinstance(raw_output, dict):
                continue
            output_id = str(raw_output.get("output_id") or "model")
            stl_path = self._job_relative_path(job_dir, raw_output.get("stl_path"))
            step_path = self._job_relative_path(job_dir, raw_output.get("step_path"))
            brep_path = self._job_relative_path(job_dir, raw_output.get("brep_path"))
            topology_metadata = raw_output.get("topology_metadata")
            topology_metadata_path: Path | None = None
            if isinstance(topology_metadata, dict):
                topology_metadata_path = (stl_path.parent if stl_path else job_dir) / "topology.json"
                topology_metadata_path.write_text(
                    json.dumps(topology_metadata, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            metadata: MeshMetadata | None = None
            metadata_path: Path | None = None
            output_size = self._file_size(stl_path) if stl_path is not None else 0
            success = bool(raw_output.get("success", False))
            compile_error = raw_output.get("compile_error")
            if success and stl_path is not None:
                try:
                    metadata = inspect_stl(stl_path)
                    metadata_path = stl_path.with_suffix(".metadata.json")
                    metadata_path.write_text(
                        json.dumps(asdict(metadata), indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                except ValueError as exc:
                    success = False
                    compile_error = str(exc)
            if success:
                if step_path is None or not step_path.exists():
                    success = False
                    compile_error = "STEP artifact is missing"
                elif not _step_file_looks_valid(step_path):
                    success = False
                    compile_error = "STEP artifact is malformed"
            outputs.append(
                CadQueryOutputResult(
                    output_id=output_id,
                    entrypoint=str(raw_output.get("entrypoint") or output_id),
                    required=bool(raw_output.get("required", True)),
                    success=success,
                    stl_path=stl_path if stl_path and stl_path.exists() else None,
                    step_path=step_path if step_path and step_path.exists() else None,
                    brep_path=brep_path if brep_path and brep_path.exists() else None,
                    metadata_path=metadata_path,
                    topology_metadata_path=topology_metadata_path,
                    stl_hash=self._sha256_file(stl_path) if stl_path and stl_path.exists() else None,
                    step_hash=self._sha256_file(step_path) if step_path and step_path.exists() else None,
                    brep_hash=self._sha256_file(brep_path) if brep_path and brep_path.exists() else None,
                    output_size_bytes=output_size,
                    metadata=metadata,
                    topology_metadata=topology_metadata if isinstance(topology_metadata, dict) else None,
                    feature_trace=[
                        item for item in raw_output.get("feature_trace", [])
                        if isinstance(item, dict)
                    ],
                    feature_trace_available=bool(execution_payload.get("feature_trace_supported", False)),
                    compile_error=str(compile_error) if compile_error else None,
                )
            )
        return outputs

    def _terminate_process_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    def _kill_process_group(self, pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _file_size(self, path: Path | None) -> int:
        return path.stat().st_size if path is not None and path.exists() else 0

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _job_relative_path(self, job_dir: Path, raw_path: object) -> Path | None:
        if not isinstance(raw_path, str) or not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute() or ".." in path.parts:
            return None
        resolved_job_dir = job_dir.resolve()
        resolved_path = (job_dir / path).resolve()
        try:
            resolved_path.relative_to(resolved_job_dir)
        except ValueError:
            return None
        return resolved_path

    def _diagnostic(self, stderr: bytes, fallback: str) -> str:
        decoded = stderr.decode("utf-8", errors="replace").strip()
        return decoded or fallback

    def _safe_command_args(self, args: list[str]) -> list[str]:
        return [Path(arg).name if Path(arg).is_absolute() else arg for arg in args]

    def _subprocess_env(self) -> dict[str, str]:
        allowed_keys = {
            "LANG",
            "LC_ALL",
            "PATH",
            "PYTHONIOENCODING",
            "TZ",
        }
        env = {
            key: value
            for key, value in os.environ.items()
            if key in allowed_keys and value
        }
        env.setdefault("PATH", os.defpath)
        env["HOME"] = str(self.workspace_root / ".home")
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        # CadQuery imports VTK and numerical libraries in the isolated child.
        # Keep their thread pools bounded so one job cannot exhaust the
        # worker's process/thread budget before the CAD timeout can intervene.
        for key in (
            "OPENBLAS_NUM_THREADS",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            env[key] = os.environ.get(key, "1")
        env["VTK_SMP_MAX_THREADS"] = os.environ.get("VTK_SMP_MAX_THREADS", "1")
        return env


def _step_file_looks_valid(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(512).decode("ascii", errors="ignore").upper()
    except OSError:
        return False
    return "ISO-10303-21" in prefix and "HEADER" in prefix


_CADQUERY_RUNNER_SOURCE = """
import hashlib
import importlib.util
import json
import re
import resource
import signal
import sys
import time
from pathlib import Path

from app.services.cad.cadquery_contract import CadQueryContractError, validate_cadquery_source
from app.services.cad.topology_evidence import collect_topology_evidence

PLACEMENT_POLICY = "cadquery-output-placement-v1"
PLACEMENT_TOLERANCE_MM = 1e-6
cq = None
ParameterValues = None
Product = None
_TIMING = {"functions": [], "operations": [], "outputs": {}}
_FEATURE_TRACE = []
_RESULT_PATH = None
_DIAGNOSTIC_STATE_PATH = None
_STARTED_AT = None
_ACTIVE_OPERATION = None
_COUNTED_OPERATION_NAMES = {"sweep", "cut", "cutBlind", "cutThruAll", "union", "intersect", "fillet", "chamfer", "loft", "shell"}
_DIAGNOSTIC_STATE = {
    "schema_version": "volundr-cadquery-diagnostic-state-v1",
    "per_output_results": {},
    "completed_output_ids": [],
    "phase_events": [],
}


def _rss_kb():
    try:
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except Exception:
        return None


def _write_diagnostic_state():
    if _DIAGNOSTIC_STATE_PATH is None:
        return
    try:
        if _STARTED_AT is not None:
            _DIAGNOSTIC_STATE["elapsed_ms"] = round((time.perf_counter() - _STARTED_AT) * 1000, 3)
        rss_kb = _rss_kb()
        if rss_kb is not None:
            _DIAGNOSTIC_STATE["process_rss_kb"] = rss_kb
        tmp_path = _DIAGNOSTIC_STATE_PATH.with_name(f".{_DIAGNOSTIC_STATE_PATH.name}.tmp")
        tmp_path.write_text(
            json.dumps(_DIAGNOSTIC_STATE, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(_DIAGNOSTIC_STATE_PATH)
    except OSError:
        pass


def _safe_exception_message(exc):
    message = " ".join(str(exc).split())
    message = re.sub(
        r"(?i)(?:GEMINI_API_KEY_2|GEMINI_API_KEY|api[_-]?key|authorization|token)\\s*[=:]\\s*[^\\s,;]+",
        "[redacted]",
        message,
    )
    message = re.sub(r"(?i)(?:/root/|/home/|/users/|[A-Za-z]:[\\/])[^\\s,;]+", "[path]", message)
    return message[:800]


def _record_failure(exc):
    if _DIAGNOSTIC_STATE.get("failure_exception_type"):
        return
    source_frame = None
    traceback = exc.__traceback__
    while traceback is not None:
        frame = traceback.tb_frame
        if frame.f_globals.get("__name__") == "volundr_generated_model":
            source_frame = frame
        traceback = traceback.tb_next
    stack_frame = sys._getframe()
    while stack_frame is not None:
        if stack_frame.f_globals.get("__name__") == "volundr_generated_model":
            source_frame = stack_frame
            break
        stack_frame = stack_frame.f_back
    operation = _ACTIVE_OPERATION if isinstance(_ACTIVE_OPERATION, dict) else {}
    normalized_message = _safe_exception_message(exc)
    requested_output_ids = _DIAGNOSTIC_STATE.get("requested_output_ids") or []
    failure_output_id = _DIAGNOSTIC_STATE.get("active_output_id")
    if failure_output_id is None and len(requested_output_ids) == 1:
        failure_output_id = requested_output_ids[0]
    _DIAGNOSTIC_STATE.update({
        "failure_phase": _DIAGNOSTIC_STATE.get("active_phase"),
        "failure_output_id": failure_output_id,
        "failure_operation": operation.get("name"),
        "failure_operation_before": operation.get("before"),
        "failure_exception_type": type(exc).__name__,
        "failure_message": normalized_message,
        "normalized_exception": f"{type(exc).__name__} / {normalized_message}",
        "failure_source_function": source_frame.f_code.co_name if source_frame is not None else _DIAGNOSTIC_STATE.get("active_function"),
        "failure_source_line": source_frame.f_lineno if source_frame is not None else None,
        "failure_source_hash": _DIAGNOSTIC_STATE.get("source_hash"),
    })
    _write_diagnostic_state()


def _set_phase(phase):
    _DIAGNOSTIC_STATE["active_phase"] = phase
    _DIAGNOSTIC_STATE["phase_started_at_monotonic"] = time.perf_counter()
    _DIAGNOSTIC_STATE.setdefault("phase_events", []).append({
        "phase": phase,
        "event": "started",
        "at_monotonic": _DIAGNOSTIC_STATE["phase_started_at_monotonic"],
    })
    _write_diagnostic_state()


def _complete_phase(phase):
    _DIAGNOSTIC_STATE.setdefault("phase_events", []).append({
        "phase": phase,
        "event": "completed",
        "at_monotonic": time.perf_counter(),
    })
    _write_diagnostic_state()


def _initialize_diagnostic_state(source_path, requested_outputs):
    _DIAGNOSTIC_STATE["source_hash"] = _file_sha256(source_path)
    _DIAGNOSTIC_STATE["requested_output_ids"] = [
        str(request.get("output_id") or "")
        for request in requested_outputs
        if isinstance(request, dict) and request.get("output_id")
    ]
    _DIAGNOSTIC_STATE["per_output_results"] = {
        str(request.get("output_id") or ""): {
            "status": "not_attempted",
            "required": bool(request.get("required", True)),
        }
        for request in requested_outputs
        if isinstance(request, dict) and request.get("output_id")
    }
    _DIAGNOSTIC_STATE["completed_output_ids"] = []
    _write_diagnostic_state()


def _initialize_output_requests(requests):
    per_output = _DIAGNOSTIC_STATE.setdefault("per_output_results", {})
    requested_ids = []
    for request in requests:
        if not isinstance(request, dict):
            continue
        output_id = str(request.get("output_id") or "")
        if not output_id:
            continue
        requested_ids.append(output_id)
        per_output.setdefault(output_id, {"status": "not_attempted"})
    _DIAGNOSTIC_STATE["requested_output_ids"] = requested_ids
    _write_diagnostic_state()


def _set_output_status(output_id, status, **extra):
    if not output_id:
        return
    per_output = _DIAGNOSTIC_STATE.setdefault("per_output_results", {})
    current = per_output.get(output_id) if isinstance(per_output.get(output_id), dict) else {}
    current.update({
        "status": status,
        "updated_at_monotonic": time.perf_counter(),
        **extra,
    })
    if status == "started" and "started_at_monotonic" not in current:
        current["started_at_monotonic"] = current["updated_at_monotonic"]
    if status == "completed":
        completed = _DIAGNOSTIC_STATE.setdefault("completed_output_ids", [])
        if output_id not in completed:
            completed.append(output_id)
    per_output[output_id] = current
    _DIAGNOSTIC_STATE["active_output_id"] = output_id if status == "started" else None
    _write_diagnostic_state()


def _output_status(result):
    if not isinstance(result, dict):
        return "execution_failed"
    if result.get("success") is True:
        return "completed"
    message = str(result.get("compile_error") or "")
    if message == "output shape is invalid" or message == "print-placed output shape is invalid":
        return "invalid_shape"
    if "export" in message.lower():
        return "export_failed"
    if message.startswith("requested output not found"):
        return "not_found"
    return "execution_failed"


def _set_export(output_id, export_format):
    _DIAGNOSTIC_STATE["active_output_id"] = output_id
    _DIAGNOSTIC_STATE["active_export_format"] = export_format
    _set_phase(f"{export_format.lower()}_export")


def _clear_export():
    _DIAGNOSTIC_STATE["active_export_format"] = None
    _write_diagnostic_state()


class _FunctionProfiler:
    def __init__(self):
        self.active = {}
        self.records = []

    def __call__(self, frame, event, _arg):
        if frame.f_globals.get("__name__") != "volundr_generated_model":
            return self
        key = id(frame)
        if event == "call":
            self.active[key] = (frame.f_code.co_name, time.perf_counter())
            _DIAGNOSTIC_STATE["active_function"] = frame.f_code.co_name
            _write_diagnostic_state()
        elif event in {"return", "exception"}:
            record = self.active.pop(key, None)
            if record is not None:
                name, started = record
                self.records.append({"name": name, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3)})
                if _DIAGNOSTIC_STATE.get("active_function") == name:
                    _DIAGNOSTIC_STATE["active_function"] = None
                _write_diagnostic_state()
        return self


def _shape_complexity(value):
    try:
        shape = value.val() if hasattr(value, "val") else value
        return {
            "face_count": len(shape.Faces()) if hasattr(shape, "Faces") else None,
            "edge_count": len(shape.Edges()) if hasattr(shape, "Edges") else None,
            "solid_count": len(shape.Solids()) if hasattr(shape, "Solids") else None,
            "valid": bool(shape.isValid()) if hasattr(shape, "isValid") else None,
        }
    except Exception:
        return {"face_count": None, "edge_count": None, "solid_count": None, "valid": None}


def _shape_summary(value):
    # Return a compact, deterministic identity for one provider shape.
    try:
        shape = value.val() if hasattr(value, "val") else value
        if shape is None:
            return None
        bounds = shape.BoundingBox() if hasattr(shape, "BoundingBox") else None
        summary = {
            "solid_count": len(shape.Solids()) if hasattr(shape, "Solids") else None,
            "volume": round(float(shape.Volume()), 6) if hasattr(shape, "Volume") else None,
            "bounds": {
                "xmin": round(float(bounds.xmin), 6),
                "ymin": round(float(bounds.ymin), 6),
                "zmin": round(float(bounds.zmin), 6),
                "xmax": round(float(bounds.xmax), 6),
                "ymax": round(float(bounds.ymax), 6),
                "zmax": round(float(bounds.zmax), 6),
            } if bounds is not None else None,
            "face_count": len(shape.Faces()) if hasattr(shape, "Faces") else None,
            "edge_count": len(shape.Edges()) if hasattr(shape, "Edges") else None,
            "valid": bool(shape.isValid()) if hasattr(shape, "isValid") else None,
        }
        encoded = json.dumps(summary, sort_keys=True, separators=(",", ":"))
        summary["shape_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return summary
    except Exception:
        return None


def _shape_argument(args):
    for value in args:
        if hasattr(value, "val") or hasattr(value, "Solids"):
            return value
    return None


def _feature_operation_category(operation_names, *, shape_changed):
    if not shape_changed:
        return "no_effect"
    names = set(operation_names)
    if names & {"cut", "cutBlind", "cutThruAll", "hole", "shell"}:
        return "subtractive"
    if names & {"union", "extrude", "box", "cylinder", "loft"}:
        return "additive"
    if names & {"translate", "rotate", "mirror"}:
        return "transform"
    if names & {"fillet", "chamfer"}:
        return "finishing"
    return "unknown"


def _wrap_provider_feature_functions(module):
    # Wrap provider-owned component/feature functions without product knowledge.
    for name, function in list(vars(module).items()):
        if not callable(function) or not name.startswith("_ai_"):
            continue

        def traced(*args, _name=name, _function=function, **kwargs):
            started = time.perf_counter()
            input_shape = _shape_summary(_shape_argument(args))
            operation_start = len(_TIMING["operations"])
            record = {
                "feature_id": _name.removeprefix("_ai_feature_"),
                "source_function_id": _name,
                "source_executed": False,
                "input": input_shape,
                "input_shape_hash": input_shape.get("shape_hash") if input_shape else None,
                "output": None,
                "output_shape_hash": None,
                "shape_changed": False,
                "operation_category": "unknown",
                "operation_names": [],
                "elapsed_ms": None,
                "error": None,
            }
            try:
                output = _function(*args, **kwargs)
                output_shape = _shape_summary(output)
                record["source_executed"] = True
                record["output"] = output_shape
                record["output_shape_hash"] = output_shape.get("shape_hash") if output_shape else None
                record["shape_changed"] = bool(
                    record["input_shape_hash"] != record["output_shape_hash"]
                    if record["input_shape_hash"] is not None and record["output_shape_hash"] is not None
                    else output_shape is not None
                )
                record["operation_names"] = [
                    item.get("name")
                    for item in _TIMING["operations"][operation_start:]
                    if isinstance(item, dict) and item.get("name")
                ]
                record["operation_category"] = _feature_operation_category(
                    record["operation_names"], shape_changed=record["shape_changed"]
                )
                return output
            except Exception as exc:
                record["error"] = type(exc).__name__
                raise
            finally:
                record["source_executed"] = bool(record["source_executed"])
                record["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
                _FEATURE_TRACE.append(record)

        setattr(module, name, traced)


def _install_operation_timing():
    originals = {}
    operation_names = ("box", "circle", "cylinder", "extrude", "sweep", "slot2D", "spline", "cut", "cutBlind", "cutThruAll", "union", "intersect", "fillet", "chamfer", "loft", "shell", "hole", "mirror", "rotate", "translate")
    for name in operation_names:
        original = getattr(cq.Workplane, name, None)
        if not callable(original):
            continue
        originals[name] = original
        def timed(self, *args, _name=name, _original=original, **kwargs):
            global _ACTIVE_OPERATION
            started = time.perf_counter()
            before = _shape_complexity(self) if _name in _COUNTED_OPERATION_NAMES else None
            _ACTIVE_OPERATION = {
                "name": _name,
                "before": before,
                "started_at_monotonic": started,
            }
            _DIAGNOSTIC_STATE["active_operation"] = _ACTIVE_OPERATION
            _DIAGNOSTIC_STATE["operation_started_at_monotonic"] = started
            _DIAGNOSTIC_STATE["last_started_incomplete_operation"] = _ACTIVE_OPERATION
            _write_diagnostic_state()
            try:
                result = _original(self, *args, **kwargs)
                after = _shape_complexity(result) if _name in _COUNTED_OPERATION_NAMES else None
                return result
            except Exception as exc:
                _record_failure(exc)
                raise
            finally:
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                completed = {
                    "name": _name,
                    "elapsed_ms": elapsed_ms,
                    "before": before,
                    "after": locals().get("after"),
                }
                _ACTIVE_OPERATION = None
                _DIAGNOSTIC_STATE["active_operation"] = None
                _DIAGNOSTIC_STATE["operation_started_at_monotonic"] = None
                _DIAGNOSTIC_STATE["last_completed_operation"] = completed
                _TIMING["operations"].append(completed)
                _write_diagnostic_state()
        setattr(cq.Workplane, name, timed)
    return originals


def _restore_operation_timing(originals):
    for name, original in originals.items():
        setattr(cq.Workplane, name, original)


def _write_partial_result(reason):
    if _RESULT_PATH is None:
        return
    try:
        _write_diagnostic_state()
        _RESULT_PATH.write_text(json.dumps({
            "cad_backend": "cadquery",
            "cadquery_version": getattr(cq, "__version__", "unknown"),
            "source_language": "python",
            "source_contract_version": "cadquery-v1",
            "success": False,
            "failure_class": "timeout",
            "diagnostics": {"message": reason, "operation_active": _ACTIVE_OPERATION},
            "diagnostic_state": _DIAGNOSTIC_STATE,
            "execution_timing": {
                **_TIMING,
                "total_ms": round((time.perf_counter() - _STARTED_AT) * 1000, 3) if _STARTED_AT else None,
            },
            "outputs": [
                {
                    "output_id": output_id,
                    "entrypoint": output_id,
                    "required": bool(record.get("required", True)) if isinstance(record, dict) else True,
                    "success": False,
                    "compile_error": "output did not complete before timeout",
                }
                for output_id, record in _DIAGNOSTIC_STATE.get("per_output_results", {}).items()
                if isinstance(record, dict) and record.get("status") != "completed"
            ],
            "worker_version": "cadquery-cli-runner-v1",
        }, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def _handle_term(_signum, _frame):
    _write_partial_result("CAD worker terminated while execution timing was being collected")
    raise SystemExit(143)


def main() -> int:
    global cq, ParameterValues, Product, _RESULT_PATH, _DIAGNOSTIC_STATE_PATH, _STARTED_AT
    started_at = time.perf_counter()
    _STARTED_AT = started_at
    output_dir = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    _RESULT_PATH = result_path
    _DIAGNOSTIC_STATE_PATH = result_path.with_name("diagnostic-state.json")
    signal.signal(signal.SIGTERM, _handle_term)
    parameter_values_path = Path(sys.argv[3])
    requested_outputs_path = Path(sys.argv[4])
    output_dir.mkdir(parents=True, exist_ok=True)
    parameter_values = json.loads(parameter_values_path.read_text(encoding="utf-8"))
    requested_outputs = json.loads(requested_outputs_path.read_text(encoding="utf-8"))
    source_path = Path("model.py")
    _initialize_diagnostic_state(source_path, requested_outputs)
    _set_phase("source_validation")
    _validate_source_contract(source_path)
    _complete_phase("source_validation")
    _set_phase("module_import")
    spec = importlib.util.spec_from_file_location("volundr_generated_model", source_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load generated model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _complete_phase("module_import")
    import cadquery as cadquery_module
    from volundr_cad.runtime import ParameterValues as parameter_values_cls, Product as product_cls
    cq = cadquery_module
    ParameterValues = parameter_values_cls
    Product = product_cls
    _DIAGNOSTIC_STATE["cadquery_version"] = getattr(cq, "__version__", "unknown")
    _DIAGNOSTIC_STATE["cadquery_worker_version"] = "cadquery-cli-runner-v1"
    _write_diagnostic_state()

    if not hasattr(module, "build"):
        raise RuntimeError("generated source must define build(params)")
    originals = _install_operation_timing()
    _wrap_provider_feature_functions(module)
    profiler = _FunctionProfiler()
    sys.setprofile(profiler)
    try:
        _set_phase("build_function")
        product = _build_product(module, parameter_values)
        _complete_phase("build_function")
        _set_phase("output_materialization")
        outputs = _execute_product_outputs(product, requested_outputs, output_dir)
        _complete_phase("output_materialization")
    except Exception as exc:
        _record_failure(exc)
        raise
    finally:
        sys.setprofile(None)
        _restore_operation_timing(originals)
    _TIMING["functions"] = profiler.records
    _TIMING["outputs"] = {
        output.get("output_id"): output.get("timing", {})
        for output in outputs
        if output.get("output_id")
    }

    result_path.write_text(
        json.dumps(
            {
                "cad_backend": "cadquery",
                "cadquery_version": getattr(cq, "__version__", "unknown"),
                "source_language": "python",
                "source_contract_version": "cadquery-v1",
                "source_hash": _file_sha256(Path("model.py")),
                "parameter_hash": _json_sha256(parameter_values),
                "parameters": parameter_values,
                "requested_output_ids": [
                    str(request.get("output_id") or "")
                    for request in requested_outputs
                ] if requested_outputs else [output.output_id for output in product.outputs],
                "output_ids": [
                    output["output_id"]
                    for output in outputs
                    if output.get("success")
                ],
                "execution_timing": {
                    "total_ms": round((time.perf_counter() - started_at) * 1000, 3),
                    "functions": _TIMING["functions"],
                    "operations": _TIMING["operations"],
                    "outputs": _TIMING["outputs"],
                },
                "feature_trace": _FEATURE_TRACE,
                "feature_trace_supported": True,
                "diagnostic_state": _DIAGNOSTIC_STATE,
                "outputs": outputs,
                "worker_version": "cadquery-cli-runner-v1",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


def _validate_source_contract(source_path):
    source = source_path.read_text(encoding="utf-8")
    try:
        validate_cadquery_source(source, contract_version="cadquery-v1")
    except CadQueryContractError as exc:
        raise RuntimeError(f"CadQuery contract violation: {exc}") from exc


def _build_product(module, parameter_values):
    specs = getattr(module, "PARAMETERS", ())
    params = ParameterValues.from_specs(specs, parameter_values)
    product = module.build(params)
    if not isinstance(product, Product):
        raise RuntimeError("build(params) must return Product")
    return product


def _execute_product_outputs(product, requested_outputs, output_dir):
    by_id = {output.output_id: output for output in product.outputs}
    requests = requested_outputs or [{"output_id": output.output_id, "required": output.required} for output in product.outputs]
    _initialize_output_requests(requests)
    results = []
    for request in requests:
        output_id = str(request.get("output_id") or "")
        required = bool(request.get("required", True))
        printable = by_id.get(output_id)
        _set_output_status(output_id, "started", required=required)
        if printable is None:
            result = {
                "output_id": output_id,
                "entrypoint": output_id,
                "required": required,
                "success": False,
                "compile_error": f"requested output not found: {output_id}",
                "topology_metadata": _execution_failed_topology_metadata(
                    output_id=output_id,
                    expected_solid_count=int(request.get("expected_solid_count") or 1),
                    allow_disconnected_solids=bool(request.get("allow_disconnected_solids", False)),
                ),
            }
            results.append(result)
            _set_output_status(output_id, "not_found", required=required, compile_error=result["compile_error"])
            continue
        started = time.perf_counter()
        result = _export_printable_output(output_dir, printable, required=required)
        result["feature_trace"] = [
            {**trace, "output_id": output_id}
            for trace in _FEATURE_TRACE
        ]
        result["timing"] = {"export_ms": round((time.perf_counter() - started) * 1000, 3)}
        results.append(result)
        _set_output_status(
            output_id,
            _output_status(result),
            required=required,
            compile_error=result.get("compile_error"),
            timing=result.get("timing"),
        )
    return results


def _export_printable_output(output_dir, printable, *, required):
    return _export_output(
        output_dir=output_dir,
        output_id=printable.output_id,
        entrypoint=printable.output_id,
        required=required,
        model=printable.model,
        expected_solid_count=printable.expected_solid_count,
        allow_disconnected_solids=printable.allow_disconnected_solids,
    )


def _export_output(
    *,
    output_dir,
    output_id,
    entrypoint,
    required,
    model,
    expected_solid_count,
    allow_disconnected_solids,
):
    if model is None:
        return _failed_output(
            output_id,
            entrypoint,
            required,
            "output model is None",
            topology_metadata=_empty_topology_metadata(
                output_id=output_id,
                expected_solid_count=expected_solid_count,
                allow_disconnected_solids=allow_disconnected_solids,
            ),
        )
    safe_id = _safe_stem(output_id)
    artifact_dir = output_dir / safe_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stl_path = artifact_dir / f"{safe_id}.stl"
    step_path = artifact_dir / f"{safe_id}.step"
    brep_path = artifact_dir / f"{safe_id}.brep"
    try:
        _set_phase("topology_analysis")
        model_space_topology = _topology_metadata(
            output_id=output_id,
            model=model,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
        if not model_space_topology["valid"]:
            return _failed_output(
                output_id,
                entrypoint,
                required,
                "output shape is invalid",
                topology_metadata=model_space_topology,
            )
        placement = _print_placement_metadata(model_space_topology.get("bounding_box_mm"))
        print_model = _apply_print_transform(model, placement["print_transform"])
        topology_metadata = _topology_metadata(
            output_id=output_id,
            model=print_model,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
        topology_metadata.update(placement)
        topology_metadata["coordinate_space"] = "print_space"
        topology_metadata["print_space_bounds"] = topology_metadata.get("bounding_box_mm")
        if not topology_metadata["valid"]:
            return _failed_output(
                output_id,
                entrypoint,
                required,
                "print-placed output shape is invalid",
                topology_metadata=topology_metadata,
            )
        export_timings = {}
        _set_export(output_id, "STL")
        started = time.perf_counter()
        cq.exporters.export(print_model, str(stl_path))
        export_timings["stl_export_ms"] = round((time.perf_counter() - started) * 1000, 3)
        _clear_export()
        _set_export(output_id, "STEP")
        started = time.perf_counter()
        cq.exporters.export(print_model, str(step_path))
        export_timings["step_export_ms"] = round((time.perf_counter() - started) * 1000, 3)
        _clear_export()
        try:
            _set_export(output_id, "BREP")
            started = time.perf_counter()
            cq.exporters.export(print_model, str(brep_path))
            export_timings["brep_export_ms"] = round((time.perf_counter() - started) * 1000, 3)
        except Exception:
            brep_path.unlink(missing_ok=True)
        finally:
            _clear_export()
        _set_phase("metadata_generation")
        return {
            "output_id": output_id,
            "entrypoint": entrypoint,
            "required": required,
            "success": True,
            "stl_path": str(stl_path),
            "step_path": str(step_path),
            "brep_path": str(brep_path) if brep_path.exists() else None,
            "stl_hash": _file_sha256(stl_path),
            "step_hash": _file_sha256(step_path),
            "brep_hash": _file_sha256(brep_path) if brep_path.exists() else None,
            "topology_metadata": topology_metadata,
            "export_timings": export_timings,
        }
    except Exception as exc:
        return _failed_output(
            output_id,
            entrypoint,
            required,
            str(exc),
            topology_metadata=_execution_failed_topology_metadata(
                output_id=output_id,
                expected_solid_count=expected_solid_count,
                allow_disconnected_solids=allow_disconnected_solids,
            ),
        )


def _print_placement_metadata(model_space_bounds):
    z_min = None
    if isinstance(model_space_bounds, dict):
        z_min = model_space_bounds.get("z_min")
    dz = 0.0
    if isinstance(z_min, (int, float)) and z_min < -PLACEMENT_TOLERANCE_MM:
        dz = round(float(-z_min), 6)
    return {
        "placement_policy": PLACEMENT_POLICY,
        "model_space_bounds": model_space_bounds,
        "print_transform": {
            "translation": [0.0, 0.0, dz],
            "rotation": [0.0, 0.0, 0.0],
        },
    }


def _apply_print_transform(model, print_transform):
    translation = print_transform.get("translation") if isinstance(print_transform, dict) else None
    if not isinstance(translation, list) or len(translation) != 3:
        return model
    if all(abs(float(value)) <= PLACEMENT_TOLERANCE_MM for value in translation):
        return model
    if not hasattr(model, "translate"):
        raise RuntimeError("output cannot be translated into print space")
    return model.translate(tuple(float(value) for value in translation))


def _failed_output(output_id, entrypoint, required, message, topology_metadata=None):
    return {
        "output_id": output_id,
        "entrypoint": entrypoint,
        "required": required,
        "success": False,
        "compile_error": message,
        "topology_metadata": topology_metadata,
    }


def _topology_metadata(
    *,
    output_id,
    model,
    expected_solid_count,
    allow_disconnected_solids,
):
    shape = _shape_for(model)
    if shape is None:
        return _empty_topology_metadata(
            output_id=output_id,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
    if not _is_supported_shape_data(model, shape):
        return _unsupported_shape_topology_metadata(
            output_id=output_id,
            expected_solid_count=expected_solid_count,
            allow_disconnected_solids=allow_disconnected_solids,
        )
    evidence = collect_topology_evidence(
        model,
        expected_solid_count=expected_solid_count,
        allow_disconnected_solids=allow_disconnected_solids,
    )
    evidence["output_id"] = output_id
    return evidence


def _unsupported_shape_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    evidence = collect_topology_evidence(
        None,
        expected_solid_count=expected_solid_count,
        allow_disconnected_solids=allow_disconnected_solids,
    )
    evidence.update({
        "output_id": output_id,
        "outcome": "unsupported_shape",
    })
    return evidence


def _execution_failed_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    evidence = collect_topology_evidence(
        None,
        expected_solid_count=expected_solid_count,
        allow_disconnected_solids=allow_disconnected_solids,
    )
    evidence.update({
        "output_id": output_id,
        "outcome": "execution_failed",
    })
    return evidence


def _empty_topology_metadata(*, output_id, expected_solid_count, allow_disconnected_solids):
    evidence = collect_topology_evidence(
        None,
        expected_solid_count=expected_solid_count,
        allow_disconnected_solids=allow_disconnected_solids,
    )
    evidence.update({
        "output_id": output_id,
        "outcome": "empty",
        "volume_mm3": 0,
        "shell_count": 0,
    })
    return evidence


def _shape_for(model):
    if hasattr(model, "val"):
        try:
            return model.val()
        except Exception:
            return None
    return model


def _is_supported_shape_data(model, shape):
    supported_attributes = ("isValid", "Volume", "Solids")
    return (
        hasattr(model, "val")
        or hasattr(model, "solids")
        or any(hasattr(shape, attribute) for attribute in supported_attributes)
    )


def _solid_count(model, shape):
    if hasattr(model, "solids"):
        try:
            solids = model.solids()
            if hasattr(solids, "size"):
                return int(solids.size())
        except Exception:
            pass
    if hasattr(shape, "Solids"):
        try:
            return len(shape.Solids())
        except Exception:
            pass
    return 1


def _shell_count(model, shape):
    if hasattr(model, "shells"):
        try:
            shells = model.shells()
            if hasattr(shells, "size"):
                return int(shells.size())
        except Exception:
            pass
    if hasattr(shape, "Shells"):
        try:
            return len(shape.Shells())
        except Exception:
            pass
    return None


def _bounding_box_metadata(shape):
    if not hasattr(shape, "BoundingBox"):
        return None
    try:
        bounding_box = shape.BoundingBox()
    except Exception:
        return None
    return {
        "x_min": _numeric_attr(bounding_box, "xmin"),
        "x_max": _numeric_attr(bounding_box, "xmax"),
        "y_min": _numeric_attr(bounding_box, "ymin"),
        "y_max": _numeric_attr(bounding_box, "ymax"),
        "z_min": _numeric_attr(bounding_box, "zmin"),
        "z_max": _numeric_attr(bounding_box, "zmax"),
        "size_x": _numeric_attr(bounding_box, "xlen"),
        "size_y": _numeric_attr(bounding_box, "ylen"),
        "size_z": _numeric_attr(bounding_box, "zlen"),
    }


def _numeric_attr(value, name):
    attribute = getattr(value, name, None)
    if callable(attribute):
        attribute = attribute()
    if isinstance(attribute, (int, float)):
        return float(attribute)
    return None


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_stem(value):
    return "".join(character if character.isalnum() or character in "._-" else "-" for character in value).strip(".-") or "output"


if __name__ == "__main__":
    raise SystemExit(main())
"""
