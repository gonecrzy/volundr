from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_cad_runner, get_data_dir, get_validated_actor_id, get_workflow_ai_provider
from app.core.config import settings
from app.db.session import get_db
from app.schemas.project import ClarificationAnswersCreate
from app.schemas.validated_cadquery import (
    ValidatedArtifactRead,
    ValidatedBoundedRevision,
    ValidatedCadQueryStart,
    ValidatedDiagnosticsRead,
    ValidatedIndependentReviewSubmit,
    ValidatedPlanRead,
    ValidatedRequirementsRead,
    ValidatedVerificationRead,
    ValidatedWorkflowRead,
    ValidatedOutputRead,
)
from app.services.validated_cadquery_workflow import ValidatedCadQueryWorkflowService
from app.services.executable_cadquery.workflow import ExecutableCadQueryWorkflowService


router = APIRouter(prefix="/api/validated-cadquery", tags=["validated-cadquery"])


def _service(
    db: Session,
    data_dir: Path,
    ai_provider: object | None = None,
    cad_runner: object | None = None,
    owner_id: str = "anonymous",
) -> ValidatedCadQueryWorkflowService:
    service_type = (
        ExecutableCadQueryWorkflowService
        if settings.executable_cadquery_flow_enabled
        else ValidatedCadQueryWorkflowService
    )
    return service_type(
        db=db,
        data_dir=data_dir,
        ai_provider=ai_provider,
        cad_runner=cad_runner,
        owner_id=owner_id,
    )


@router.post("/designs", response_model=ValidatedWorkflowRead, status_code=201)
async def start_validated_design(
    payload: ValidatedCadQueryStart,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: object = Depends(get_workflow_ai_provider),
    cad_runner: object = Depends(get_cad_runner),
    owner_id: str = Depends(get_validated_actor_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ValidatedWorkflowRead:
    if not (settings.validated_cadquery_flow_enabled or settings.executable_cadquery_flow_enabled):
        raise HTTPException(status_code=404, detail="validated workflow not found")
    try:
        return await _service(db, data_dir, ai_provider, cad_runner, owner_id).start_design(payload, idempotency_key=idempotency_key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}", response_model=ValidatedWorkflowRead)
def get_validated_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedWorkflowRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).read(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/clarification", response_model=ValidatedWorkflowRead)
async def submit_validated_clarification(
    workflow_id: str,
    payload: ClarificationAnswersCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: object = Depends(get_workflow_ai_provider),
    cad_runner: object = Depends(get_cad_runner),
    owner_id: str = Depends(get_validated_actor_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ValidatedWorkflowRead:
    try:
        return await _service(db, data_dir, ai_provider, cad_runner, owner_id).submit_clarification(workflow_id, payload, idempotency_key=idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/requirements", response_model=ValidatedRequirementsRead)
def get_validated_requirements(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedRequirementsRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).requirements(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/plan", response_model=ValidatedPlanRead)
def get_validated_plan(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedPlanRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).plan(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/outputs", response_model=list[ValidatedOutputRead])
def get_validated_outputs(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> list[ValidatedOutputRead]:
    try:
        return _service(db, data_dir, owner_id=owner_id).read(workflow_id).outputs
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/verification", response_model=ValidatedVerificationRead)
def get_validated_verification(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedVerificationRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).verification(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/independent-review", response_model=ValidatedWorkflowRead)
def submit_independent_review(
    workflow_id: str,
    payload: ValidatedIndependentReviewSubmit,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedWorkflowRead:
    service = _service(db, data_dir, owner_id=owner_id)
    if not isinstance(service, ExecutableCadQueryWorkflowService):
        raise HTTPException(status_code=404, detail="independent review not found")
    try:
        return service.record_independent_review(
            workflow_id,
            payload.model_dump(mode="json"),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/artifacts", response_model=list[ValidatedArtifactRead])
def list_validated_artifacts(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> list[ValidatedArtifactRead]:
    try:
        return _service(db, data_dir, owner_id=owner_id).artifacts(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/artifacts/{artifact_id}/download")
def download_validated_artifact(
    workflow_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> FileResponse:
    try:
        resolved = _service(db, data_dir, owner_id=owner_id).resolve_artifact(workflow_id, artifact_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if resolved is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    path, media_type = resolved
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/workflows/{workflow_id}/accept", response_model=ValidatedWorkflowRead)
def accept_validated_candidate(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ValidatedWorkflowRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).accept_candidate(workflow_id, idempotency_key=idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/revision", response_model=ValidatedWorkflowRead, status_code=201)
async def start_validated_revision(
    workflow_id: str,
    payload: ValidatedBoundedRevision,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: object = Depends(get_workflow_ai_provider),
    cad_runner: object = Depends(get_cad_runner),
    owner_id: str = Depends(get_validated_actor_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ValidatedWorkflowRead:
    try:
        return await _service(db, data_dir, ai_provider, cad_runner, owner_id).start_bounded_revision(workflow_id, payload, idempotency_key=idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}/diagnostics", response_model=ValidatedDiagnosticsRead)
def get_validated_diagnostics(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedDiagnosticsRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).diagnostics(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/continue", response_model=ValidatedWorkflowRead)
def continue_validated_generation(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedWorkflowRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).continue_generation(workflow_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/package", response_model=ValidatedWorkflowRead)
def create_validated_package(
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ValidatedWorkflowRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).create_package(workflow_id, idempotency_key=idempotency_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}", response_model=ValidatedWorkflowRead)
def get_project_validated_workflow(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedWorkflowRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).read(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/requirements", response_model=ValidatedRequirementsRead)
def get_project_validated_requirements(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedRequirementsRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).requirements(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/plan", response_model=ValidatedPlanRead)
def get_project_validated_plan(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedPlanRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).plan(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/outputs", response_model=list[ValidatedOutputRead])
def get_project_validated_outputs(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> list[ValidatedOutputRead]:
    try:
        return _service(db, data_dir, owner_id=owner_id).read(workflow_id, project_id=project_id).outputs
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/verification", response_model=ValidatedVerificationRead)
def get_project_validated_verification(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedVerificationRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).verification(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/diagnostics", response_model=ValidatedDiagnosticsRead)
def get_project_validated_diagnostics(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedDiagnosticsRead:
    try:
        return _service(db, data_dir, owner_id=owner_id).diagnostics(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/artifacts", response_model=list[ValidatedArtifactRead])
def list_project_validated_artifacts(
    project_id: str,
    workflow_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> list[ValidatedArtifactRead]:
    try:
        return _service(db, data_dir, owner_id=owner_id).artifacts(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/projects/{project_id}/designs/{workflow_id}/artifacts/{artifact_id}/download")
def download_project_validated_artifact(
    project_id: str,
    workflow_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> FileResponse:
    try:
        resolved = _service(db, data_dir, owner_id=owner_id).resolve_artifact(
            workflow_id,
            artifact_id,
            project_id=project_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if resolved is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    path, media_type = resolved
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/projects/{project_id}/designs/{workflow_id}/revisions/{revision_id}", response_model=ValidatedWorkflowRead)
def get_project_validated_revision(
    project_id: str,
    workflow_id: str,
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    owner_id: str = Depends(get_validated_actor_id),
) -> ValidatedWorkflowRead:
    try:
        result = _service(db, data_dir, owner_id=owner_id).read(workflow_id, project_id=project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if result.revision_id != revision_id and result.parent_revision_id != revision_id:
        raise HTTPException(status_code=404, detail="validated revision not found")
    return result
