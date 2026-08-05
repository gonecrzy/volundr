import asyncio
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from app.core.config import settings
from app.services.cad.cadquery_runner import (
    CadQueryCompileResult,
    CadQueryOutputResult,
)
from app.services.cad.jobs import FilesystemCadJobQueue, load_job_result
from app.services.mesh.inspect import inspect_stl


class FilesystemCadWorkerClient:
    def __init__(self, jobs_root: Path | None = None) -> None:
        self.jobs_root = jobs_root or settings.cad_workspace_dir
        self.queue = FilesystemCadJobQueue(self.jobs_root)

    def submit_cadquery_execution(
        self,
        *,
        source: str,
        job_id: str,
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
        timeout_seconds: int = 60,
    ) -> Path:
        return self.queue.submit_cadquery_source(
            source=source,
            job_id=job_id,
            parameter_values=parameter_values,
            requested_outputs=requested_outputs,
            timeout_seconds=timeout_seconds,
        )

    def read_result(self, job_id: str) -> dict[str, Any] | None:
        job_dir = self.jobs_root / job_id
        result_path = job_dir / "result.json"
        if not result_path.exists():
            return None
        return load_job_result(job_dir)


class FilesystemCadWorkerRunner:
    def __init__(
        self,
        jobs_root: Path | None = None,
        *,
        poll_interval_seconds: float = 0.1,
        result_timeout_seconds: float | None = None,
    ) -> None:
        self.jobs_root = jobs_root or settings.cad_workspace_dir
        self.client = FilesystemCadWorkerClient(self.jobs_root)
        self.poll_interval_seconds = poll_interval_seconds
        self.result_timeout_seconds = result_timeout_seconds or (settings.cad_timeout_seconds + 30)

    async def compile(
        self,
        source: str,
        job_id: str,
        *,
        source_contract_version: str = "cadquery-v1",
        parameter_values: dict[str, Any] | None = None,
        requested_outputs: list[dict[str, Any]] | None = None,
    ) -> CadQueryCompileResult:
        source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if source_contract_version != "cadquery-v1":
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
                error_message="unsupported CadQuery source_contract_version",
                command_args=None,
                outputs=[],
            )
        job_dir = self.client.submit_cadquery_execution(
            source=source,
            job_id=job_id,
            parameter_values=parameter_values,
            requested_outputs=requested_outputs,
            timeout_seconds=settings.cad_timeout_seconds,
        )
        deadline = time.monotonic() + self.result_timeout_seconds
        while time.monotonic() < deadline:
            result = self.client.read_result(job_id)
            if result is not None:
                return self._compile_result_from_worker_payload(
                    job_dir=job_dir,
                    source_hash=source_hash,
                    payload=result,
                )
            await asyncio.sleep(self.poll_interval_seconds)
        diagnostics = self._client_timeout_diagnostics(
            job_dir=job_dir,
            source_hash=source_hash,
        )
        return CadQueryCompileResult(
            job_id=job_id,
            success=False,
            timed_out=True,
            exit_code=None,
            source_path=job_dir / "input" / "model.py",
            stl_path=None,
            step_path=None,
            stdout_path=None,
            stderr_path=None,
            metadata_path=None,
            source_hash=source_hash,
            output_size_bytes=0,
            metadata=None,
            error_message=(
                "CAD worker did not complete job within "
                f"{self.result_timeout_seconds:g} seconds"
            ),
            command_args=None,
            outputs=[],
            execution_diagnostics=diagnostics,
        )

    def _compile_result_from_worker_payload(
        self,
        *,
        job_dir: Path,
        source_hash: str,
        payload: dict[str, Any],
    ) -> CadQueryCompileResult:
        diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
        stdout_path = self._job_relative_path(job_dir, diagnostics.get("partial_stdout_path"))
        stderr_path = self._job_relative_path(job_dir, diagnostics.get("partial_stderr_path"))
        outputs = [
            self._output_result_from_worker_payload(job_dir, raw_output)
            for raw_output in payload.get("outputs", [])
            if isinstance(raw_output, dict)
        ]
        successful_outputs = [output for output in outputs if output.success]
        primary_output = successful_outputs[0] if successful_outputs else None
        return CadQueryCompileResult(
            job_id=str(payload.get("job_id") or job_dir.name),
            success=bool(payload.get("success")),
            timed_out=payload.get("failure_class") == "timeout",
            exit_code=diagnostics.get("exit_code") if isinstance(diagnostics.get("exit_code"), int) else None,
            source_path=job_dir / "input" / "model.py",
            stl_path=primary_output.stl_path if primary_output is not None else None,
            step_path=primary_output.step_path if primary_output is not None else None,
            stdout_path=stdout_path if stdout_path is not None and stdout_path.exists() else None,
            stderr_path=stderr_path if stderr_path is not None and stderr_path.exists() else None,
            metadata_path=primary_output.metadata_path if primary_output is not None else None,
            source_hash=source_hash,
            output_size_bytes=sum(output.output_size_bytes for output in successful_outputs),
            metadata=primary_output.metadata if primary_output is not None else None,
            error_message=diagnostics.get("message") if isinstance(diagnostics.get("message"), str) else None,
            command_args=diagnostics.get("command_args")
            if isinstance(diagnostics.get("command_args"), list)
            else None,
            outputs=outputs,
            execution_manifest_path=job_dir / "result.json",
            execution_diagnostics=diagnostics,
        )

    def _output_result_from_worker_payload(
        self,
        job_dir: Path,
        payload: dict[str, Any],
    ) -> CadQueryOutputResult:
        stl_path = self._job_relative_path(job_dir, payload.get("stl_path"))
        step_path = self._job_relative_path(job_dir, payload.get("step_path"))
        brep_path = self._job_relative_path(job_dir, payload.get("brep_path"))
        metadata_path = self._job_relative_path(job_dir, payload.get("metadata_path"))
        topology_metadata_path = self._job_relative_path(job_dir, payload.get("topology_metadata_path"))
        metadata = None
        if stl_path is not None and stl_path.exists() and payload.get("success"):
            try:
                metadata = inspect_stl(stl_path)
            except ValueError:
                metadata = None
        return CadQueryOutputResult(
            output_id=str(payload.get("output_id") or "model"),
            entrypoint=str(payload.get("entrypoint") or payload.get("output_id") or "model"),
            required=bool(payload.get("required", True)),
            success=bool(payload.get("success")),
            stl_path=stl_path if stl_path is not None and stl_path.exists() else None,
            step_path=step_path if step_path is not None and step_path.exists() else None,
            brep_path=brep_path if brep_path is not None and brep_path.exists() else None,
            metadata_path=metadata_path if metadata_path is not None and metadata_path.exists() else None,
            topology_metadata_path=topology_metadata_path
            if topology_metadata_path is not None and topology_metadata_path.exists()
            else None,
            stl_hash=payload.get("stl_hash") if isinstance(payload.get("stl_hash"), str) else None,
            step_hash=payload.get("step_hash") if isinstance(payload.get("step_hash"), str) else None,
            brep_hash=payload.get("brep_hash") if isinstance(payload.get("brep_hash"), str) else None,
            output_size_bytes=int(payload.get("stl_size_bytes") or 0),
            metadata=metadata,
            topology_metadata=payload.get("topology_metadata")
            if isinstance(payload.get("topology_metadata"), dict)
            else None,
            compile_error=payload.get("compile_error") if isinstance(payload.get("compile_error"), str) else None,
        )

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

    def _client_timeout_diagnostics(
        self,
        *,
        job_dir: Path,
        source_hash: str,
    ) -> dict[str, Any]:
        inner_job_dir = job_dir / "work" / job_dir.name
        state_path = inner_job_dir / "diagnostic-state.json"
        state = self._read_json(state_path)
        if not isinstance(state, dict):
            state = {}
        per_output = state.get("per_output_results") if isinstance(state.get("per_output_results"), dict) else {}
        completed_output_ids = [
            str(output_id)
            for output_id, result in per_output.items()
            if isinstance(result, dict) and result.get("status") == "completed"
        ]
        incomplete_output_ids = [
            str(output_id)
            for output_id, result in per_output.items()
            if isinstance(result, dict) and result.get("status") != "completed"
        ]
        diagnostics: dict[str, Any] = {
            "timed_out": True,
            "timeout_seconds": settings.cad_timeout_seconds,
            "worker_result_timeout_seconds": self.result_timeout_seconds,
            "source_hash": source_hash,
            "active_phase": state.get("active_phase"),
            "active_output_id": state.get("active_output_id"),
            "active_function": state.get("active_function"),
            "active_operation": state.get("active_operation"),
            "active_export_format": state.get("active_export_format"),
            "operation_started_at_monotonic": state.get("operation_started_at_monotonic"),
            "last_completed_operation": state.get("last_completed_operation"),
            "last_started_incomplete_operation": state.get("last_started_incomplete_operation"),
            "completed_output_ids": completed_output_ids,
            "incomplete_output_ids": incomplete_output_ids,
            "per_output_results": per_output,
            "partial_timing_record_path": self._relative_path(job_dir, state_path),
            "partial_diagnostic_state_path": self._relative_path(job_dir, state_path),
            "partial_stdout_path": self._relative_path(job_dir, inner_job_dir / "stdout.log"),
            "partial_stderr_path": self._relative_path(job_dir, inner_job_dir / "stderr.log"),
            "process_rss_kb": state.get("process_rss_kb"),
        }
        return {key: value for key, value in diagnostics.items() if value is not None}

    def _read_json(self, path: Path) -> dict[str, Any] | None:
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
