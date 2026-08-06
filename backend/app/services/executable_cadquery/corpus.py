"""Opt-in frozen-corpus contract loading for the executable-CadQuery study."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.executable_cadquery.contract import (
    validate_executable_cadquery_design_contract,
)


REPEATABILITY_CORPUS_SCHEMA_VERSION = "executable-cadquery-repeatability-corpus-v1"


def load_repeatability_contract(
    manifest_path: Path,
    *,
    prompt: str,
) -> tuple[str, dict[str, Any]]:
    """Load one contract only when its prompt exactly matches the manifest."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("repeatability corpus manifest could not be read") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != REPEATABILITY_CORPUS_SCHEMA_VERSION:
        raise ValueError("unsupported repeatability corpus manifest")
    projects = payload.get("projects")
    if not isinstance(projects, list):
        raise ValueError("repeatability corpus projects are required")
    matches = [
        project
        for project in projects
        if isinstance(project, Mapping) and project.get("prompt") == prompt
    ]
    if len(matches) != 1:
        raise ValueError("repeatability corpus prompt is not registered exactly once")
    project = matches[0]
    project_id = project.get("project_id")
    contract = project.get("contract")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("repeatability corpus project_id is required")
    if not isinstance(contract, Mapping):
        raise ValueError(f"repeatability corpus contract is missing for {project_id}")
    return project_id, validate_executable_cadquery_design_contract(deepcopy(dict(contract)))
