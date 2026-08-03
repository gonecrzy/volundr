from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_data_dir
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app


def test_capabilities_expose_only_the_safe_developer_boolean(monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", False, raising=False)

    response = TestClient(app).get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {"developer_tools_enabled": False}


def test_all_debug_batch_operations_are_forbidden_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", False, raising=False)
    client = TestClient(app)

    operations = [
        ("post", "/api/debug-batches", {"label": "live-01", "target_project_count": 5}),
        ("get", "/api/debug-batches/one", None),
        ("post", "/api/debug-batches/one/finish", None),
        ("get", "/api/debug-batches/one/report", None),
        ("get", "/api/debug-batches/one/evidence.zip", None),
        ("post", "/api/debug-batches/one/frontend-events", {"events": []}),
        ("get", "/api/debug-batches/one/comparison", None),
    ]

    for method, path, payload in operations:
        response = getattr(client, method)(path, json=payload) if payload is not None else getattr(client, method)(path)
        assert response.status_code == 403, (method, path, response.text)


def test_normal_project_route_remains_available_when_disabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "developer_tools_enabled", False, raising=False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_db() -> Generator[Session, None, None]:
        with session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    try:
        response = TestClient(app).get("/api/projects")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
