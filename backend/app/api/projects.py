from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_cad_runner, get_data_dir
from app.db.session import get_db
from app.schemas.project import (
    ManualRevisionCreate,
    ProjectCreate,
    ProjectRead,
    RevisionRead,
)
from app.services.cad.runner import OpenScadCliRunner
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


@router.get("/projects/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


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
) -> PlainTextResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    source = service.read_revision_source(revision_id)
    if source is None:
        raise HTTPException(status_code=404, detail="revision source not found")
    return PlainTextResponse(source, media_type="text/plain")


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
