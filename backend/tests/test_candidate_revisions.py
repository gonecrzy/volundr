from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.generation_attempt import GenerationAttempt
from app.models.revision import Revision
from app.services.ai.provider import ModelGenerationRequest, ModelGenerationResult
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata


class SourceAiProvider:
    def __init__(self, *sources: str) -> None:
        self.sources = list(sources)
        self.requests: list[ModelGenerationRequest] = []

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        self.requests.append(request)
        source = self.sources.pop(0) if self.sources else clean_source()
        return ModelGenerationResult(
            raw_output=f"```scad\n{source}\n```",
            provider="fake",
            provider_model="fake-candidate-model",
        )


class CandidateCadRunner:
    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-candidate-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")

        if "compile_fail" in source:
            stderr_path.write_text("Parser error: syntax error", encoding="utf-8")
            return CadCompileResult(
                job_id=job_id,
                success=False,
                timed_out=False,
                exit_code=1,
                source_path=source_path,
                stl_path=None,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                metadata_path=None,
                source_hash="fake-source-hash",
                output_size_bytes=0,
                metadata=None,
                error_message="Parser error: syntax error",
            )

        mesh = mesh_for_source(source)
        mesh.export(stl_path)
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        metadata = MeshMetadata(
            size_x_mm=float(mesh.bounding_box.extents[0]),
            size_y_mm=float(mesh.bounding_box.extents[1]),
            size_z_mm=float(mesh.bounding_box.extents[2]),
            volume_mm3=float(abs(mesh.volume)),
            triangle_count=int(len(mesh.faces)),
            connected_components=2 if "advisory_components" in source else 1,
            is_watertight=bool(mesh.is_watertight),
            is_winding_consistent=True,
            center_of_mass=(0.0, 0.0, 0.0),
        )
        metadata_path.write_text("{}", encoding="utf-8")
        return CadCompileResult(
            job_id=job_id,
            success=True,
            timed_out=False,
            exit_code=0,
            source_path=source_path,
            stl_path=stl_path,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            metadata_path=metadata_path,
            source_hash="fake-source-hash",
            output_size_bytes=stl_path.stat().st_size,
            metadata=metadata,
            error_message=None,
        )


def build_client(
    tmp_path: Path,
    ai_provider: SourceAiProvider | None = None,
) -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(engine)

    def override_db() -> Generator[Session, None, None]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_data_dir] = lambda: tmp_path / "data"
    app.dependency_overrides[get_ai_provider] = lambda: ai_provider or SourceAiProvider(clean_source())
    app.dependency_overrides[get_cad_runner] = lambda: CandidateCadRunner()
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_clean_ai_generation_creates_ready_candidate_without_replacing_active_revision(
    tmp_path: Path,
) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(clean_source()))
    project, active_revision = create_project_with_active_revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a second cube."},
    )

    assert response.status_code == 201
    candidate = response.json()
    assert candidate["source_type"] == "ai_revision"
    assert candidate["status"] == "succeeded"
    assert candidate["review_state"] == "ready"
    assert candidate["is_accepted"] is False
    assert candidate["validation_summary"]["blocking_count"] == 0
    assert candidate["validation_summary"]["advisory_count"] == 0

    refreshed_project = client.get(f"/api/projects/{project['id']}").json()
    assert refreshed_project["active_revision_id"] == active_revision["id"]

    candidates = client.get(f"/api/projects/{project['id']}/candidates").json()
    assert [entry["id"] for entry in candidates] == [candidate["id"]]
    assert client.get(f"/api/candidates/{candidate['id']}/findings").json() == []


def test_advisory_findings_create_ready_with_warnings_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(advisory_source()))
    project, _active_revision = create_project_with_active_revision(client)

    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create two intentional components."},
    ).json()

    assert candidate["review_state"] == "ready_with_warnings"
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert any(finding["rule_id"] == "mesh.disconnected_components" for finding in findings)
    assert all(finding["is_blocking"] is False for finding in findings)


def test_blocking_finding_creates_blocked_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(below_plate_source()))
    project, active_revision = create_project_with_active_revision(client)

    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a model below the plate."},
    ).json()

    assert candidate["review_state"] == "blocked"
    assert candidate["is_accepted"] is False
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    below_plate = next(finding for finding in findings if finding["rule_id"] == "orientation.below_build_plate")
    assert below_plate["severity"] == "critical"
    assert below_plate["is_blocking"] is True


def test_accepting_ready_candidate_updates_active_revision(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(clean_source()))
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a candidate."},
    ).json()

    response = client.post(f"/api/candidates/{candidate['id']}/accept")

    assert response.status_code == 200
    accepted = response.json()
    assert accepted["review_state"] == "accepted"
    assert accepted["is_accepted"] is True
    assert accepted["accepted_at"] is not None
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == candidate["id"]
    previous = next(
        revision
        for revision in client.get(f"/api/projects/{project['id']}/revisions").json()
        if revision["id"] == active_revision["id"]
    )
    assert previous["review_state"] == "accepted"
    active_response = client.get(f"/api/projects/{project['id']}/active-revision")
    assert active_response.status_code == 200
    assert active_response.json()["id"] == candidate["id"]


def test_accepting_ready_with_warnings_candidate_updates_active_revision(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(advisory_source()))
    project, _active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a warning candidate."},
    ).json()

    response = client.post(f"/api/candidates/{candidate['id']}/accept")

    assert response.status_code == 200
    assert response.json()["review_state"] == "accepted"
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == candidate["id"]


def test_blocked_candidate_cannot_be_accepted_or_dismissed_into_acceptability(
    tmp_path: Path,
) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(oversized_source()))
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create an oversized candidate."},
    ).json()
    finding = client.get(f"/api/candidates/{candidate['id']}/findings").json()[0]

    dismiss_response = client.post(
        f"/api/validation-findings/{finding['id']}/dismiss",
        json={"reason": "I understand the warning."},
    )
    accept_response = client.post(f"/api/candidates/{candidate['id']}/accept")

    assert dismiss_response.status_code == 409
    assert accept_response.status_code == 409
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_rejecting_candidate_preserves_active_revision_and_files(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(below_plate_source()))
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a blocked candidate."},
    ).json()

    response = client.post(f"/api/candidates/{candidate['id']}/reject")

    assert response.status_code == 200
    rejected = response.json()
    assert rejected["review_state"] == "rejected"
    assert rejected["rejected_at"] is not None
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]
    assert client.get(f"/api/revisions/{candidate['id']}/source").status_code == 200
    assert client.get(f"/api/revisions/{candidate['id']}/stl").status_code == 200
    assert client.get(f"/api/candidates/{candidate['id']}/findings").json()


def test_blocked_or_rejected_candidates_cannot_be_restored_as_active(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(below_plate_source()))
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a blocked candidate."},
    ).json()

    assert client.post(f"/api/revisions/{candidate['id']}/restore").status_code == 404
    client.post(f"/api/candidates/{candidate['id']}/reject")
    assert client.post(f"/api/revisions/{candidate['id']}/restore").status_code == 404
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_dismissing_advisory_warning_persists_without_deleting_it(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(advisory_source()))
    project, _active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a warning candidate."},
    ).json()
    finding = client.get(f"/api/candidates/{candidate['id']}/findings").json()[0]

    response = client.post(
        f"/api/validation-findings/{finding['id']}/dismiss",
        json={"reason": "Intentional separate print pieces."},
    )

    assert response.status_code == 200
    dismissed = response.json()
    assert dismissed["dismissed_at"] is not None
    assert dismissed["dismissal_reason"] == "Intentional separate print pieces."
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    assert len(findings) == 1
    assert findings[0]["id"] == finding["id"]
    assert findings[0]["finding_state"] == "dismissed"


def test_failed_compile_creates_no_candidate(tmp_path: Path) -> None:
    provider = SourceAiProvider(compile_fail_source(), compile_fail_source())
    client, _SessionLocal = build_client(tmp_path, provider)
    project, active_revision = create_project_with_active_revision(client)

    response = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create invalid OpenSCAD."},
    )

    assert response.status_code == 201
    revision = response.json()
    assert revision["status"] == "failed"
    assert revision["review_state"] is None
    assert client.get(f"/api/projects/{project['id']}/candidates").json() == []
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_zero_volume_mesh_creates_no_acceptable_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(zero_volume_source()))
    project, active_revision = create_project_with_active_revision(client)

    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a flat zero volume candidate."},
    ).json()

    assert candidate["review_state"] == "blocked"
    assert client.post(f"/api/candidates/{candidate['id']}/accept").status_code == 409
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_build_volume_and_below_plate_findings_block_acceptance(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(
        tmp_path,
        SourceAiProvider(oversized_source(), below_plate_source()),
    )
    project, _active_revision = create_project_with_active_revision(client)

    oversized = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create an oversized candidate."},
    ).json()
    below = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a below-plate candidate."},
    ).json()

    oversized_findings = client.get(f"/api/candidates/{oversized['id']}/findings").json()
    below_findings = client.get(f"/api/candidates/{below['id']}/findings").json()
    assert oversized["review_state"] == "blocked"
    assert any(finding["rule_id"] == "profile.build_volume" and finding["is_blocking"] for finding in oversized_findings)
    assert below["review_state"] == "blocked"
    assert any(finding["rule_id"] == "orientation.below_build_plate" and finding["is_blocking"] for finding in below_findings)


def test_invalid_candidate_state_transitions_fail_cleanly(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(clean_source()))
    project, _active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create a candidate."},
    ).json()
    client.post(f"/api/candidates/{candidate['id']}/accept")

    assert client.post(f"/api/candidates/{candidate['id']}/reject").status_code == 409
    assert client.post(f"/api/candidates/{candidate['id']}/accept").status_code == 409


def test_acceptance_failure_preserves_active_revision(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(tmp_path, SourceAiProvider(below_plate_source()))
    project, active_revision = create_project_with_active_revision(client)
    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create blocked candidate."},
    ).json()

    assert client.post(f"/api/candidates/{candidate['id']}/accept").status_code == 409
    assert client.get(f"/api/projects/{project['id']}").json()["active_revision_id"] == active_revision["id"]


def test_generation_attempt_and_candidate_links_remain_traceable(tmp_path: Path) -> None:
    client, SessionLocal = build_client(tmp_path, SourceAiProvider(clean_source()))
    project, _active_revision = create_project_with_active_revision(client)

    candidate = client.post(
        f"/api/projects/{project['id']}/generate",
        json={"user_instruction": "Create traceable candidate."},
    ).json()

    with SessionLocal() as session:
        attempt = session.scalar(select(GenerationAttempt).where(GenerationAttempt.resulting_revision_id == candidate["id"]))
        revision = session.get(Revision, candidate["id"])
        assert attempt is not None
        assert revision is not None
        assert attempt.project_id == revision.project_id
        assert attempt.base_revision_id == revision.parent_revision_id


def create_project_with_active_revision(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": "Candidate fixture", "original_intent": "Create a base cube."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"scad_source": clean_source(), "user_instruction": "Accepted base cube."},
    ).json()
    return project, revision


def mesh_for_source(source: str) -> trimesh.Trimesh:
    if "advisory_components" in source:
        left = cube_mesh((10.0, 10.0, 10.0), z_min=0.0)
        left.apply_translation([-15.0, 0.0, 0.0])
        right = cube_mesh((10.0, 10.0, 10.0), z_min=0.0)
        right.apply_translation([15.0, 0.0, 0.0])
        return trimesh.util.concatenate([left, right])
    if "below_plate" in source:
        return cube_mesh((10.0, 10.0, 10.0), z_min=-1.0)
    if "oversized" in source:
        return cube_mesh((300.0, 10.0, 10.0), z_min=0.0)
    if "zero_volume" in source:
        return trimesh.Trimesh(
            vertices=[
                [0.0, 0.0, 0.0],
                [10.0, 0.0, 0.0],
                [0.0, 10.0, 0.0],
            ],
            faces=[[0, 1, 2]],
            process=False,
        )
    return cube_mesh((10.0, 10.0, 10.0), z_min=0.0)


def cube_mesh(extents: tuple[float, float, float], *, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([0.0, 0.0, z_min + extents[2] / 2.0])
    return mesh


def clean_source() -> str:
    return """
module main_model() {
  cube([10, 10, 10]);
}
main_model();
"""


def advisory_source() -> str:
    return """
module main_model() {
  advisory_components = true;
  cube([10, 10, 10]);
}
main_model();
"""


def below_plate_source() -> str:
    return """
module main_model() {
  below_plate = true;
  cube([10, 10, 10]);
}
main_model();
"""


def oversized_source() -> str:
    return """
module main_model() {
  oversized = true;
  cube([300, 10, 10]);
}
main_model();
"""


def zero_volume_source() -> str:
    return """
module main_model() {
  zero_volume = true;
  polygon(points=[[0,0],[10,0],[0,10]]);
}
main_model();
"""


def compile_fail_source() -> str:
    return """
module main_model() {
  compile_fail = true;
  broken(
}
main_model();
"""
