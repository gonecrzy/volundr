import asyncio
import hashlib
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
        )

    def _compile_result_from_worker_payload(
        self,
        *,
        job_dir: Path,
        source_hash: str,
        payload: dict[str, Any],
    ) -> CadQueryCompileResult:
        diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
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
            stdout_path=None,
            stderr_path=None,
            metadata_path=primary_output.metadata_path if primary_output is not None else None,
            source_hash=source_hash,
            output_size_bytes=sum(output.output_size_bytes for output in successful_outputs),
            metadata=primary_output.metadata if primary_output is not None else None,
            error_message=diagnostics.get("message") if isinstance(diagnostics.get("message"), str) else None,
            command_args=diagnostics.get("command_args")
            if isinstance(diagnostics.get("command_args"), list)
            else None,
            outputs=outputs,
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
