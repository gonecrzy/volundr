import logging
import time
import asyncio

from app.core.config import settings
from app.services.cad.worker_execution import process_next_job

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("volundr.cad_worker")


def main() -> None:
    settings.cad_workspace_dir.mkdir(parents=True, exist_ok=True)
    logger.info("CAD worker ready; workspace=%s", settings.cad_workspace_dir)
    while True:
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
