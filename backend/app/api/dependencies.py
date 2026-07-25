from pathlib import Path

from app.core.config import settings
from app.services.cad.runner import OpenScadCliRunner


def get_data_dir() -> Path:
    return settings.data_dir


def get_cad_runner() -> OpenScadCliRunner:
    return OpenScadCliRunner()
