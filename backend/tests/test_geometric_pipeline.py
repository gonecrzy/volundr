import json
from collections.abc import Generator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
import trimesh

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.validation_finding import ValidationFinding
from app.services.ai.provider import (
    ModelGenerationRequest,
    ModelGenerationResult,
    RequirementExtractionRequest,
    RequirementExtractionResult,
)
from app.services.cad.runner import CadCompileResult
from app.services.mesh.inspect import MeshMetadata
from tests.test_geometric_invariants import two_hole_wall_mesh


DESIGN_SPEC = {
    "schema_version": "1.0",
    "object_type": "mounting_plate",
    "purpose": "Mount a controller",
    "units": "mm",
    "supported_scope": True,
    "critical_dimensions": [
        {
            "id": "part_width",
            "label": "Overall width",
            "value": 80,
            "unit": "mm",
            "tolerance": None,
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "mount_hole_diameter",
            "label": "Mounting hole diameter",
            "value": 5,
            "unit": "mm",
            "tolerance": None,
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
        {
            "id": "mount_hole_spacing",
            "label": "Mounting hole spacing",
            "value": 50,
            "unit": "mm",
            "tolerance": None,
            "source": "user",
            "importance": "critical",
            "protected": True,
        },
    ],
    "parameters": [],
    "functional_requirements": [
        {
            "id": "mounting_holes",
            "description": "Two mounting holes",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "print_requirements": {},
    "assumptions": [],
    "conflicts": [],
    "missing_requirements": [],
    "clarification_required": False,
    "clarification_questions": [],
    "generation_ready": True,
    "outcome": "generation_ready",
}


def source_with_bounds() -> str:
    return source_template(
        """
// @volundr-geometry type=bounds x=part_width
// @volundr-feature mounting_holes
module mounting_holes() {}
module main_model() {
  cube([part_width, 35, 6]);
}
"""
    )


def source_with_holes() -> str:
    return source_template(
        """
// @volundr-feature mounting_holes
// @volundr-geometry type=hole_group count=2 diameter=mount_hole_diameter spacing=mount_hole_spacing axis=z
module mounting_holes() {}
module main_model() {
  mounting_holes();
}
"""
    )


def source_without_geometry_markers() -> str:
    return source_template(
        """
// @volundr-feature mounting_holes
module mounting_holes() {}
module main_model() {
  cube([part_width, 35, 6]);
}
"""
    )


def source_template(body: str) -> str:
    return f"""
```openscad
/*
Project: Geometry pipeline
Units: millimeters
Purpose: verify candidate geometry
Assumptions: none
Print notes: flat
*/
// ===== QUALITY =====
$fn = 48;
// ===== USER PARAMETERS =====
// @volundr-requirement part_width
part_width = 80;
// @volundr-requirement mount_hole_diameter
mount_hole_diameter = 5;
// @volundr-requirement mount_hole_spacing
mount_hole_spacing = 50;
// ===== DERIVED VALUES =====
// ===== VALIDATION =====
assert(part_width > 0);
// ===== MODULES =====
{body.strip()}
// ===== FINAL MODEL =====
main_model();
```
"""


class GeometryAiProvider:
    def __init__(self, source: str) -> None:
        self.source = source

    @property
    def gemini_ruleset_version(self) -> str:
        return "gemini-ruleset-v1"

    def provider_settings(self) -> dict[str, Any]:
        return {"model": "fake-geometry-model"}

    def requirement_prompt_template_version(self) -> str:
        return "requirements-v1"

    def prompt_template_version_for(self, request: ModelGenerationRequest) -> str:
        return "openscad-generation-v3" if request.design_specification else "legacy-revision-v1"

    def build_prompt(self, request: ModelGenerationRequest) -> str:
        return "geometry prompt"

    def build_requirement_prompt(self, request: RequirementExtractionRequest) -> str:
        return "requirements prompt"

    async def extract_requirements(
        self,
        request: RequirementExtractionRequest,
    ) -> RequirementExtractionResult:
        return RequirementExtractionResult(
            raw_output=json.dumps(DESIGN_SPEC),
            provider="fake",
            provider_model="fake-geometry-model",
        )

    async def generate_model(self, request: ModelGenerationRequest) -> ModelGenerationResult:
        return ModelGenerationResult(
            raw_output=self.source,
            provider="fake",
            provider_model="fake-geometry-model",
        )


class GeometryCadRunner:
    def __init__(self, mesh: trimesh.Trimesh) -> None:
        self.mesh = mesh

    async def compile(self, source: str, job_id: str) -> CadCompileResult:
        job_dir = Path("/tmp") / "volundr-fake-geometry-jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        source_path = job_dir / "model.scad"
        stl_path = job_dir / "model.stl"
        stdout_path = job_dir / "stdout.log"
        stderr_path = job_dir / "stderr.log"
        metadata_path = job_dir / "metadata.json"
        source_path.write_text(source, encoding="utf-8")
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("Compilation finished", encoding="utf-8")
        self.mesh.export(stl_path)
        metadata = MeshMetadata(
            size_x_mm=float(self.mesh.bounding_box.extents[0]),
            size_y_mm=float(self.mesh.bounding_box.extents[1]),
            size_z_mm=float(self.mesh.bounding_box.extents[2]),
            volume_mm3=float(abs(self.mesh.volume)),
            triangle_count=int(len(self.mesh.faces)),
            connected_components=1,
            is_watertight=bool(self.mesh.is_watertight),
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
    *,
    source: str,
    mesh: trimesh.Trimesh,
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
    app.dependency_overrides[get_ai_provider] = lambda: GeometryAiProvider(source)
    app.dependency_overrides[get_cad_runner] = lambda: GeometryCadRunner(mesh)
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_geometric_analysis_result_is_persisted_for_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(
        tmp_path,
        source=source_with_bounds(),
        mesh=box_mesh((80, 35, 6), z_min=0),
    )
    project = client.post(
        "/api/projects",
        json={"name": "Geometry candidate", "original_intent": "Create a bounded part."},
    ).json()
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm wide part."},
    ).json()

    candidate = client.post(f"/api/design-specifications/{spec['id']}/generate").json()
    analysis_response = client.get(f"/api/candidates/{candidate['id']}/geometric-analysis")

    assert candidate["review_state"] == "ready"
    assert analysis_response.status_code == 200
    analysis = analysis_response.json()
    assert analysis["analysis_version"] == "geometric-invariants-v1"
    assert analysis["tolerance_profile_version"] == "geometry-tolerance-v1"
    assert any(
        finding["rule_id"] == "geometry.protected_overall_dimension"
        and finding["verification_state"] == "verified"
        for finding in analysis["findings"]
    )


def test_confirmed_protected_bounds_violation_blocks_candidate(tmp_path: Path) -> None:
    client, SessionLocal = build_client(
        tmp_path,
        source=source_with_bounds(),
        mesh=box_mesh((90, 35, 6), z_min=0),
    )
    project = client.post(
        "/api/projects",
        json={"name": "Geometry blocked", "original_intent": "Create a bounded part."},
    ).json()
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm wide part."},
    ).json()

    candidate = client.post(f"/api/design-specifications/{spec['id']}/generate").json()

    assert candidate["review_state"] == "blocked"
    with SessionLocal() as session:
        findings = list(session.scalars(select(ValidationFinding)))
        geometric = next(finding for finding in findings if finding.rule_id == "geometry.protected_overall_dimension")
        assert geometric.is_blocking is True
        assert geometric.category == "geometry"
        assert json.loads(geometric.metadata_json)["verification_state"] == "violated"


def test_source_contract_passes_but_geometry_hole_spacing_blocks(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(
        tmp_path,
        source=source_with_holes(),
        mesh=two_hole_wall_mesh(spacing=60, diameter=5, height=6, segments=48),
    )
    project = client.post(
        "/api/projects",
        json={"name": "Hole spacing", "original_intent": "Create a two-hole part."},
    ).json()
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create two holes spaced 50 mm apart."},
    ).json()

    candidate = client.post(f"/api/design-specifications/{spec['id']}/generate").json()
    findings = client.get(f"/api/candidates/{candidate['id']}/findings").json()
    analysis = client.get(f"/api/candidates/{candidate['id']}/geometric-analysis").json()

    assert candidate["review_state"] == "blocked"
    spacing = next(finding for finding in findings if finding["rule_id"] == "geometry.protected_hole_spacing")
    analysis_spacing = next(
        finding for finding in analysis["findings"] if finding["rule_id"] == "geometry.protected_hole_spacing"
    )
    assert spacing["is_blocking"] is True
    assert spacing["detected_value"] == "60"
    assert spacing["threshold_value"] == "50"
    assert analysis_spacing["validation_finding_id"] == spacing["id"]


def test_legacy_candidate_without_spec_has_no_geometric_analysis(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(
        tmp_path,
        source=source_with_bounds(),
        mesh=box_mesh((80, 35, 6), z_min=0),
    )
    project = client.post(
        "/api/projects",
        json={"name": "Legacy manual", "original_intent": "Manual source."},
    ).json()
    revision = client.post(
        f"/api/projects/{project['id']}/revisions",
        json={"scad_source": "module main_model() { cube([10, 10, 10]); }\nmain_model();"},
    ).json()

    response = client.get(f"/api/candidates/{revision['id']}/geometric-analysis")

    assert response.status_code == 404


def test_missing_geometry_markers_create_unverifiable_advisory_candidate(tmp_path: Path) -> None:
    client, _SessionLocal = build_client(
        tmp_path,
        source=source_without_geometry_markers(),
        mesh=box_mesh((80, 35, 6), z_min=0),
    )
    project = client.post(
        "/api/projects",
        json={"name": "Missing geometry markers", "original_intent": "Create a bounded part."},
    ).json()
    spec = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"user_instruction": "Create an 80 mm wide part."},
    ).json()

    candidate = client.post(f"/api/design-specifications/{spec['id']}/generate").json()
    analysis = client.get(f"/api/candidates/{candidate['id']}/geometric-analysis").json()

    assert candidate["review_state"] == "ready_with_warnings"
    assert any(
        finding["rule_id"] == "geometry.missing_geometry_markers"
        and finding["verification_state"] == "unverifiable"
        and not finding["is_blocking"]
        for finding in analysis["findings"]
    )


def box_mesh(extents: tuple[float, float, float], *, z_min: float) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation([0, 0, z_min + extents[2] / 2])
    return mesh
