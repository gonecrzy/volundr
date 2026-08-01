import json
from pathlib import Path

import trimesh
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.api.dependencies import get_data_dir
from app.db.session import get_db
from app.main import app
from app.models.project import Project
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.workflow import WorkflowArtifact
from app.services.geometry.snapshots import (
    CANONICAL_COORDINATE_FRAME,
    STANDARD_VIEW_NAMES,
    SnapshotRenderSettings,
    SnapshotService,
    build_camera_definition,
    render_stl_view,
)
from app.services.workflow.observability import WorkflowRecorder
from fastapi.testclient import TestClient


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False)()


def _project_revision_output(session: Session, data_dir: Path) -> tuple[Project, Revision, RevisionOutput]:
    project = Project(
        name="Snapshot project",
        slug="snapshot-project",
        original_intent="Create a spacer plate.",
    )
    session.add(project)
    session.flush()
    revision = Revision(
        project_id=project.id,
        revision_number=1,
        source_type="fixture",
        user_instruction="Create a spacer plate.",
        source_path="revisions/r1/source.py",
        status="succeeded",
        is_accepted=True,
        review_state="accepted",
    )
    session.add(revision)
    session.flush()
    stl_path = data_dir / "revisions" / revision.id / "stl" / "plate.stl"
    stl_path.parent.mkdir(parents=True, exist_ok=True)
    trimesh.creation.box(extents=(80, 45, 6)).export(stl_path)
    output = RevisionOutput(
        revision_id=revision.id,
        output_id="plate",
        component_id="plate_body",
        component_ids_json=json.dumps(["plate_body"]),
        execution_state="ready",
        output_type="printable_component",
        label="Plate",
        filename="plate.stl",
        quantity=1,
        required=True,
        entrypoint="plate",
        stl_path=str(stl_path.relative_to(data_dir)),
        stl_hash="fixture-stl-hash",
        mesh_metadata_json=json.dumps(
            {
                "size_x_mm": 80.0,
                "size_y_mm": 45.0,
                "size_z_mm": 6.0,
                "volume_mm3": 21600.0,
                "triangle_count": 12,
                "connected_components": 1,
                "is_watertight": True,
                "is_winding_consistent": True,
                "center_of_mass": [40.0, 22.5, 3.0],
            }
        ),
        topology_metadata_json=json.dumps(
            {
                "valid": True,
                "detected_solid_count": 1,
                "expected_solid_count": 1,
                "bounding_box_mm": {"xlen": 80.0, "ylen": 45.0, "zlen": 6.0},
            }
        ),
    )
    session.add(output)
    session.commit()
    session.refresh(project)
    session.refresh(revision)
    session.refresh(output)
    return project, revision, output


def test_standard_views_and_camera_metadata_are_deterministic() -> None:
    assert STANDARD_VIEW_NAMES == ("isometric", "opposite_isometric", "front", "right", "top")
    first = build_camera_definition(
        "front",
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(80.0, 45.0, 6.0),
        settings=SnapshotRenderSettings(),
    )
    second = build_camera_definition(
        "front",
        bounds_min=(0.0, 0.0, 0.0),
        bounds_max=(80.0, 45.0, 6.0),
        settings=SnapshotRenderSettings(),
    )
    assert first == second
    assert first["position_direction"] == [0.0, 1.0, 0.0]
    assert first["view_direction"] == [0.0, -1.0, 0.0]
    assert first["up"] == [0.0, 0.0, 1.0]
    assert first["orthographic_scale"] > 0


def test_renderer_produces_stable_png_and_preserves_source(tmp_path: Path) -> None:
    source = tmp_path / "plate.stl"
    target_a = tmp_path / "a.png"
    target_b = tmp_path / "b.png"
    trimesh.creation.box(extents=(20, 10, 4)).export(source)

    first = render_stl_view(source, target_a, "isometric", SnapshotRenderSettings())
    second = render_stl_view(source, target_b, "isometric", SnapshotRenderSettings())

    assert first["image_hash"] == second["image_hash"]
    assert target_a.read_bytes() == target_b.read_bytes()
    assert target_a.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert source.exists()


def test_snapshot_packet_registers_durable_images_and_metadata(tmp_path: Path) -> None:
    session = _session()
    data_dir = tmp_path / "data"
    project, revision, output = _project_revision_output(session, data_dir)
    run = WorkflowRecorder(db=session, data_dir=data_dir).start_run(
        project_id=project.id,
        workflow_type="source_generation",
    )

    result = SnapshotService(db=session, data_dir=data_dir).generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[output],
        candidate_state="ready",
        execution_context={"coordinate_frame": CANONICAL_COORDINATE_FRAME},
    )

    assert result.packet["schema_version"] == "geometry-snapshot-packet-v1"
    assert result.packet["candidate_state"] == "ready"
    assert result.packet["coordinate_frame"] == CANONICAL_COORDINATE_FRAME
    assert {view["view_name"] for view in result.packet["views"]} == set(STANDARD_VIEW_NAMES)
    artifacts = list(
        session.scalars(
            select(WorkflowArtifact).where(WorkflowArtifact.project_id == project.id)
        )
    )
    assert "geometry_snapshot_packet" in {artifact.artifact_type for artifact in artifacts}
    assert "geometry_snapshot" in {artifact.artifact_type for artifact in artifacts}
    assert all((data_dir / artifact.path).exists() for artifact in artifacts)
    assert any(parent.name == revision.id for parent in result.packet_path.parents)
    assert result.packet_path.parent.name in {"initial"} or result.packet_path.parent.name.startswith("attempt-")
    repeat = SnapshotService(db=session, data_dir=data_dir).generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[output],
        candidate_state="ready",
        execution_context={"coordinate_frame": CANONICAL_COORDINATE_FRAME},
    )
    assert repeat.packet["packet_hash"] == result.packet["packet_hash"]
    assert repeat.packet_path != result.packet_path


def test_pre_worker_snapshot_is_not_applicable_and_missing_image_is_reported(tmp_path: Path) -> None:
    session = _session()
    data_dir = tmp_path / "data"
    project, revision, _output = _project_revision_output(session, data_dir)
    run = WorkflowRecorder(db=session, data_dir=data_dir).start_run(
        project_id=project.id,
        workflow_type="source_generation",
    )
    service = SnapshotService(db=session, data_dir=data_dir)

    result = service.generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[],
        candidate_state="blocked",
        execution_context={},
    )
    assert result.packet is None
    assert result.status == "snapshot_not_applicable_before_worker"
    assert service.resolve_registered_image(project.id, "missing") is None

    successful = service.generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[_output],
        candidate_state="blocked",
        execution_context={},
    )
    image_artifact_id = successful.packet["views"][0]["image_artifact_id"]
    image_path = service.resolve_registered_image(project.id, image_artifact_id)
    assert image_path is not None
    image_path.unlink()
    assert service.resolve_registered_image(project.id, image_artifact_id) is None


def test_internal_fit_context_generates_a_conservative_section_snapshot(tmp_path: Path) -> None:
    session = _session()
    data_dir = tmp_path / "data"
    project, revision, output = _project_revision_output(session, data_dir)
    run = WorkflowRecorder(db=session, data_dir=data_dir).start_run(
        project_id=project.id,
        workflow_type="source_generation",
    )
    result = SnapshotService(db=session, data_dir=data_dir).generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[output],
        candidate_state="ready",
        execution_context={"active_requirements": [{"description": "internal fit clearance"}]},
    )
    assert len(result.packet["section_views"]) == 1
    assert result.packet["section_views"][0]["kept_side"] == "positive"


def test_revision_comparison_records_metrics_and_paired_views(tmp_path: Path) -> None:
    session = _session()
    data_dir = tmp_path / "data"
    project, before, output = _project_revision_output(session, data_dir)
    run = WorkflowRecorder(db=session, data_dir=data_dir).start_run(
        project_id=project.id,
        workflow_type="revision_generation",
    )
    service = SnapshotService(db=session, data_dir=data_dir)
    before_result = service.generate_for_revision(
        workflow_run=run,
        revision=before,
        outputs=[output],
        candidate_state="ready",
        execution_context={},
    )

    after = Revision(
        project_id=project.id,
        parent_revision_id=before.id,
        revision_number=2,
        source_type="fixture",
        user_instruction="Increase thickness.",
        source_path="revisions/r2/source.py",
        status="succeeded",
        is_accepted=True,
        review_state="accepted",
    )
    session.add(after)
    session.flush()
    after_path = data_dir / "revisions" / after.id / "stl" / "plate.stl"
    after_path.parent.mkdir(parents=True, exist_ok=True)
    trimesh.creation.box(extents=(80, 45, 8)).export(after_path)
    after_output = RevisionOutput(
        revision_id=after.id,
        output_id="plate",
        component_id="plate_body",
        component_ids_json=json.dumps(["plate_body"]),
        execution_state="ready",
        output_type="printable_component",
        label="Plate",
        filename="plate.stl",
        quantity=1,
        required=True,
        entrypoint="plate",
        stl_path=str(after_path.relative_to(data_dir)),
        stl_hash="after-stl-hash",
        mesh_metadata_json=output.mesh_metadata_json.replace('"size_z_mm": 6.0', '"size_z_mm": 8.0').replace('"volume_mm3": 21600.0', '"volume_mm3": 28800.0'),
        topology_metadata_json=output.topology_metadata_json.replace('"zlen": 6.0', '"zlen": 8.0'),
    )
    session.add(after_output)
    session.commit()
    session.refresh(after)
    session.refresh(after_output)
    after_result = service.generate_for_revision(
        workflow_run=run,
        revision=after,
        outputs=[after_output],
        candidate_state="ready",
        execution_context={},
    )

    comparison = service.compare_revisions(
        workflow_run=run,
        before_revision=before,
        after_revision=after,
        revision_instruction="Increase thickness.",
        before_packet=before_result.packet,
        after_packet=after_result.packet,
    )
    assert comparison["schema_version"] == "revision-comparison-v1"
    assert comparison["geometry"]["bounding_box_delta"]["z"] == 2.0
    assert comparison["geometry"]["volume_delta"] == 7200.0
    assert len(comparison["artifacts"]["paired_view_ids"]) == len(STANDARD_VIEW_NAMES)
    assert comparison["comparison_hash"]


def test_snapshot_api_owns_revision_and_does_not_expose_paths(tmp_path: Path) -> None:
    session = _session()
    data_dir = tmp_path / "data"
    project, revision, output = _project_revision_output(session, data_dir)
    run = WorkflowRecorder(db=session, data_dir=data_dir).start_run(
        project_id=project.id,
        workflow_type="source_generation",
    )
    result = SnapshotService(db=session, data_dir=data_dir).generate_for_revision(
        workflow_run=run,
        revision=revision,
        outputs=[output],
        candidate_state="ready",
        execution_context={},
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_data_dir] = lambda: data_dir
    try:
        client = TestClient(app)
        packet_response = client.get(f"/api/revisions/{revision.id}/snapshots")
        assert packet_response.status_code == 200
        assert "packet_hash" in packet_response.json()
        artifact_id = result.packet["views"][0]["image_artifact_id"]
        image_response = client.get(f"/api/revisions/{revision.id}/snapshots/images/{artifact_id}")
        assert image_response.status_code == 200
        assert image_response.headers["content-type"].startswith("image/png")
        assert str(data_dir) not in packet_response.text
    finally:
        app.dependency_overrides.clear()
