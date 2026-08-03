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
    build_identities: dict[str, dict[str, Any]]
    identity_complete: bool
    provider: str
    configured_default_model: str
    stage_model_policy: dict[str, Any]
    actual_provider_models: dict[str, Any]
    prompt_versions: dict[str, str]
    configuration_hash: str


def _git_command(data_dir: Path, *args: str) -> str | None:
    cwd = data_dir.parent if data_dir.name == "data" else Path.cwd()
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, check=False, capture_output=True, text=True, timeout=1
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def _git_value(data_dir: Path, *args: str) -> str:
    if args == ("rev-parse", "HEAD"):
        configured = getattr(settings, "build_git_sha", None)
    else:
        configured = getattr(settings, "build_branch", None)
    return str(configured or _git_command(data_dir, *args) or "unknown")


def _git_dirty(data_dir: Path) -> bool | None:
    configured = getattr(settings, "build_dirty", None)
    if configured is not None:
        return bool(configured)
    status = _git_command(data_dir, "status", "--porcelain")
    if status is None:
        return None
    return bool(status)


def _git_timestamp(data_dir: Path) -> str | None:
    configured = getattr(settings, "build_timestamp", None)
    if configured:
        return str(configured)
    return _git_command(data_dir, "show", "-s", "--format=%cI", "HEAD")


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


def _frontend_identity(value: str, *, default_timestamp: str | None, default_dirty: bool | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    git_sha = str(parsed.get("git_sha") or "unknown")
    if git_sha == "unknown" and value and value not in {"frontend-dev", "unknown"}:
        candidate = value.strip()
        if len(candidate) >= 7 and all(character in "0123456789abcdefABCDEF" for character in candidate):
            git_sha = candidate
    identity_label = parsed.get("identity")
    if not isinstance(identity_label, str) or not identity_label.isprintable() or len(identity_label) > 160:
        identity_label = "provided"
    return {
        "component": "frontend",
        "git_sha": git_sha,
        "dirty": parsed.get("dirty", default_dirty),
        "build_timestamp": parsed.get("build_timestamp") or default_timestamp,
        "release_label": parsed.get("release_label"),
        "identity": identity_label,
    }


def _component_identity(
    component: str,
    *,
    git_sha: str,
    dirty: bool | None,
    build_timestamp: str | None,
    branch: str,
    application_version: str,
) -> dict[str, Any]:
    return {
        "component": component,
        "git_sha": git_sha,
        "dirty": dirty,
        "build_timestamp": build_timestamp,
        "branch": branch,
        "application_version": application_version,
        "release_label": getattr(settings, "build_release_label", None),
    }


def _identity_is_complete(identity: dict[str, Any]) -> bool:
    return (
        identity.get("git_sha") not in {None, "", "unknown"}
        and identity.get("dirty") is not None
        and identity.get("build_timestamp") not in {None, "", "unknown"}
    )


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
    branch = _git_value(data_dir, "branch", "--show-current")
    dirty = _git_dirty(data_dir)
    build_timestamp = _git_timestamp(data_dir)
    application_version = _application_version()
    backend = _component_identity(
        "backend",
        git_sha=git_head,
        dirty=dirty,
        build_timestamp=build_timestamp,
        branch=branch,
        application_version=application_version,
    )
    frontend = _frontend_identity(
        frontend_build_identity,
        default_timestamp=build_timestamp,
        default_dirty=dirty,
    )
    worker = _component_identity(
        "worker",
        git_sha=str(getattr(settings, "worker_build_git_sha", None) or git_head),
        dirty=getattr(settings, "worker_build_dirty", None) if getattr(settings, "worker_build_dirty", None) is not None else dirty,
        build_timestamp=str(getattr(settings, "worker_build_timestamp", None) or build_timestamp or "") or None,
        branch=branch,
        application_version="cad-worker-v1",
    )
    build_identities = {"backend": backend, "frontend": frontend, "worker": worker}
    identity_complete = all(_identity_is_complete(identity) for identity in build_identities.values())

    safe_frontend_identity = json.dumps(frontend, sort_keys=True)
    return BatchIdentity(
        git_head=git_head,
        branch=branch,
        migration_head=_migration_head(db),
        application_version=application_version,
        frontend_build_identity=safe_frontend_identity,
        backend_build_identity=json.dumps(backend, sort_keys=True),
        worker_build_identity=json.dumps(worker, sort_keys=True),
        build_identities=build_identities,
        identity_complete=identity_complete,
        provider=settings.ai_provider,
        configured_default_model=policy.general_model,
        stage_model_policy=stage_model_policy,
        actual_provider_models={},
        prompt_versions=prompt_versions,
        configuration_hash=configuration_hash,
    )


def identity_payload(identity: BatchIdentity) -> dict[str, Any]:
    return asdict(identity)
