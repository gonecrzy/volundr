from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.session import get_db
from app.schemas.project import (
    ManualRevisionCreate,
    GenerationCreate,
    ProjectCreate,
    ProjectMessageRead,
    ProjectRead,
    ProjectSave,
    ProjectUpdate,
    RevisionRead,
)
from app.schemas.printability import PrintabilityProfile, PrintabilityReport
from app.services.ai.provider import AiProvider
from app.services.cad.runner import OpenScadCliRunner
from app.services.printability.inspector import inspect_printability
from app.services.projects.service import ProjectService

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    return service.create_project(payload)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectRead]:
    service = ProjectService(db=db)
    return service.list_projects()


@router.post("/projects/draft", response_model=ProjectRead, status_code=201)
def create_draft_project(
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ProjectRead:
    service = ProjectService(db=db, data_dir=data_dir)
    return service.create_draft_project()


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.update_project(project_id, payload)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.post("/projects/{project_id}/save", response_model=ProjectRead)
def save_project(
    project_id: str,
    payload: ProjectSave,
    db: Session = Depends(get_db),
) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.save_project(project_id, payload)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.post("/projects/{project_id}/archive", response_model=ProjectRead)
def archive_project(project_id: str, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.archive_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@router.get("/projects/{project_id}/messages", response_model=list[ProjectMessageRead])
def list_project_messages(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[ProjectMessageRead]:
    service = ProjectService(db=db)
    messages = service.list_project_messages(project_id)
    if messages is None:
        raise HTTPException(status_code=404, detail="project not found")
    return messages


@router.post("/projects/{project_id}/revisions", response_model=RevisionRead, status_code=201)
async def create_manual_revision(
    project_id: str,
    payload: ManualRevisionCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: OpenScadCliRunner = Depends(get_cad_runner),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir, cad_runner=cad_runner)
    revision = await service.create_manual_revision(project_id, payload)
    if revision is None:
        raise HTTPException(status_code=404, detail="project not found")
    return revision


@router.post("/projects/{project_id}/generate", response_model=RevisionRead, status_code=201)
async def generate_initial_revision(
    project_id: str,
    payload: GenerationCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: OpenScadCliRunner = Depends(get_cad_runner),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> RevisionRead:
    service = ProjectService(
        db=db,
        data_dir=data_dir,
        cad_runner=cad_runner,
        ai_provider=ai_provider,
    )
    try:
        revision = await service.generate_initial_revision(project_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if revision is None:
        raise HTTPException(status_code=404, detail="project not found")
    return revision


@router.get("/projects/{project_id}/revisions", response_model=list[RevisionRead])
def list_revisions(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[RevisionRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    if service.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return service.list_revisions(project_id)


@router.get("/revisions/{revision_id}/source")
def get_revision_source(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    source_path = service.resolve_revision_source(revision_id)
    if source_path is None:
        raise HTTPException(status_code=404, detail="revision source not found")
    return FileResponse(source_path, media_type="text/plain", filename="model.scad")


@router.get("/revisions/{revision_id}/compile-log")
def get_revision_compile_log(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> PlainTextResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    compile_log = service.read_revision_compile_log(revision_id)
    if compile_log is None:
        raise HTTPException(status_code=404, detail="revision compile log not found")
    return PlainTextResponse(compile_log, media_type="text/plain")


@router.get("/revisions/{revision_id}/ai-output")
def get_revision_ai_output(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> PlainTextResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    ai_output = service.read_revision_ai_output(revision_id)
    if ai_output is None:
        raise HTTPException(status_code=404, detail="revision AI output not found")
    return PlainTextResponse(ai_output, media_type="text/plain")


@router.get("/revisions/{revision_id}/diff")
def get_revision_diff(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> PlainTextResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    diff = service.read_revision_diff(revision_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="revision diff not found")
    return PlainTextResponse(diff, media_type="text/plain")


@router.get("/revisions/{revision_id}/stl")
def get_revision_stl(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    stl_path = service.resolve_revision_stl(revision_id)
    if stl_path is None:
        raise HTTPException(status_code=404, detail="revision STL not found")
    return FileResponse(stl_path, media_type="model/stl", filename="model.stl")


@router.post("/revisions/{revision_id}/printability", response_model=PrintabilityReport)
def inspect_revision_printability(
    revision_id: str,
    payload: PrintabilityProfile,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> PrintabilityReport:
    service = ProjectService(db=db, data_dir=data_dir)
    stl_path = service.resolve_revision_stl(revision_id)
    if stl_path is None:
        raise HTTPException(status_code=404, detail="revision STL not found")
    try:
        return inspect_printability(stl_path, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/revisions/{revision_id}/restore", response_model=ProjectRead)
def restore_revision(revision_id: str, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.restore_revision(revision_id)
    if project is None:
        raise HTTPException(status_code=404, detail="successful revision not found")
    return project
