from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


@dataclass(frozen=True)
class BatchIdentity:
    git_head: str
    branch: str
    migration_head: str
    application_version: str
    frontend_build_identity: str
    backend_build_identity: str
    worker_build_identity: str
    provider: str
    configured_default_model: str
    stage_model_policy: dict[str, Any]
    actual_provider_models: dict[str, Any]
    prompt_versions: dict[str, str]
    configuration_hash: str


def _git_value(data_dir: Path, *args: str) -> str:
    configured_name = "application_commit" if args == ("rev-parse", "HEAD") else "application_branch"
    configured = getattr(settings, configured_name, None)
    if configured:
        return str(configured)
    cwd = data_dir.parent if data_dir.name == "data" else Path.cwd()
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=1
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _migration_head(db: Session) -> str:
    try:
        value = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except Exception:  # pragma: no cover - fresh in-memory test databases
        value = None
    return str(value or "unknown")


def _application_version() -> str:
    try:
        return version("volundr-backend")
    except PackageNotFoundError:
        return "volundr-backend-0.1.0"


def capture_batch_identity(
    *, db: Session, data_dir: Path, frontend_build_identity: str
) -> BatchIdentity:
    from app.services.ai.model_policy import GeminiModelPolicy

    policy = GeminiModelPolicy.from_settings(settings)
    stage_model_policy = {
        "policy_version": policy.policy_version,
        "provider": policy.provider,
        "general_model": policy.general_model,
        "requirements_model": policy.requirements_model,
        "design_plan_model": policy.design_plan_model,
        "geometry_model": policy.geometry_model,
        "geometry_repair_model": policy.geometry_repair_model,
        "revision_planning_model": policy.revision_planning_model,
        "component_revision_model": policy.component_revision_model,
        "temperature": policy.temperature,
        "max_output_tokens": policy.max_output_tokens,
        "thinking_level": policy.thinking_level,
        "max_retries": policy.max_retries,
        "max_retry_sleep_seconds": policy.max_retry_sleep_seconds,
    }
    prompt_versions = {
        "requirements": "requirements-v4",
        "design_plan": "design-plan-v8",
        "compact_plan": "compact-cad-plan-v3",
        "cadquery": "cadquery-geometry-body-v10",
        "cadquery_repair": "cadquery-geometry-body-repair-v10",
        "revision_plan": "revision-planning-v1",
    }
    safe_configuration = {
        "provider": settings.ai_provider,
        "model_policy": stage_model_policy,
        "provider_timeout_seconds": settings.gemini_timeout_seconds,
        "cad_timeout_seconds": settings.cad_timeout_seconds,
        "workflow_stale_seconds": settings.workflow_stale_seconds,
        "snapshots_enabled": settings.snapshots_enabled,
        "snapshot_image_width": settings.snapshot_image_width,
        "snapshot_image_height": settings.snapshot_image_height,
        "prompt_versions": prompt_versions,
    }
    configuration_hash = hashlib.sha256(
        json.dumps(safe_configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    git_head = _git_value(data_dir, "rev-parse", "HEAD")
    return BatchIdentity(
        git_head=git_head,
        branch=_git_value(data_dir, "branch", "--show-current"),
        migration_head=_migration_head(db),
        application_version=_application_version(),
        frontend_build_identity=frontend_build_identity,
        backend_build_identity=getattr(settings, "application_commit", None) or git_head,
        worker_build_identity="cad-worker-v1",
        provider=settings.ai_provider,
        configured_default_model=policy.general_model,
        stage_model_policy=stage_model_policy,
        actual_provider_models={},
        prompt_versions=prompt_versions,
        configuration_hash=configuration_hash,
    )


def identity_payload(identity: BatchIdentity) -> dict[str, Any]:
    return asdict(identity)
