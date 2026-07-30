from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.cad.jobs import FilesystemCadJobQueue, load_job_result


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
