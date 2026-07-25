import logging
import time

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("volundr.cad_worker")


def main() -> None:
    settings.cad_workspace_dir.mkdir(parents=True, exist_ok=True)
    logger.info("CAD worker ready; workspace=%s", settings.cad_workspace_dir)
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
