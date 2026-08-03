from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.api.dependencies import get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app


def _client(tmp_path: Path) -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.state.debug_batch_session_local = session_local
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()
    if hasattr(app.state, "debug_batch_session_local"):
        del app.state.debug_batch_session_local


def test_enabled_api_starts_reads_and_finishes_batch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client = _client(tmp_path)

    started = client.post(
        "/api/debug-batches",
        json={"label": " live-01 ", "target_project_count": 5, "notes": "Run one"},
    )

    assert started.status_code == 201
    batch = started.json()
    assert batch["label"] == "live-01"
    assert batch["state"] == "active"
    assert batch["target_project_count"] == 5
    assert batch["git_head"]
    assert "gemini_api_key" not in batch

    detail = client.get(f"/api/debug-batches/{batch['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == batch["id"]

    finished = client.post(f"/api/debug-batches/{batch['id']}/finish")
    assert finished.status_code == 200
    assert finished.json()["state"] == "frozen"

    repeated = client.post(f"/api/debug-batches/{batch['id']}/finish")
    assert repeated.status_code == 200
    assert repeated.json()["finished_at"] == finished.json()["finished_at"]

    report = client.get(f"/api/debug-batches/{batch['id']}/report")
    assert report.status_code == 200
    assert report.json()["batch"]["id"] == batch["id"]
    assert "projects" in report.json()["summary"]

    evidence = client.get(f"/api/debug-batches/{batch['id']}/evidence.zip")
    assert evidence.status_code == 200
    assert evidence.headers["content-type"] == "application/zip"


def test_enabled_api_rejects_active_baseline_and_accepts_frozen_baseline(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", True)
    client = _client(tmp_path)
    first = client.post(
        "/api/debug-batches", json={"label": "live-01", "target_project_count": 5}
    ).json()

    active_baseline = client.post(
        "/api/debug-batches",
        json={
            "label": "live-02",
            "target_project_count": 5,
            "baseline_batch_id": first["id"],
        },
    )
    assert active_baseline.status_code == 409

    client.post(f"/api/debug-batches/{first['id']}/finish")
    frozen_baseline = client.post(
        "/api/debug-batches",
        json={
            "label": "live-02",
            "target_project_count": 5,
            "baseline_batch_id": first["id"],
        },
    )
    assert frozen_baseline.status_code == 201
