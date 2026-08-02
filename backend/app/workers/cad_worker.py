import logging
import time
import asyncio
import json
import os
from pathlib import Path

from app.core.config import settings
from app.services.cad.worker_execution import process_next_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("volundr.cad_worker")


def worker_health_path(_workspace: Path) -> Path:
    """Return a writable heartbeat path without requiring shared-dir ownership."""
    return Path(os.environ.get("VOLUNDR_WORKER_HEALTH_PATH", "/tmp/.worker-health.json"))


def main() -> None:
    settings.cad_workspace_dir.mkdir(parents=True, exist_ok=True)
    health_path = worker_health_path(settings.cad_workspace_dir)
    health_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("CAD worker ready; workspace=%s", settings.cad_workspace_dir)
    while True:
        health_path.write_text(
            json.dumps({"status": "ready", "updated_at": time.time()}),
            encoding="utf-8",
        )
        result = asyncio.run(process_next_job(settings.cad_workspace_dir))
        if result is None:
            time.sleep(1)
            continue
        logger.info(
            "CAD job finished; job_id=%s success=%s failure_class=%s",
            result["job_id"],
            result["success"],
            result["failure_class"],
        )


if __name__ == "__main__":
    main()
