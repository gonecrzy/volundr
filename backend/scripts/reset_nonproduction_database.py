"""Guarded reset and migration workflow for one disposable Volundr database.

The command is intentionally SQLite-focused because the supported Volundr
Compose deployment uses one SQLite file under ``VOLUNDR_DATA_DIR``.  It does
not stop writers itself: the operator must stop the Compose API and worker,
after which the command proves that they are stopped before it can unlink the
database.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from typing import Callable, Iterator, Sequence
from urllib.parse import unquote, urlsplit


class ResetGuardError(RuntimeError):
    """Raised when a reset safety condition is not proven."""


@dataclass(frozen=True)
class ResetOptions:
    environment: str
    confirm_database: str
    data_dir: Path
    evidence_root: Path
    database_url: str | None = None
    allow_destructive_reset: bool = False
    dry_run: bool = True
    compose_project: str = "volundr"


@dataclass(frozen=True)
class WriterStatus:
    active_services: tuple[str, ...]
    open_handles: tuple[str, ...]
    shared_projects: tuple[str, ...]


WriterProbe = Callable[[ResetOptions], WriterStatus]
MigrationRunner = Callable[[ResetOptions, str], None]

_ALLOWED_ENVIRONMENTS = {"development", "test", "staging"}
_PRODUCTION_DENYLIST = {"prod", "production", "live", "primary"}
_ADMINISTRATIVE_DATABASES = {
    "main",
    "master",
    "model",
    "msdb",
    "postgres",
    "template0",
    "template1",
    "tempdb",
}


def database_url_for(data_dir: Path) -> str:
    """Return an absolute SQLite URL without relying on application imports."""

    return f"sqlite:///{(data_dir / 'app.db').resolve()}"


def parse_sqlite_database_url(database_url: str) -> Path:
    """Parse only an absolute SQLite target and reject ambiguous URLs."""

    parsed = urlsplit(database_url)
    if parsed.scheme.lower() != "sqlite" or parsed.netloc:
        raise ResetGuardError("only an absolute SQLite database target is supported")
    if parsed.query or parsed.fragment:
        raise ResetGuardError("SQLite query and fragment options are not permitted")
    raw_path = unquote(parsed.path)
    if not raw_path or raw_path in {":memory:", "/:memory:"}:
        raise ResetGuardError("an in-memory database is not a disposable target")
    if not database_url.lower().startswith("sqlite:////"):
        raise ResetGuardError("the SQLite database path must be absolute")
    target = Path(raw_path).resolve()
    if target.name in {"", ".", ".."}:
        raise ResetGuardError("the SQLite database name is missing")
    return target


def redact_database_url(database_url: str) -> str:
    """Render a database target without credentials, host paths, or query text."""

    parsed = urlsplit(database_url)
    name = Path(unquote(parsed.path)).name or "<unknown>"
    scheme = parsed.scheme.lower() or "unknown"
    return f"{scheme}:///<redacted>/{name}"


def database_path(options: ResetOptions) -> Path:
    return parse_sqlite_database_url(options.database_url or database_url_for(options.data_dir))


def validate_options(options: ResetOptions) -> Path:
    environment = options.environment.strip().lower()
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise ResetGuardError("environment must be explicitly non-production")
    if not options.confirm_database:
        raise ResetGuardError("the exact database name confirmation is required")
    if not options.data_dir.exists() or not options.data_dir.is_dir():
        raise ResetGuardError("the configured data root does not exist")
    if options.data_dir.is_symlink():
        raise ResetGuardError("the configured data root must not be a symlink")

    target = database_path(options)
    data_root = options.data_dir.resolve()
    if target.parent != data_root:
        raise ResetGuardError("the database target must be directly inside the configured data root")
    if target.name != options.confirm_database:
        raise ResetGuardError("the exact database name confirmation does not match the target")
    if target.name.lower() in _ADMINISTRATIVE_DATABASES:
        raise ResetGuardError("administrative/default database names are not resettable")
    if any(part.lower() in _PRODUCTION_DENYLIST for part in target.parts):
        raise ResetGuardError("the target is on the production denylist")
    if not options.dry_run and not options.allow_destructive_reset:
        raise ResetGuardError("destructive execution requires --allow-destructive-reset")
    return target


def _run_capture(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise ResetGuardError("required process inspection tooling is unavailable") from exc


def _container_mounts(options: ResetOptions) -> tuple[tuple[str, str, str], ...]:
    docker = shutil.which("docker")
    if docker is None:
        raise ResetGuardError("Docker is required to prove the target is not shared")
    containers = _run_capture([docker, "ps", "-aq"])
    if containers.returncode != 0:
        raise ResetGuardError("Docker container inventory could not be inspected")
    ids = tuple(line.strip() for line in containers.stdout.splitlines() if line.strip())
    if not ids:
        return ()
    inspected = _run_capture(
        [
            docker,
            "inspect",
            "--format",
            '{{.Name}}|{{index .Config.Labels "com.docker.compose.project"}}|{{range .Mounts}}{{.Source}},{{end}}###',
            *ids,
        ]
    )
    if inspected.returncode != 0:
        raise ResetGuardError("Docker mount ownership could not be inspected")
    result: list[tuple[str, str, str]] = []
    for record in inspected.stdout.split("###"):
        if not record.strip():
            continue
        header = record.strip().split("|", 2)
        if len(header) != 3:
            continue
        name, project, sources_text = header
        for source in sources_text.split(","):
            if source:
                result.append((name.lstrip("/"), project, source))
    return tuple(result)


def default_writer_probe(options: ResetOptions) -> WriterStatus:
    """Prove Compose writers are stopped and no process holds the DB file."""

    docker = shutil.which("docker")
    if docker is None:
        raise ResetGuardError("Docker is required to prove Volundr writers are stopped")
    active_services: list[str] = []
    for service in ("volundr-api", "volundr-cad-worker"):
        result = _run_capture(
            [
                docker,
                "ps",
                "--filter",
                f"label=com.docker.compose.project={options.compose_project}",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.Names}}",
            ]
        )
        if result.returncode != 0:
            raise ResetGuardError("Volundr writer status could not be inspected")
        if result.stdout.strip():
            active_services.append(service)

    target = database_path(options)
    lsof = shutil.which("lsof")
    if lsof is None:
        raise ResetGuardError("lsof is required to prove the database has no open handles")
    handles = _run_capture([lsof, "-nP", "-t", "--", str(target)])
    if handles.returncode not in {0, 1}:
        raise ResetGuardError("database handle inspection failed")
    open_handles = tuple(line.strip() for line in handles.stdout.splitlines() if line.strip())

    shared_projects: list[str] = []
    target_root = options.data_dir.resolve()
    for _name, project, source in _container_mounts(options):
        try:
            same_root = Path(source).resolve() == target_root
        except OSError:
            same_root = False
        if same_root and project and project != options.compose_project:
            shared_projects.append(project)
    return WriterStatus(tuple(active_services), open_handles, tuple(sorted(set(shared_projects))))


def _status_payload(status: WriterStatus) -> dict[str, object]:
    return {
        "active_services": list(status.active_services),
        "open_handle_count": len(status.open_handles),
        "shared_projects": list(status.shared_projects),
    }


@contextmanager
def reset_lock(data_dir: Path) -> Iterator[None]:
    lock_path = data_dir / ".volundr-reset.lock"
    try:
        with lock_path.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ResetGuardError("another database reset already holds the advisory lock") from exc
            yield
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError as exc:
        raise ResetGuardError("the configured data root disappeared before locking") from exc


def _inventory(target: Path) -> dict[str, object]:
    if not target.exists():
        return {"database_present": False, "tables": [], "row_counts": {}, "current_revision": None}
    if target.is_symlink() or not target.is_file():
        raise ResetGuardError("the database target must be a regular non-symlink file")
    try:
        connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ResetGuardError("the database target is not a readable SQLite file") from exc
    try:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ]
        counts = {
            name: connection.execute(
                f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"'
            ).fetchone()[0]
            for name in names
        }
        revision_row = (
            connection.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()
            if "alembic_version" in names
            else None
        )
        return {
            "database_present": True,
            "sqlite_version": sqlite3.sqlite_version,
            "tables": names,
            "row_counts": counts,
            "current_revision": revision_row[0] if revision_row else None,
            "artifact_record_count": counts.get("workflow_artifacts", 0),
            "workflow_count": counts.get("workflow_runs", 0) + counts.get("validated_cadquery_workflows", 0),
            "project_count": counts.get("projects", 0),
            "revision_count": counts.get("revisions", 0),
        }
    except sqlite3.Error as exc:
        raise ResetGuardError("the database inventory query failed") from exc
    finally:
        connection.close()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def _base_evidence(options: ResetOptions, target: Path) -> dict[str, object]:
    return {
        "schema_version": "volundr-nonproduction-reset-v1",
        "environment": options.environment.strip().lower(),
        "engine": "sqlite",
        "host_classification": "local-docker-compose",
        "database_name": target.name,
        "schema_name": "main",
        "database_target": redact_database_url(options.database_url or database_url_for(options.data_dir)),
        "destructive_flag_supplied": options.allow_destructive_reset,
        "repository_commit": os.environ.get("VOLUNDR_BUILD_GIT_SHA") or "recorded-by-operator",
    }


def run_reset(
    options: ResetOptions,
    *,
    writer_probe: WriterProbe | None = None,
    migration_runner: MigrationRunner | None = None,
) -> dict[str, object]:
    """Run a guarded dry-run or destructive reset and return safe evidence."""

    target = validate_options(options)
    probe = writer_probe or default_writer_probe
    migrate = migration_runner or default_migration_runner
    with reset_lock(options.data_dir):
        status = probe(options)
        if status.active_services:
            raise ResetGuardError("writers are still active: " + ", ".join(status.active_services))
        if status.open_handles:
            raise ResetGuardError("writers still hold open database handles")
        if status.shared_projects:
            raise ResetGuardError("the target data root is shared with another environment")

        inventory = _inventory(target)
        common = _base_evidence(options, target)
        common["writer_status"] = _status_payload(status)
        common["pre_reset_inventory"] = inventory
        if options.dry_run:
            result = {**common, "mode": "dry_run", "destructive_action": "not_performed"}
            _write_json(options.evidence_root / "reset-dry-run.json", result)
            return result

        _write_json(options.evidence_root / "pre-reset-inventory.json", common)
        for sidecar in (target, Path(str(target) + "-wal"), Path(str(target) + "-shm")):
            if sidecar.exists() or sidecar.is_symlink():
                if sidecar.is_symlink() or not sidecar.is_file():
                    raise ResetGuardError("the database sidecar must be a regular non-symlink file")
                sidecar.unlink()
        execution: dict[str, object] = {
            **common,
            "mode": "destructive",
            "destructive_action": "database_file_and_sqlite_sidecars_removed",
            "reset_completed": False,
        }
        try:
            migrate(options, "upgrade", "head")
            execution["reset_completed"] = True
            execution["post_reset_inventory"] = _inventory(target)
        except Exception as exc:
            execution["error_type"] = type(exc).__name__
            execution["error"] = "migration failed; inspect the command exit status without serializing command output"
            _write_json(options.evidence_root / "reset-execution.json", execution)
            raise
        _write_json(options.evidence_root / "reset-execution.json", execution)
        return execution


def default_migration_runner(options: ResetOptions, *args: str) -> None:
    """Run Alembic locally when available, otherwise in the Compose API image."""

    environment = os.environ.copy()
    environment["VOLUNDR_DATA_DIR"] = str(options.data_dir.resolve())
    backend_root = Path(__file__).resolve().parents[1]
    if shutil.which("alembic") or _module_available("alembic"):
        command = [sys.executable, "-m", "alembic", *args]
        subprocess.run(command, cwd=backend_root, env=environment, check=True)
        return
    docker = shutil.which("docker")
    if docker is None:
        raise ResetGuardError("Alembic is unavailable and Docker cannot run the migration")
    repo_root = backend_root.parent
    command = [docker, "compose", "run", "--rm", "--no-deps", "-T", "volundr-api", "alembic", *args]
    subprocess.run(command, cwd=repo_root, env=environment, check=True)


def _module_available(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--confirm-database", required=True)
    parser.add_argument("--allow-destructive-reset", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="validate and report without removing the database")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("VOLUNDR_DATA_DIR", "data")))
    parser.add_argument("--database-url")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("data/debug-sessions/database-rebuild/clean-database-baseline-01"),
    )
    parser.add_argument("--compose-project", default="volundr")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    options = ResetOptions(
        environment=args.environment,
        confirm_database=args.confirm_database,
        data_dir=args.data_dir,
        evidence_root=args.evidence_root,
        database_url=args.database_url,
        allow_destructive_reset=args.allow_destructive_reset,
        dry_run=args.dry_run or not args.allow_destructive_reset,
        compose_project=args.compose_project,
    )
    try:
        result = run_reset(options)
    except ResetGuardError as exc:
        print(f"reset refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"reset failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"mode": result["mode"], "database_name": result["database_name"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
