from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _alembic(data_dir: Path, *args: str) -> None:
    environment = os.environ.copy()
    environment["VOLUNDR_DATA_DIR"] = str(data_dir)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _alembic_result(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["VOLUNDR_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def test_validated_workflow_migrations_upgrade_downgrade_and_upgrade_again(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _alembic(data_dir, "upgrade", "0036_benchmark_model_metadata")

    database = data_dir / "app.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO projects (id, name, slug, original_intent, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            ("project-0037-fixture", "Existing", "existing", "Keep this project", "active"),
        )
        connection.commit()

    _alembic(data_dir, "upgrade", "head")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "validated_cadquery_workflows" in tables
        assert "validated_cadquery_outputs" in tables
        assert "validated_cadquery_operations" in tables
        assert "validated_cadquery_provider_attempts" in tables
        assert connection.execute("SELECT COUNT(*) FROM projects WHERE id = 'project-0037-fixture'").fetchone()[0] == 1

    _alembic(data_dir, "downgrade", "0036_benchmark_model_metadata")
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "validated_cadquery_workflows" not in tables
        assert "validated_cadquery_operations" not in tables
        assert "validated_cadquery_provider_attempts" not in tables
        assert connection.execute("SELECT COUNT(*) FROM projects WHERE id = 'project-0037-fixture'").fetchone()[0] == 1

    _alembic(data_dir, "upgrade", "head")


def test_fresh_database_has_no_alembic_drift_after_upgrade_to_head(tmp_path: Path) -> None:
    data_dir = tmp_path / "fresh-data"
    data_dir.mkdir()

    _alembic(data_dir, "upgrade", "head")
    result = _alembic_result(data_dir, "check")

    assert result.returncode == 0, result.stdout + result.stderr
