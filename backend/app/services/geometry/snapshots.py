"""Deterministic, durable geometry snapshots and revision evidence.

This module deliberately observes worker-produced STL artifacts.  It never
changes the authoritative CAD artifacts and it has no provider dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.revision import Revision
from app.models.revision_output import RevisionOutput
from app.models.validation_finding import ValidationFinding
from app.models.workflow import WorkflowArtifact, WorkflowRun
from app.services.workflow.observability import WorkflowRecorder


SNAPSHOT_PACKET_SCHEMA_VERSION = "geometry-snapshot-packet-v1"
REVISION_COMPARISON_SCHEMA_VERSION = "revision-comparison-v1"
CANONICAL_COORDINATE_FRAME = {
    "units": "mm",
    "up_axis": "Z",
    "front_axis": "Y",
    "right_axis": "X",
}
STANDARD_VIEW_NAMES = ("isometric", "opposite_isometric", "front", "right", "top")
OPTIONAL_VIEW_NAMES = ("rear", "left", "bottom")


@dataclass(frozen=True)
class SnapshotRenderSettings:
    image_width: int = 768
    image_height: int = 768
    padding_ratio: float = 0.08
    background: str = "neutral_light"
    edge_overlay: bool = True


@dataclass(frozen=True)
class SnapshotGenerationResult:
    packet: dict[str, Any] | None
    packet_path: Path | None
    packet_artifact_id: str | None
    status: str
    warnings: tuple[str, ...] = ()
    timing: dict[str, Any] | None = None


def build_camera_definition(
    view_name: str,
    *,
    bounds_min: Iterable[float],
    bounds_max: Iterable[float],
    settings: SnapshotRenderSettings,
    coordinate_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    if view_name not in STANDARD_VIEW_NAMES + OPTIONAL_VIEW_NAMES:
        raise ValueError(f"unsupported snapshot view: {view_name}")
    frame = coordinate_frame or CANONICAL_COORDINATE_FRAME
    directions = {
        "isometric": ((1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
        "opposite_isometric": ((-1.0, -1.0, 1.0), (0.0, 0.0, 1.0)),
        "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        "rear": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
        "right": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        "left": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
        "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
        "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    }
    position_direction, up = directions[view_name]
    bounds_min_array = np.asarray(tuple(bounds_min), dtype=float)
    bounds_max_array = np.asarray(tuple(bounds_max), dtype=float)
    if bounds_min_array.shape != (3,) or bounds_max_array.shape != (3,):
        raise ValueError("snapshot bounds must contain three coordinates")
    center = (bounds_min_array + bounds_max_array) / 2.0
    extents = np.maximum(bounds_max_array - bounds_min_array, 1e-6)
    forward = -_unit(position_direction)
    up_vector = _unit(up)
    right = _unit(np.cross(up_vector, forward))
    image_up = _unit(np.cross(forward, right))
    corners = np.asarray(
        [
            (x, y, z)
            for x in (bounds_min_array[0], bounds_max_array[0])
            for y in (bounds_min_array[1], bounds_max_array[1])
            for z in (bounds_min_array[2], bounds_max_array[2])
        ],
        dtype=float,
    )
    projected_x = (corners - center) @ right
    projected_y = (corners - center) @ image_up
    fit_width = max(float(projected_x.max() - projected_x.min()), 1e-6)
    fit_height = max(float(projected_y.max() - projected_y.min()), 1e-6)
    usable_ratio = max(1.0 - 2.0 * settings.padding_ratio, 0.5)
    orthographic_scale = max(fit_width, fit_height) / usable_ratio
    radius = max(float(np.linalg.norm(extents) / 2.0), 1.0)
    camera_position = center + _unit(position_direction) * (radius * 4.0 + 1.0)
    depths = (corners - camera_position) @ forward
    near = max(0.01, float(depths.min() - radius))
    far = float(depths.max() + radius)
    return {
        "view_name": view_name,
        "coordinate_frame": frame,
        "position_direction": _rounded_list(position_direction),
        "view_direction": _rounded_list(forward),
        "position": _rounded_list(camera_position),
        "target": _rounded_list(center),
        "up": _rounded_list(image_up),
        "projection": "orthographic",
        "orthographic_scale": _round(orthographic_scale),
        "near": _round(near),
        "far": _round(far),
        "image_width": settings.image_width,
        "image_height": settings.image_height,
        "padding_ratio": settings.padding_ratio,
    }


def render_stl_view(
    stl_path: Path,
    target_path: Path,
    view_name: str,
    settings: SnapshotRenderSettings,
    *,
    coordinate_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    mesh = _load_mesh(stl_path)
    return render_mesh_view(
        mesh,
        target_path,
        view_name,
        settings,
        coordinate_frame=coordinate_frame,
    )


def render_mesh_view(
    mesh: trimesh.Trimesh,
    target_path: Path,
    view_name: str,
    settings: SnapshotRenderSettings,
    *,
    coordinate_frame: dict[str, str] | None = None,
) -> dict[str, Any]:
    if len(mesh.faces) == 0:
        raise ValueError("snapshot mesh contains no faces")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    camera = build_camera_definition(
        view_name,
        bounds_min=mesh.bounds[0],
        bounds_max=mesh.bounds[1],
        settings=settings,
        coordinate_frame=coordinate_frame,
    )
    image = Image.new("RGB", (settings.image_width, settings.image_height), _background_color(settings.background))
    draw = ImageDraw.Draw(image)
    target = np.asarray(camera["target"], dtype=float)
    forward = np.asarray(camera["view_direction"], dtype=float)
    up = np.asarray(camera["up"], dtype=float)
    right = _unit(np.cross(up, forward))
    camera_position = np.asarray(camera["position"], dtype=float)
    scale = float(camera["orthographic_scale"])
    width = settings.image_width
    height = settings.image_height
    projected = (mesh.vertices - target) @ np.vstack((right, up)).T
    pixels = np.column_stack(
        (
            width / 2.0 + projected[:, 0] * width / scale,
            height / 2.0 - projected[:, 1] * height / scale,
        )
    )
    depth = (mesh.vertices - camera_position) @ forward
    normals = mesh.face_normals if len(mesh.face_normals) == len(mesh.faces) else np.zeros((len(mesh.faces), 3))
    light = _unit(np.asarray((1.0, 1.0, 2.0), dtype=float))
    ordered_faces = sorted(
        range(len(mesh.faces)),
        key=lambda index: float(np.mean(depth[mesh.faces[index]])),
        reverse=True,
    )
    for index in ordered_faces:
        face = mesh.faces[index]
        polygon = [tuple(int(round(value)) for value in pixels[vertex]) for vertex in face]
        normal = normals[index]
        shade = 0.66 + 0.34 * max(0.0, float(np.dot(_unit(normal), light)))
        color = tuple(int(channel * shade) for channel in (171, 181, 194))
        draw.polygon(polygon, fill=color)
        if settings.edge_overlay:
            draw.line(polygon + [polygon[0]], fill=(91, 101, 115), width=1, joint="curve")
    image.save(target_path, format="PNG", optimize=False, compress_level=9)
    return {
        "camera": camera,
        "image_hash": _sha256_file(target_path),
        "width": settings.image_width,
        "height": settings.image_height,
        "media_type": "image/png",
    }


class SnapshotService:
    def __init__(self, *, db: Session, data_dir: Path) -> None:
        self.db = db
        self.data_dir = data_dir
        self.recorder = WorkflowRecorder(db=db, data_dir=data_dir)

    def generate_for_revision(
        self,
        *,
        workflow_run: WorkflowRun,
        revision: Revision,
        outputs: list[RevisionOutput],
        candidate_state: str,
        execution_context: dict[str, Any] | None,
        attempt_id: str | None = None,
        render_settings: SnapshotRenderSettings | None = None,
    ) -> SnapshotGenerationResult:
        started = time.perf_counter()
        deadline = started + settings.snapshot_timeout_seconds
        if not settings.snapshots_enabled:
            return SnapshotGenerationResult(None, None, None, "disabled")
        successful = [
            output
            for output in outputs
            if output.stl_path and self._resolve(output.stl_path).is_file()
        ]
        if not successful:
            self.recorder.record_event(
                workflow_run,
                stage="snapshot_generation",
                event_type="snapshot.not_applicable_before_worker",
                severity="standard",
                message="No worker-produced geometry was available for snapshots.",
                revision_id=revision.id,
                deduplication_key=f"snapshot-not-applicable-{revision.id}",
                metadata={"status": "snapshot_not_applicable_before_worker"},
            )
            return SnapshotGenerationResult(
                None,
                None,
                None,
                "snapshot_not_applicable_before_worker",
                timing={"total_ms": _elapsed_ms(started)},
            )

        render_settings = render_settings or SnapshotRenderSettings(
            image_width=settings.snapshot_image_width,
            image_height=settings.snapshot_image_height,
            background=settings.snapshot_background,
        )
        frame = _coordinate_frame(execution_context)
        snapshot_root = self.data_dir / "projects" / revision.project_id / "revisions" / revision.id / "snapshots"
        snapshot_dir = self._new_snapshot_batch_dir(
            snapshot_root=snapshot_root,
            revision_id=revision.id,
            workflow_run=workflow_run,
            attempt_id=attempt_id,
        )
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        views: list[dict[str, Any]] = []
        component_views: list[dict[str, Any]] = []
        timing_views: dict[str, float] = {}
        meshes = [(output, _load_mesh(self._resolve(output.stl_path))) for output in successful if output.stl_path]
        combined = trimesh.util.concatenate([mesh for _output, mesh in meshes])
        registration_started = time.perf_counter()
        geometry_sources = self._register_geometry_sources(workflow_run, revision, successful)
        section_views: list[dict[str, Any]] = []
        section_omission_reason: str | None = None

        for view_name in STANDARD_VIEW_NAMES[: settings.snapshot_max_whole_design_views]:
            view_started = time.perf_counter()
            path = snapshot_dir / "whole" / f"{view_name}.png"
            try:
                _check_snapshot_deadline(deadline)
                rendered = render_mesh_view(combined, path, view_name, render_settings, coordinate_frame=frame)
                artifact = self.recorder.record_artifact(
                    workflow_run,
                    stage="snapshot_generation",
                    artifact_type="geometry_snapshot",
                    role=f"revision_{revision.id}_{view_name}",
                    path=path,
                    media_type="image/png",
                    redacted=False,
                    metadata={
                        "revision_id": revision.id,
                        "attempt_id": attempt_id,
                        "candidate_state": candidate_state,
                        "view_name": view_name,
                        "camera": rendered["camera"],
                        "geometry_hashes": [output.stl_hash for output in successful],
                    },
                )
                views.append(
                    {
                        "view_id": f"whole:{view_name}",
                        "view_name": view_name,
                        "image_artifact_id": artifact.id,
                        "image_hash": rendered["image_hash"],
                        "camera": rendered["camera"],
                        "width": rendered["width"],
                        "height": rendered["height"],
                    }
                )
            except Exception as exc:
                warnings.append(f"{view_name}: {exc}")
            timing_views[view_name] = _elapsed_ms(view_started)

        for output, mesh in meshes[: settings.snapshot_max_components]:
            component_id = output.component_id or output.output_id
            for view_name in ("isometric", "front", "top"):
                view_started = time.perf_counter()
                path = snapshot_dir / "components" / _safe_stem(component_id) / f"{view_name}.png"
                try:
                    _check_snapshot_deadline(deadline)
                    rendered = render_mesh_view(mesh, path, view_name, render_settings, coordinate_frame=frame)
                    artifact = self.recorder.record_artifact(
                        workflow_run,
                        stage="snapshot_generation",
                        artifact_type="component_snapshot",
                        role=f"revision_{revision.id}_{_safe_stem(component_id)}_{view_name}",
                        path=path,
                        media_type="image/png",
                        redacted=False,
                        metadata={
                            "revision_id": revision.id,
                            "component_id": component_id,
                            "attempt_id": attempt_id,
                            "candidate_state": candidate_state,
                            "view_name": view_name,
                            "camera": rendered["camera"],
                            "geometry_hash": output.stl_hash,
                        },
                    )
                    component_views.append(
                        {
                            "component_id": component_id,
                            "component_name": output.label,
                            "view_id": f"component:{component_id}:{view_name}",
                            "view_name": view_name,
                            "image_artifact_id": artifact.id,
                            "image_hash": rendered["image_hash"],
                            "camera": rendered["camera"],
                            "width": rendered["width"],
                            "height": rendered["height"],
                            "visibility": "visible",
                            "geometry_hash": output.stl_hash,
                        }
                    )
                except Exception as exc:
                    warnings.append(f"{component_id}/{view_name}: {exc}")
                timing_views[f"{component_id}/{view_name}"] = _elapsed_ms(view_started)

        section_reason = _section_reason(execution_context)
        if settings.snapshot_section_enabled and section_reason:
            view_started = time.perf_counter()
            try:
                _check_snapshot_deadline(deadline)
                section_mesh, section_origin, section_normal = _center_section_mesh(combined)
                path = snapshot_dir / "sections" / "center-section.png"
                rendered = render_mesh_view(section_mesh, path, "front", render_settings, coordinate_frame=frame)
                artifact = self.recorder.record_artifact(
                    workflow_run,
                    stage="snapshot_generation",
                    artifact_type="section_snapshot",
                    role=f"revision_{revision.id}_center_section",
                    path=path,
                    media_type="image/png",
                    redacted=False,
                    metadata={
                        "revision_id": revision.id,
                        "candidate_state": candidate_state,
                        "view_name": "center_section",
                        "camera": rendered["camera"],
                        "section_plane_origin": _rounded_list(section_origin),
                        "section_plane_normal": _rounded_list(section_normal),
                        "kept_side": "positive",
                        "reason": section_reason,
                    },
                )
                section_views.append(
                    {
                        "view_id": "section:center_section",
                        "view_name": "center_section",
                        "image_artifact_id": artifact.id,
                        "image_hash": rendered["image_hash"],
                        "camera": rendered["camera"],
                        "width": rendered["width"],
                        "height": rendered["height"],
                        "section_plane_origin": _rounded_list(section_origin),
                        "section_plane_normal": _rounded_list(section_normal),
                        "kept_side": "positive",
                        "reason": section_reason,
                    }
                )
            except Exception as exc:
                section_omission_reason = f"section rendering failed: {exc}"
                warnings.append(section_omission_reason)
            timing_views["center_section"] = _elapsed_ms(view_started)
        elif section_reason:
            section_omission_reason = "section snapshots disabled by deployment configuration"
        else:
            section_omission_reason = "no internal-fit or containment requirement selected a section"

        packet: dict[str, Any] = {
            "schema_version": SNAPSHOT_PACKET_SCHEMA_VERSION,
            "project_id": revision.project_id,
            "workflow_run_id": workflow_run.id,
            "revision_id": revision.id,
            "attempt_id": attempt_id,
            "candidate_state": candidate_state,
            "coordinate_frame": frame,
            "geometry_source": geometry_sources,
            "render_settings": {
                "renderer": "volundr-stl-raster-v1",
                "renderer_version": "1",
                "projection": "orthographic",
                "image_width": render_settings.image_width,
                "image_height": render_settings.image_height,
                "padding_ratio": render_settings.padding_ratio,
                "background": render_settings.background,
                "edge_overlay": render_settings.edge_overlay,
            },
            "views": views,
            "component_views": component_views,
            "section_views": section_views,
            "section_omission_reason": section_omission_reason,
            "warnings": warnings,
            "timing": {
                "total_ms": _elapsed_ms(started),
                "per_view_ms": timing_views,
                "renderer_startup_ms": 0.0,
                "image_encoding_ms": _round(sum(timing_views.values())),
                "artifact_registration_ms": _elapsed_ms(registration_started),
            },
        }
        packet["packet_hash"] = _stable_hash(_hashable_packet(packet))
        packet_path = snapshot_dir / "packet.json"
        packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True), encoding="utf-8")
        packet_artifact = self.recorder.record_artifact(
            workflow_run,
            stage="snapshot_generation",
            artifact_type="geometry_snapshot_packet",
            role=f"revision_{revision.id}_snapshot_packet",
            path=packet_path,
            media_type="application/json",
            redacted=False,
            metadata={
                "revision_id": revision.id,
                "attempt_id": attempt_id,
                "candidate_state": candidate_state,
                "packet_hash": packet["packet_hash"],
                "view_count": len(views),
                "component_view_count": len(component_views),
            },
        )
        packet["packet_artifact_id"] = packet_artifact.id
        self.recorder.record_event(
            workflow_run,
            stage="snapshot_generation",
            event_type="snapshot.generated",
            severity="warning" if warnings else "summary",
            message="Deterministic geometry snapshots generated."
            if not warnings
            else "Deterministic geometry snapshots generated with warnings.",
            revision_id=revision.id,
            deduplication_key=f"snapshot-generated-{revision.id}",
            metadata={
                "packet_artifact_id": packet_artifact.id,
                "packet_hash": packet["packet_hash"],
                "warnings": warnings,
                "timing": packet["timing"],
            },
        )
        return SnapshotGenerationResult(
            packet,
            packet_path,
            packet_artifact.id,
            "generated" if not warnings else "generated_with_warnings",
            tuple(warnings),
            packet["timing"],
        )

    def compare_revisions(
        self,
        *,
        workflow_run: WorkflowRun,
        before_revision: Revision,
        after_revision: Revision,
        revision_instruction: str | None,
        before_packet: dict[str, Any] | None,
        after_packet: dict[str, Any] | None,
        requirement_delta_ids: list[str] | None = None,
        preserved_requirement_ids: list[str] | None = None,
        intended_affected_component_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        before_outputs = self._outputs(before_revision.id)
        after_outputs = self._outputs(after_revision.id)
        before_metrics = _geometry_metrics(before_outputs, self.data_dir)
        after_metrics = _geometry_metrics(after_outputs, self.data_dir)
        paired_views = _pair_views(before_packet, after_packet)
        payload: dict[str, Any] = {
            "schema_version": REVISION_COMPARISON_SCHEMA_VERSION,
            "project_id": after_revision.project_id,
            "from_revision_id": before_revision.id,
            "to_revision_id": after_revision.id,
            "revision_instruction": revision_instruction,
            "requirement_delta_ids": requirement_delta_ids or [],
            "preserved_requirement_ids": preserved_requirement_ids or [],
            "intended_affected_component_ids": intended_affected_component_ids or [],
            "observed_changed_component_ids": _changed_components(before_outputs, after_outputs),
            "geometry": _geometry_delta(before_metrics, after_metrics),
            "artifacts": {
                "before_snapshot_packet_id": (before_packet or {}).get("packet_artifact_id"),
                "after_snapshot_packet_id": (after_packet or {}).get("packet_artifact_id"),
                "paired_view_ids": paired_views,
            },
            "verification": _finding_delta(self.db, before_revision.id, after_revision.id),
        }
        payload["comparison_hash"] = _stable_hash(_hashable_packet(payload))
        comparison_root = (
            self.data_dir
            / "projects"
            / after_revision.project_id
            / "revisions"
            / after_revision.id
            / "snapshots"
        )
        comparison_root.mkdir(parents=True, exist_ok=True)
        comparison_path = self._new_comparison_path(
            comparison_root=comparison_root,
            comparison_hash=payload["comparison_hash"],
        )
        comparison_path.parent.mkdir(parents=True, exist_ok=True)
        comparison_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        artifact = self.recorder.record_artifact(
            workflow_run,
            stage="snapshot_comparison",
            artifact_type="revision_comparison_manifest",
            role=f"revision_{after_revision.id}_comparison",
            path=comparison_path,
            media_type="application/json",
            redacted=False,
            metadata={
                "from_revision_id": before_revision.id,
                "to_revision_id": after_revision.id,
                "comparison_hash": payload["comparison_hash"],
            },
        )
        payload["comparison_artifact_id"] = artifact.id
        self.recorder.record_event(
            workflow_run,
            stage="snapshot_comparison",
            event_type="revision.comparison.generated",
            severity="summary",
            message="Deterministic before-and-after revision evidence generated.",
            revision_id=after_revision.id,
            deduplication_key=f"revision-comparison-{after_revision.id}",
            metadata={"comparison_artifact_id": artifact.id, "comparison_hash": payload["comparison_hash"]},
        )
        return payload

    def _new_snapshot_batch_dir(
        self,
        *,
        snapshot_root: Path,
        revision_id: str,
        workflow_run: WorkflowRun,
        attempt_id: str | None,
    ) -> Path:
        """Allocate an immutable directory for one worker observation."""
        existing_count = sum(
            1
            for artifact in self.db.scalars(
                select(WorkflowArtifact).where(
                    WorkflowArtifact.artifact_type == "geometry_snapshot_packet",
                    WorkflowArtifact.project_id == workflow_run.project_id,
                )
            )
            if _json_mapping(artifact.artifact_metadata_json).get("revision_id") == revision_id
        )
        if existing_count == 0:
            candidate = snapshot_root / "initial"
            if not candidate.exists():
                return candidate
        seed = _safe_stem(attempt_id or workflow_run.id or "attempt")
        index = max(1, existing_count + 1)
        while True:
            candidate = snapshot_root / f"attempt-{seed}-{index}"
            if not candidate.exists():
                return candidate
            index += 1

    def _new_comparison_path(
        self,
        *,
        comparison_root: Path,
        comparison_hash: str,
    ) -> Path:
        """Return a non-overwriting path for a revision comparison artifact."""
        stem = f"comparison-{_safe_stem(comparison_hash)}"
        candidate = comparison_root / f"{stem}.json"
        if not candidate.exists():
            return candidate
        index = 2
        while True:
            candidate = comparison_root / f"{stem}-{index}.json"
            if not candidate.exists():
                return candidate
            index += 1

    def get_packet(self, revision_id: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        query = select(WorkflowArtifact).where(WorkflowArtifact.artifact_type == "geometry_snapshot_packet")
        if project_id is not None:
            query = query.where(WorkflowArtifact.project_id == project_id)
        artifacts = list(self.db.scalars(query.order_by(WorkflowArtifact.created_at.desc())))
        for artifact in artifacts:
            metadata = _json_mapping(artifact.artifact_metadata_json)
            if metadata.get("revision_id") != revision_id:
                continue
            path = self._resolve(artifact.path)
            if not path.is_file():
                return {"status": "snapshot_artifact_missing", "artifact_id": artifact.id, "revision_id": revision_id}
            try:
                packet = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"status": "snapshot_artifact_invalid", "artifact_id": artifact.id, "revision_id": revision_id}
            packet.setdefault("packet_artifact_id", artifact.id)
            return packet
        return None

    def get_comparison(self, revision_id: str, *, project_id: str | None = None) -> dict[str, Any] | None:
        query = select(WorkflowArtifact).where(WorkflowArtifact.artifact_type == "revision_comparison_manifest")
        if project_id is not None:
            query = query.where(WorkflowArtifact.project_id == project_id)
        for artifact in self.db.scalars(query.order_by(WorkflowArtifact.created_at.desc())):
            metadata = _json_mapping(artifact.artifact_metadata_json)
            if metadata.get("to_revision_id") != revision_id:
                continue
            path = self._resolve(artifact.path)
            if not path.is_file():
                return {"status": "comparison_artifact_missing", "artifact_id": artifact.id}
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.setdefault("comparison_artifact_id", artifact.id)
            return payload
        return None

    def resolve_registered_image(self, project_id: str, artifact_id: str) -> Path | None:
        artifact = self.db.get(WorkflowArtifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            return None
        if artifact.artifact_type not in {"geometry_snapshot", "component_snapshot", "section_snapshot"}:
            return None
        path = self._resolve(artifact.path)
        return path if path.is_file() and path.stat().st_size > 0 else None

    def resolve_registered_image_for_revision(
        self,
        project_id: str,
        revision_id: str,
        artifact_id: str,
    ) -> Path | None:
        artifact = self.db.get(WorkflowArtifact, artifact_id)
        if artifact is None or artifact.project_id != project_id:
            return None
        metadata = _json_mapping(artifact.artifact_metadata_json)
        if metadata.get("revision_id") != revision_id:
            return None
        return self.resolve_registered_image(project_id, artifact_id)

    def _register_geometry_sources(
        self,
        workflow_run: WorkflowRun,
        revision: Revision,
        outputs: list[RevisionOutput],
    ) -> dict[str, Any]:
        source: dict[str, Any] = {"brep_artifact_ids": [], "step_artifact_ids": [], "stl_artifact_ids": [], "component_ids": []}
        for output in outputs:
            component_id = output.component_id or output.output_id
            source["component_ids"].append(component_id)
            for kind, artifact_type, target in (
                ("brep_path", "geometry_brep", "brep_artifact_ids"),
                ("step_path", "geometry_step", "step_artifact_ids"),
                ("stl_path", "geometry_stl", "stl_artifact_ids"),
            ):
                relative = getattr(output, kind)
                if not relative:
                    continue
                path = self._resolve(relative)
                if not path.is_file():
                    continue
                artifact = self.recorder.record_artifact(
                    workflow_run,
                    stage="snapshot_generation",
                    artifact_type=artifact_type,
                    role=f"revision_{revision.id}_{_safe_stem(output.output_id)}_{kind.removesuffix('_path')}",
                    path=path,
                    redacted=False,
                    metadata={"revision_id": revision.id, "output_id": output.output_id, "component_id": component_id},
                )
                source[target].append(artifact.id)
        return source

    def _outputs(self, revision_id: str) -> list[RevisionOutput]:
        return list(
            self.db.scalars(
                select(RevisionOutput)
                .where(RevisionOutput.revision_id == revision_id)
                .order_by(RevisionOutput.created_at.asc(), RevisionOutput.output_id.asc())
            )
        )

    def _resolve(self, relative_path: str) -> Path:
        path = Path(relative_path)
        candidate = path if path.is_absolute() else self.data_dir / path
        resolved = candidate.resolve()
        root = self.data_dir.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("snapshot artifact path escapes durable storage")
        return resolved


def _load_mesh(path: Path) -> trimesh.Trimesh:
    loaded = trimesh.load(path, force="mesh")
    if isinstance(loaded, trimesh.Scene):
        meshes = [geometry for geometry in loaded.geometry.values() if isinstance(geometry, trimesh.Trimesh)]
        if not meshes:
            raise ValueError("STL contains no mesh geometry")
        return trimesh.util.concatenate(meshes)
    if isinstance(loaded, trimesh.Trimesh):
        return loaded
    raise ValueError("unsupported STL geometry")


def _coordinate_frame(context: dict[str, Any] | None) -> dict[str, str]:
    if isinstance(context, dict):
        frame = context.get("coordinate_frame") or context.get("coordinate_frames")
        if isinstance(frame, dict) and all(key in frame for key in CANONICAL_COORDINATE_FRAME):
            return {key: str(frame[key]) for key in CANONICAL_COORDINATE_FRAME}
    return dict(CANONICAL_COORDINATE_FRAME)


def _geometry_metrics(outputs: list[RevisionOutput], data_dir: Path) -> dict[str, Any]:
    meshes = []
    for output in outputs:
        if not output.stl_path:
            continue
        path = Path(output.stl_path)
        path = path if path.is_absolute() else data_dir / path
        if path.is_file():
            meshes.append(_load_mesh(path))
    if not meshes:
        return {
            "bounding_box": {"x": None, "y": None, "z": None},
            "volume": None,
            "solid_count": None,
            "component_count": 0,
        }
    combined = trimesh.util.concatenate(meshes)
    extents = combined.bounds[1] - combined.bounds[0]
    return {
        "bounding_box": {axis: _round(float(extents[index])) for index, axis in enumerate(("x", "y", "z"))},
        "volume": _round(float(abs(combined.volume))),
        "solid_count": int(sum(max(1, len(mesh.split(only_watertight=False))) for mesh in meshes)),
        "component_count": len(meshes),
    }


def _geometry_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_box = before["bounding_box"]
    after_box = after["bounding_box"]
    delta = {
        axis: _round(after_box[axis] - before_box[axis])
        if before_box[axis] is not None and after_box[axis] is not None
        else None
        for axis in ("x", "y", "z")
    }
    return {
        "bounding_box_before": before_box,
        "bounding_box_after": after_box,
        "bounding_box_delta": delta,
        "volume_before": before["volume"],
        "volume_after": after["volume"],
        "volume_delta": _round(after["volume"] - before["volume"])
        if before["volume"] is not None and after["volume"] is not None
        else None,
        "solid_count_before": before["solid_count"],
        "solid_count_after": after["solid_count"],
        "component_count_before": before["component_count"],
        "component_count_after": after["component_count"],
    }


def _pair_views(before: dict[str, Any] | None, after: dict[str, Any] | None) -> list[dict[str, Any]]:
    before_views = {view.get("view_name"): view for view in (before or {}).get("views", [])}
    after_views = {view.get("view_name"): view for view in (after or {}).get("views", [])}
    pairs = []
    for view_name in STANDARD_VIEW_NAMES:
        left = before_views.get(view_name)
        right = after_views.get(view_name)
        if left is None or right is None:
            continue
        pairs.append(
            {
                "view_name": view_name,
                "before_image_artifact_id": left.get("image_artifact_id"),
                "after_image_artifact_id": right.get("image_artifact_id"),
                "camera_match": left.get("camera", {}).get("view_direction") == right.get("camera", {}).get("view_direction"),
                "scale_mode": "shared_scale"
                if left.get("camera", {}).get("orthographic_scale") == right.get("camera", {}).get("orthographic_scale")
                else "separate_scale",
            }
        )
    return pairs


def _finding_delta(db: Session, before_id: str, after_id: str) -> dict[str, list[str]]:
    def ids(revision_id: str, *, blocking: bool | None = None) -> set[str]:
        query = select(ValidationFinding).where(ValidationFinding.revision_id == revision_id)
        if blocking is not None:
            query = query.where(ValidationFinding.is_blocking.is_(blocking))
        return {str(item.rule_id) for item in db.scalars(query) if item.rule_id}

    before_all = ids(before_id)
    after_all = ids(after_id)
    before_blocking = ids(before_id, blocking=True)
    after_blocking = ids(after_id, blocking=True)
    return {
        "passed_added": sorted(before_all - after_all),
        "passed_removed": sorted(after_all - before_all),
        "warnings_added": sorted(ids(after_id, blocking=False) - ids(before_id, blocking=False)),
        "warnings_resolved": sorted(ids(before_id, blocking=False) - ids(after_id, blocking=False)),
        "blocking_added": sorted(after_blocking - before_blocking),
        "blocking_resolved": sorted(before_blocking - after_blocking),
    }


def _changed_components(before: list[RevisionOutput], after: list[RevisionOutput]) -> list[str]:
    before_hashes = {output.component_id or output.output_id: output.stl_hash for output in before}
    after_hashes = {output.component_id or output.output_id: output.stl_hash for output in after}
    return sorted(
        component_id
        for component_id in set(before_hashes) | set(after_hashes)
        if before_hashes.get(component_id) != after_hashes.get(component_id)
    )


def _section_reason(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    text = json.dumps(context, sort_keys=True, default=str).lower()
    for keyword, reason in (
        ("internal fit", "internal fit requires a conservative center section"),
        ("containment", "containment requirement requires a conservative center section"),
        ("cavity", "cavity geometry requires a conservative center section"),
        ("wall_thickness", "wall thickness requires a conservative center section"),
        ("lid engagement", "lid engagement requires a conservative center section"),
        ("internal_clearance", "internal clearance requires a conservative center section"),
    ):
        if keyword in text:
            return reason
    return None


def _center_section_mesh(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray]:
    origin = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
    normal = np.asarray((0.0, 1.0, 0.0), dtype=float)
    centers = mesh.triangles_center
    selected = np.flatnonzero((centers - origin) @ normal >= 0.0)
    if selected.size == 0:
        raise ValueError("center section removed all faces")
    section = mesh.submesh([selected], append=True, repair=False)
    if not isinstance(section, trimesh.Trimesh) or len(section.faces) == 0:
        raise ValueError("center section contains no faces")
    return section, origin, normal


def _hashable_packet(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _hashable_packet(item)
            for key, item in value.items()
            if not key.endswith("_id")
            and not key.endswith("_ids")
            and "artifact" not in key
            and key != "timing"
            and key not in {"project_id", "workflow_run_id", "revision_id", "attempt_id"}
        }
    if isinstance(value, list):
        return [_hashable_packet(item) for item in value]
    return value


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _json_mapping(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _unit(values: Iterable[float]) -> np.ndarray:
    result = np.asarray(tuple(values), dtype=float)
    norm = float(np.linalg.norm(result))
    if norm <= 1e-12:
        raise ValueError("snapshot vector must be non-zero")
    return result / norm


def _rounded_list(values: Iterable[float]) -> list[float]:
    return [_round(float(value)) for value in values]


def _round(value: float) -> float:
    return float(round(value, 6))


def _background_color(name: str) -> tuple[int, int, int]:
    return {"neutral_light": (246, 247, 249), "white": (255, 255, 255)}.get(name, (246, 247, 249))


def _safe_stem(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip(".-") or "component"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _check_snapshot_deadline(deadline: float) -> None:
    if time.perf_counter() > deadline:
        raise TimeoutError("snapshot generation exceeded configured timeout")
