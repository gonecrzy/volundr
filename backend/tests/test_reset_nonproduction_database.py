from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.scripts.reset_nonproduction_database import (
    ResetGuardError,
    ResetOptions,
    WriterStatus,
    redact_database_url,
    run_reset,
    validate_options,
)


def _options(tmp_path: Path, **overrides: object) -> ResetOptions:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "environment": "staging",
        "confirm_database": "app.db",
        "data_dir": data_dir,
        "evidence_root": tmp_path / "evidence",
    }
    values.update(overrides)
    return ResetOptions(**values)


def _quiet_writer_probe(_options: ResetOptions) -> WriterStatus:
    return WriterStatus(active_services=(), open_handles=(), shared_projects=())


def test_production_environment_is_rejected_case_insensitively(tmp_path: Path) -> None:
    with pytest.raises(ResetGuardError, match="non-production"):
        validate_options(_options(tmp_path, environment="PrOdUcTiOn", allow_destructive_reset=True))


def test_exact_database_confirmation_is_required(tmp_path: Path) -> None:
    with pytest.raises(ResetGuardError, match="exact database name"):
        validate_options(_options(tmp_path, confirm_database="other.db", allow_destructive_reset=True))


def test_administrative_database_names_are_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with pytest.raises(ResetGuardError, match="administrative"):
        validate_options(
            _options(
                tmp_path,
                confirm_database="main",
                database_url=f"sqlite:///{(data_dir / 'main').resolve()}",
                allow_destructive_reset=True,
            )
        )


def test_database_url_redaction_never_returns_password_or_full_dsn() -> None:
    rendered = redact_database_url("sqlite:////srv/secret/app.db?password=do-not-log")
    assert "do-not-log" not in rendered
    assert "password" not in rendered.lower()
    assert "/srv/secret/app.db" not in rendered


def test_dry_run_is_default_and_writes_only_machine_readable_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "app.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE projects (id TEXT, name TEXT)")
        connection.execute("INSERT INTO projects VALUES ('private-id', 'private-content')")
        connection.commit()

    result = run_reset(_options(tmp_path), writer_probe=_quiet_writer_probe)

    assert result["mode"] == "dry_run"
    assert database.exists()
    report = json.loads((tmp_path / "evidence" / "reset-dry-run.json").read_text())
    serialized = json.dumps(report)
    assert "private-content" not in serialized
    assert "private-id" not in serialized
    assert "sqlite:////" not in serialized


def test_destructive_reset_requires_explicit_flag_and_stopped_writers(tmp_path: Path) -> None:
    active = lambda _options: WriterStatus(active_services=("volundr-api",), open_handles=(), shared_projects=())
    with pytest.raises(ResetGuardError, match="writers"):
        run_reset(
            _options(tmp_path, allow_destructive_reset=True, dry_run=False),
            writer_probe=active,
        )


def test_destructive_mode_without_explicit_flag_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ResetGuardError, match="allow-destructive-reset"):
        run_reset(
            _options(tmp_path, dry_run=False),
            writer_probe=_quiet_writer_probe,
        )


def test_open_database_handles_are_rejected(tmp_path: Path) -> None:
    open_handle = lambda _options: WriterStatus(active_services=(), open_handles=("present",), shared_projects=())
    with pytest.raises(ResetGuardError, match="open database handles"):
        run_reset(
            _options(tmp_path, allow_destructive_reset=True, dry_run=False),
            writer_probe=open_handle,
        )


def test_destructive_reset_holds_guard_and_invokes_migration_after_removing_one_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    database = data_dir / "app.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE old_data (value TEXT)")
        connection.execute("INSERT INTO old_data VALUES ('old database')")
        connection.commit()
    calls: list[tuple[str, ...]] = []

    def migrate(_options: ResetOptions, *args: str) -> None:
        calls.append(args)
        assert (tmp_path / "evidence" / "pre-reset-inventory.json").exists()
        assert not database.exists()
        database.touch()

    result = run_reset(
        _options(tmp_path, allow_destructive_reset=True, dry_run=False),
        writer_probe=_quiet_writer_probe,
        migration_runner=migrate,
    )

    assert result["mode"] == "destructive"
    assert calls == [("upgrade", "head")]
    assert database.exists()
    execution = json.loads((tmp_path / "evidence" / "reset-execution.json").read_text())
    assert execution["database_name"] == "app.db"
    assert "old database" not in json.dumps(execution)


def test_shared_database_target_is_rejected(tmp_path: Path) -> None:
    shared = lambda _options: WriterStatus(active_services=(), open_handles=(), shared_projects=("production",))
    with pytest.raises(ResetGuardError, match="shared"):
        run_reset(
            _options(tmp_path, allow_destructive_reset=True, dry_run=False),
            writer_probe=shared,
        )
