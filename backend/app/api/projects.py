from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.session import get_db
from app.schemas.project import (
    ClarificationAnswersCreate,
    ClarificationQuestionRead,
    DesignSpecificationRead,
    DesignPlanRead,
    GeometricAnalysisRead,
    ManualRevisionCreate,
    GenerationCreate,
    ProjectCreate,
    ProjectMessageRead,
    ProjectRead,
    ProjectSave,
    ProjectUpdate,
    RevisionRead,
    RevisionOutputRead,
    ValidationFindingDismiss,
    ValidationFindingRead,
    RequirementExtractionCreate,
)
from app.schemas.printability import (
    PrintabilityProfile,
    PrintabilityReport,
    SavedPrintabilityProfileRead,
)
from app.services.ai.provider import AiProvider
from app.services.cad.runner import OpenScadCliRunner
from app.services.printability.inspector import inspect_printability
from app.services.printability.profiles import PrintabilityProfileService
from app.services.projects.service import ProjectService

router = APIRouter(prefix="/api", tags=["projects"])


@router.post("/projects", response_model=ProjectRead, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectRead:
    service = ProjectService(db=db)
    return service.create_project(payload)


@router.get("/projects", response_model=list[ProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ProjectRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    return service.list_projects()


@router.get("/printability-profiles", response_model=list[SavedPrintabilityProfileRead])
def list_printability_profiles(
    db: Session = Depends(get_db),
) -> list[SavedPrintabilityProfileRead]:
    service = PrintabilityProfileService(db=db)
    return service.list_profiles()


@router.post(
    "/printability-profiles",
    response_model=SavedPrintabilityProfileRead,
    status_code=201,
)
def create_printability_profile(
    payload: PrintabilityProfile,
    db: Session = Depends(get_db),
) -> SavedPrintabilityProfileRead:
    service = PrintabilityProfileService(db=db)
    return service.create_profile(payload)


@router.patch(
    "/printability-profiles/{profile_id}",
    response_model=SavedPrintabilityProfileRead,
)
def update_printability_profile(
    profile_id: str,
    payload: PrintabilityProfile,
    db: Session = Depends(get_db),
) -> SavedPrintabilityProfileRead:
    service = PrintabilityProfileService(db=db)
    profile = service.update_profile(profile_id, payload)
    if profile is None:
        raise HTTPException(status_code=404, detail="printability profile not found")
    return profile


@router.delete("/printability-profiles/{profile_id}", status_code=204)
def delete_printability_profile(
    profile_id: str,
    db: Session = Depends(get_db),
) -> Response:
    service = PrintabilityProfileService(db=db)
    if not service.delete_profile(profile_id):
        raise HTTPException(status_code=404, detail="printability profile not found")
    return Response(status_code=204)


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


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> Response:
    service = ProjectService(db=db, data_dir=data_dir)
    if not service.delete_project(project_id):
        raise HTTPException(status_code=404, detail="project not found")
    return Response(status_code=204)


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


@router.get("/projects/{project_id}/active-revision", response_model=RevisionRead)
def get_active_revision(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir)
    revision = service.get_active_revision(project_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="active accepted revision not found")
    return revision


@router.post(
    "/projects/{project_id}/requirements",
    response_model=DesignSpecificationRead,
    status_code=201,
)
async def extract_project_requirements(
    project_id: str,
    payload: RequirementExtractionCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> DesignSpecificationRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        specification = await service.extract_requirements(project_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if specification is None:
        raise HTTPException(status_code=404, detail="project not found")
    return specification


@router.get(
    "/projects/{project_id}/design-specification",
    response_model=DesignSpecificationRead,
)
def get_current_design_specification(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignSpecificationRead:
    service = ProjectService(db=db, data_dir=data_dir)
    specification = service.get_current_design_specification(project_id)
    if specification is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return specification


@router.get(
    "/design-specifications/{specification_id}",
    response_model=DesignSpecificationRead,
)
def get_design_specification(
    specification_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignSpecificationRead:
    service = ProjectService(db=db, data_dir=data_dir)
    specification = service.get_design_specification(specification_id)
    if specification is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return specification


@router.get(
    "/projects/{project_id}/design-plan",
    response_model=DesignPlanRead,
)
def get_current_design_plan(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    plan = service.get_current_design_plan(project_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return plan


@router.get(
    "/design-plans/{design_plan_id}",
    response_model=DesignPlanRead,
)
def get_design_plan(
    design_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    plan = service.get_design_plan(design_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return plan


@router.post(
    "/design-specifications/{specification_id}/design-plan",
    response_model=DesignPlanRead,
    status_code=201,
)
async def create_design_plan_from_specification(
    specification_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        plan = await service.create_design_plan_from_specification(specification_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return plan


@router.post("/design-plans/{design_plan_id}/approve", response_model=DesignPlanRead)
def approve_design_plan(
    design_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        plan = service.approve_design_plan(design_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return plan


@router.post("/design-plans/{design_plan_id}/reject", response_model=DesignPlanRead)
def reject_design_plan(
    design_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        plan = service.reject_design_plan(design_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return plan


@router.get(
    "/design-specifications/{specification_id}/clarification-questions",
    response_model=list[ClarificationQuestionRead],
)
def list_clarification_questions(
    specification_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ClarificationQuestionRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    questions = service.list_clarification_questions(specification_id)
    if questions is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return questions


@router.post(
    "/design-specifications/{specification_id}/clarification-answers",
    response_model=DesignSpecificationRead,
    status_code=201,
)
async def submit_clarification_answers(
    specification_id: str,
    payload: ClarificationAnswersCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> DesignSpecificationRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        specification = await service.submit_clarification_answers(specification_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if specification is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return specification


@router.post(
    "/design-specifications/{specification_id}/generate",
    response_model=RevisionRead,
    status_code=201,
)
async def generate_from_design_specification(
    specification_id: str,
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
        revision = await service.generate_from_design_specification(specification_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if revision is None:
        raise HTTPException(status_code=404, detail="Design Specification not found")
    return revision


@router.post(
    "/design-plans/{design_plan_id}/generate",
    response_model=RevisionRead,
    status_code=201,
)
async def generate_from_design_plan(
    design_plan_id: str,
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
        revision = await service.generate_from_design_plan(design_plan_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if revision is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return revision


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
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.get("/projects/{project_id}/candidates", response_model=list[RevisionRead])
def list_project_candidates(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[RevisionRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    candidates = service.list_candidates(project_id)
    if candidates is None:
        raise HTTPException(status_code=404, detail="project not found")
    return candidates


@router.get("/candidates/{revision_id}", response_model=RevisionRead)
def get_candidate_revision(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir)
    candidate = service.get_candidate(revision_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate revision not found")
    return candidate


@router.get("/candidates/{revision_id}/findings", response_model=list[ValidationFindingRead])
def list_candidate_validation_findings(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ValidationFindingRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    findings = service.list_validation_findings(revision_id)
    if findings is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return findings


@router.get("/revisions/{revision_id}/outputs", response_model=list[RevisionOutputRead])
def list_revision_outputs(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[RevisionOutputRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    outputs = service.list_revision_outputs(revision_id)
    if outputs is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return outputs


@router.get("/revision-outputs/{output_artifact_id}", response_model=RevisionOutputRead)
def get_revision_output(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionOutputRead:
    service = ProjectService(db=db, data_dir=data_dir)
    output = service.get_revision_output(output_artifact_id)
    if output is None:
        raise HTTPException(status_code=404, detail="revision output not found")
    return output


@router.get(
    "/revision-outputs/{output_artifact_id}/findings",
    response_model=list[ValidationFindingRead],
)
def list_revision_output_findings(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ValidationFindingRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    findings = service.list_revision_output_findings(output_artifact_id)
    if findings is None:
        raise HTTPException(status_code=404, detail="revision output not found")
    return findings


@router.get(
    "/revision-outputs/{output_artifact_id}/geometric-analysis",
    response_model=GeometricAnalysisRead,
)
def get_revision_output_geometric_analysis(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeometricAnalysisRead:
    service = ProjectService(db=db, data_dir=data_dir)
    analysis = service.get_revision_output_geometric_analysis(output_artifact_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="geometric analysis not found")
    return analysis


@router.post("/revision-outputs/{output_artifact_id}/retry", response_model=RevisionOutputRead)
async def retry_revision_output(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: OpenScadCliRunner = Depends(get_cad_runner),
) -> RevisionOutputRead:
    service = ProjectService(db=db, data_dir=data_dir, cad_runner=cad_runner)
    try:
        output = await service.retry_revision_output(output_artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if output is None:
        raise HTTPException(status_code=404, detail="revision output not found")
    return output


@router.get("/candidates/{revision_id}/geometric-analysis", response_model=GeometricAnalysisRead)
def get_candidate_geometric_analysis(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeometricAnalysisRead:
    service = ProjectService(db=db, data_dir=data_dir)
    analysis = service.get_geometric_analysis(revision_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="geometric analysis not found")
    return analysis


@router.post("/candidates/{revision_id}/accept", response_model=RevisionRead)
def accept_candidate_revision(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        candidate = service.accept_candidate(revision_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate revision not found")
    return candidate


@router.post("/candidates/{revision_id}/reject", response_model=RevisionRead)
def reject_candidate_revision(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        candidate = service.reject_candidate(revision_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate revision not found")
    return candidate


@router.post("/validation-findings/{finding_id}/dismiss", response_model=ValidationFindingRead)
def dismiss_validation_finding(
    finding_id: str,
    payload: ValidationFindingDismiss,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ValidationFindingRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        finding = service.dismiss_validation_finding(finding_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if finding is None:
        raise HTTPException(status_code=404, detail="validation finding not found")
    return finding


@router.get(
    "/generation-attempts/{attempt_id}/findings",
    response_model=list[ValidationFindingRead],
)
def list_generation_attempt_findings(
    attempt_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ValidationFindingRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    findings = service.list_generation_attempt_findings(attempt_id)
    if findings is None:
        raise HTTPException(status_code=404, detail="generation attempt not found")
    return findings


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


@router.get("/revision-outputs/{output_artifact_id}/stl")
def get_revision_output_stl(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    output = service.get_revision_output(output_artifact_id)
    stl_path = service.resolve_revision_output_stl(output_artifact_id)
    if output is None or stl_path is None:
        raise HTTPException(status_code=404, detail="revision output STL not found")
    return FileResponse(stl_path, media_type="model/stl", filename=output.filename)


@router.get("/revision-outputs/{output_artifact_id}/compile-log")
def get_revision_output_compile_log(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> PlainTextResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    compile_log = service.read_revision_output_compile_log(output_artifact_id)
    if compile_log is None:
        raise HTTPException(status_code=404, detail="revision output compile log not found")
    return PlainTextResponse(compile_log, media_type="text/plain")


@router.get("/revisions/{revision_id}/output-manifest")
def get_revision_output_manifest(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    service = ProjectService(db=db, data_dir=data_dir)
    manifest = service.read_output_manifest(revision_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="revision output manifest not found")
    return manifest


@router.get("/revisions/{revision_id}/export.zip")
def get_revision_export_zip(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    export_path = service.build_revision_export(revision_id)
    if export_path is None:
        raise HTTPException(status_code=404, detail="revision not found")
    return FileResponse(export_path, media_type="application/zip", filename="volundr-project.zip")


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
