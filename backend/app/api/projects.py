from pathlib import Path
from typing import Any

import json
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_ai_provider, get_cad_runner, get_data_dir
from app.db.session import get_db
from app.schemas.project import (
    ClarificationAnswersCreate,
    ChatMessageCreate,
    ChatWorkflowResponse,
    ClarificationQuestionRead,
    ConfigurationChangeCreate,
    ConfigurationChangeRead,
    ConfigurationOverrideManifestRead,
    ConfigurationParameterRead,
    ConfigurationPresetCreate,
    ConfigurationPresetRead,
    ComponentRevisionSummaryRead,
    DesignPlanClarificationQuestionRead,
    DesignSpecificationRead,
    DesignPlanRead,
    GenerationAttemptEvidenceRead,
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
    RevisionComplianceResultRead,
    RevisionPlanClarificationQuestionRead,
    RevisionPlanCreate,
    RevisionPlanRead,
    RevisionSuccessResultRead,
    ValidationFindingDismiss,
    ValidationFindingRead,
    RequirementExtractionCreate,
)
from app.schemas.printability import (
    PrintabilityProfile,
    PrintabilityReport,
    SavedPrintabilityProfileRead,
)
from app.schemas.workflow import (
    FrontendWorkflowEventBatchCreate,
    FrontendWorkflowEventBatchRead,
    WorkflowEventRead,
    WorkflowRunRead,
)
from app.services.ai.provider import AiProvider
from app.services.printability.inspector import inspect_printability
from app.services.printability.profiles import PrintabilityProfileService
from app.services.projects.service import ProjectService
from app.services.projects.chat_workflow import ChatWorkflowService
from app.models.workflow import FrontendWorkflowEvent, WorkflowEvent, WorkflowRun
from app.services.workflow.comparison import WorkflowRunComparisonService
from app.services.workflow.debug_bundle import WorkflowDebugBundleService
from app.services.workflow.diagnosis import WorkflowDiagnosisService
from app.services.workflow.redaction import RedactionError
from app.services.workflow.stage_trace import WorkflowStageTraceService
from app.models.generation_attempt import GenerationAttempt
from app.models.project import Project

router = APIRouter(prefix="/api", tags=["projects"])
_frontend_event_rate_window: dict[str, deque[float]] = defaultdict(deque)
_FRONTEND_EVENT_RATE_LIMIT = 120
_FRONTEND_EVENT_RATE_SECONDS = 60.0


def _check_frontend_event_rate_limit(frontend_session_id: str, event_count: int) -> None:
    now = time.monotonic()
    window = _frontend_event_rate_window[frontend_session_id]
    while window and now - window[0] > _FRONTEND_EVENT_RATE_SECONDS:
        window.popleft()
    if len(window) + event_count > _FRONTEND_EVENT_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="frontend workflow event rate limit exceeded")
    for _ in range(event_count):
        window.append(now)


def _set_latest_workflow_headers(response: Response, db: Session, project_id: str) -> None:
    run = db.scalar(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.updated_at.desc(), WorkflowRun.started_at.desc())
    )
    if run is None:
        return
    _set_workflow_headers(response, run)


def _set_workflow_headers(response: Response, run: WorkflowRun) -> None:
    response.headers["X-Workflow-Run-Id"] = run.id
    response.headers["X-Workflow-Root-Run-Id"] = run.root_workflow_run_id or run.id
    response.headers["X-Workflow-Correlation-Id"] = run.correlation_id


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
def get_project(
    project_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> ProjectRead:
    service = ProjectService(db=db)
    project = service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    _set_latest_workflow_headers(response, db, project_id)
    return project


@router.get("/projects/{project_id}/workflow-runs", response_model=list[WorkflowRunRead])
def list_project_workflow_runs(
    project_id: str,
    db: Session = Depends(get_db),
) -> list[WorkflowRunRead]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    runs = db.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project_id)
        .order_by(WorkflowRun.started_at.asc(), WorkflowRun.id.asc())
    ).all()
    return [
        WorkflowRunRead(
            id=run.id,
            project_id=run.project_id,
            workflow_type=run.workflow_type,
            parent_workflow_run_id=run.parent_workflow_run_id,
            root_workflow_run_id=run.root_workflow_run_id,
            correlation_id=run.correlation_id,
            status=run.status,
            logging_mode=run.logging_mode,
            started_at=run.started_at,
            completed_at=run.completed_at,
            prompt_versions=json.loads(run.prompt_versions_json),
        )
        for run in runs
    ]


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


@router.post("/projects/{project_id}/chat", response_model=ChatWorkflowResponse)
async def submit_chat_message(
    project_id: str,
    payload: ChatMessageCreate,
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
    cad_runner: Any = Depends(get_cad_runner),
) -> ChatWorkflowResponse:
    service = ChatWorkflowService(
        db=db,
        data_dir=data_dir,
        ai_provider=ai_provider,
        cad_runner=cad_runner,
    )
    try:
        result = await service.submit(project_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.workflow_run_id:
        run = db.get(WorkflowRun, result.workflow_run_id)
        if run is not None:
            _set_workflow_headers(response, run)
    return result


@router.get("/workflow-runs/{workflow_run_id}", response_model=WorkflowRunRead)
def get_workflow_run(
    workflow_run_id: str,
    db: Session = Depends(get_db),
) -> WorkflowRunRead:
    run = db.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    return WorkflowRunRead(
        id=run.id,
        project_id=run.project_id,
        workflow_type=run.workflow_type,
        parent_workflow_run_id=run.parent_workflow_run_id,
        root_workflow_run_id=run.root_workflow_run_id,
        correlation_id=run.correlation_id,
        status=run.status,
        logging_mode=run.logging_mode,
        started_at=run.started_at,
        completed_at=run.completed_at,
        prompt_versions=json.loads(run.prompt_versions_json),
    )


@router.get("/workflow-runs/{workflow_run_id}/events", response_model=list[WorkflowEventRead])
def list_workflow_events(
    workflow_run_id: str,
    db: Session = Depends(get_db),
) -> list[WorkflowEventRead]:
    if db.get(WorkflowRun, workflow_run_id) is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    events = db.scalars(
        select(WorkflowEvent)
        .where(WorkflowEvent.workflow_run_id == workflow_run_id)
        .order_by(WorkflowEvent.sequence_number.asc())
    )
    return [
        WorkflowEventRead(
            id=event.id,
            workflow_run_id=event.workflow_run_id,
            sequence_number=event.sequence_number,
            occurred_at=event.occurred_at,
            recorded_at=event.recorded_at,
            stage=event.stage,
            event_type=event.event_type,
            severity=event.severity,
            blocking=event.blocking,
            message=event.message,
            rule_id=event.rule_id,
        )
        for event in events
    ]


@router.get("/workflow-runs/{workflow_run_id}/diagnosis")
def get_workflow_diagnosis(
    workflow_run_id: str,
    db: Session = Depends(get_db),
) -> dict:
    try:
        diagnosis = WorkflowDiagnosisService(db=db).diagnose(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "schema_version": diagnosis.schema_version,
        "workflow_run_id": diagnosis.workflow_run_id,
        "root_cause": diagnosis.root_cause,
        "repairs": diagnosis.repairs,
        "downstream_effects": diagnosis.downstream_effects,
        "final_outcome": diagnosis.final_outcome,
    }


@router.get("/workflow-runs/{workflow_run_id}/stage-trace")
def get_workflow_stage_trace(workflow_run_id: str, db: Session = Depends(get_db)) -> dict:
    try:
        return WorkflowStageTraceService(db=db).build_trace(workflow_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflow-runs/{baseline_workflow_run_id}/compare/{candidate_workflow_run_id}")
def compare_workflow_runs(
    baseline_workflow_run_id: str,
    candidate_workflow_run_id: str,
    db: Session = Depends(get_db),
) -> dict:
    try:
        return WorkflowRunComparisonService(db=db).compare(
            baseline_workflow_run_id,
            candidate_workflow_run_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/workflow-runs/{workflow_run_id}/debug-bundle.zip")
def get_workflow_debug_bundle(
    workflow_run_id: str,
    include_geometry: bool = False,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    try:
        bundle_path = WorkflowDebugBundleService(db=db, data_dir=data_dir).build_bundle(
            workflow_run_id,
            include_geometry=include_geometry,
        )
    except RedactionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        bundle_path,
        media_type="application/zip",
        filename=f"workflow-debug-{workflow_run_id}.zip",
    )


@router.post(
    "/workflow/frontend-events",
    response_model=FrontendWorkflowEventBatchRead,
    status_code=201,
)
def record_frontend_workflow_events(
    payload: FrontendWorkflowEventBatchCreate,
    db: Session = Depends(get_db),
) -> FrontendWorkflowEventBatchRead:
    run = db.get(WorkflowRun, payload.workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    if run.project_id != payload.project_id or run.correlation_id != payload.correlation_id:
        raise HTTPException(status_code=409, detail="frontend event workflow context mismatch")
    _check_frontend_event_rate_limit(payload.frontend_session_id, len(payload.events))
    for event in payload.events:
        db.add(
            FrontendWorkflowEvent(
                project_id=payload.project_id,
                workflow_run_id=payload.workflow_run_id,
                correlation_id=payload.correlation_id,
                frontend_session_id=payload.frontend_session_id,
                route=event.route,
                action_name=event.action_name,
                user_visible_state=event.user_visible_state,
                backend_request_id=event.backend_request_id,
                occurred_at=event.timestamp,
                metadata_json=json.dumps(event.metadata, sort_keys=True),
            )
        )
    db.commit()
    return FrontendWorkflowEventBatchRead(accepted_count=len(payload.events))


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
    response: Response,
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
    _set_latest_workflow_headers(response, db, project_id)
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
    "/projects/{project_id}/revision-plan",
    response_model=RevisionPlanRead | None,
)
def get_current_revision_plan(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    plan = service.get_current_revision_plan(project_id)
    return plan


@router.get(
    "/projects/{project_id}/configuration/parameters",
    response_model=list[ConfigurationParameterRead],
)
def list_configuration_parameters(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ConfigurationParameterRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    parameters = service.list_configuration_parameters(project_id)
    if parameters is None:
        raise HTTPException(status_code=404, detail="configurable accepted revision not found")
    return parameters


@router.get(
    "/projects/{project_id}/configuration/presets",
    response_model=list[ConfigurationPresetRead],
)
def list_configuration_presets(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[ConfigurationPresetRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    presets = service.list_configuration_presets(project_id)
    if presets is None:
        raise HTTPException(status_code=404, detail="configurable accepted revision not found")
    return presets


@router.post(
    "/projects/{project_id}/configuration/presets",
    response_model=ConfigurationPresetRead,
    status_code=201,
)
def create_configuration_preset(
    project_id: str,
    payload: ConfigurationPresetCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ConfigurationPresetRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        preset = service.create_configuration_preset(project_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if preset is None:
        raise HTTPException(status_code=404, detail="configurable accepted revision not found")
    return preset


@router.post(
    "/projects/{project_id}/configuration/preview",
    response_model=ConfigurationChangeRead,
    status_code=201,
)
def preview_configuration_change(
    project_id: str,
    payload: ConfigurationChangeCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ConfigurationChangeRead:
    service = ProjectService(db=db, data_dir=data_dir)
    change = service.preview_configuration_change(project_id, payload)
    if change is None:
        raise HTTPException(status_code=404, detail="configurable accepted revision not found")
    return change


@router.get(
    "/configuration-changes/{configuration_change_id}",
    response_model=ConfigurationChangeRead,
)
def get_configuration_change(
    configuration_change_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ConfigurationChangeRead:
    service = ProjectService(db=db, data_dir=data_dir)
    change = service.get_configuration_change(configuration_change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="configuration change not found")
    return change


@router.get(
    "/configuration-changes/{configuration_change_id}/override-manifest",
    response_model=ConfigurationOverrideManifestRead,
)
def get_configuration_override_manifest(
    configuration_change_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ConfigurationOverrideManifestRead:
    service = ProjectService(db=db, data_dir=data_dir)
    manifest = service.read_configuration_override_manifest(configuration_change_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="configuration change not found")
    return manifest


@router.post(
    "/configuration-changes/{configuration_change_id}/generate",
    response_model=RevisionRead,
    status_code=201,
)
async def generate_from_configuration_change(
    configuration_change_id: str,
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: Any = Depends(get_cad_runner),
) -> RevisionRead:
    service = ProjectService(db=db, data_dir=data_dir, cad_runner=cad_runner)
    try:
        revision = await service.generate_from_configuration_change(configuration_change_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if revision is None:
        raise HTTPException(status_code=404, detail="configuration change not found")
    _set_latest_workflow_headers(response, db, revision.project_id)
    return revision


@router.get(
    "/revision-plans/{revision_plan_id}",
    response_model=RevisionPlanRead,
)
def get_revision_plan(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    plan = service.get_revision_plan(revision_plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return plan


@router.post(
    "/projects/{project_id}/revision-plans",
    response_model=RevisionPlanRead,
    status_code=201,
)
async def create_revision_plan(
    project_id: str,
    payload: RevisionPlanCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        plan = await service.create_revision_plan(project_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="project not found")
    return plan


@router.post("/revision-plans/{revision_plan_id}/approve", response_model=RevisionPlanRead)
def approve_revision_plan(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        plan = service.approve_revision_plan(revision_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return plan


@router.post("/revision-plans/{revision_plan_id}/reject", response_model=RevisionPlanRead)
def reject_revision_plan(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir)
    try:
        plan = service.reject_revision_plan(revision_plan_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return plan


@router.get(
    "/revision-plans/{revision_plan_id}/clarification-questions",
    response_model=list[RevisionPlanClarificationQuestionRead],
)
def list_revision_plan_clarification_questions(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[RevisionPlanClarificationQuestionRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    questions = service.list_revision_plan_clarification_questions(revision_plan_id)
    if questions is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return questions


@router.post(
    "/revision-plans/{revision_plan_id}/clarification-answers",
    response_model=RevisionPlanRead,
    status_code=201,
)
async def submit_revision_plan_clarification_answers(
    revision_plan_id: str,
    payload: ClarificationAnswersCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> RevisionPlanRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        plan = await service.submit_revision_plan_clarification_answers(revision_plan_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if plan is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return plan


@router.post(
    "/revision-plans/{revision_plan_id}/generate",
    response_model=RevisionRead,
    status_code=201,
)
async def generate_from_revision_plan(
    revision_plan_id: str,
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: Any = Depends(get_cad_runner),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> RevisionRead:
    service = ProjectService(
        db=db,
        data_dir=data_dir,
        cad_runner=cad_runner,
        ai_provider=ai_provider,
    )
    try:
        revision = await service.generate_from_revision_plan(revision_plan_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if revision is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    _set_latest_workflow_headers(response, db, revision.project_id)
    return revision


@router.get(
    "/revision-plans/{revision_plan_id}/compliance-result",
    response_model=RevisionComplianceResultRead,
)
def get_revision_compliance_result(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> RevisionComplianceResultRead:
    service = ProjectService(db=db, data_dir=data_dir)
    result = service.get_revision_compliance_result(revision_plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="revision compliance result not found")
    return result


@router.get("/revision-plans/{revision_plan_id}/component-scope")
def get_revision_plan_component_scope(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    service = ProjectService(db=db, data_dir=data_dir)
    result = service.get_component_revision_scope(revision_plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="component revision scope not found")
    return result


@router.get("/revision-plans/{revision_plan_id}/module-ownership-comparison")
def get_revision_plan_module_ownership_comparison(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    service = ProjectService(db=db, data_dir=data_dir)
    result = service.get_revision_compliance_result(revision_plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="revision compliance result not found")
    return {
        "revision_plan_id": revision_plan_id,
        "base_module_fingerprints": result.metadata.get("base_module_fingerprints", {}),
        "revised_module_fingerprints": result.metadata.get("revised_module_fingerprints", {}),
        "findings": result.findings,
    }


@router.get(
    "/revision-plans/{revision_plan_id}/component-revision-summary",
    response_model=ComponentRevisionSummaryRead,
)
def get_component_revision_summary_for_plan(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ComponentRevisionSummaryRead:
    service = ProjectService(db=db, data_dir=data_dir)
    result = service.get_component_revision_summary_by_plan(revision_plan_id)
    if result is None:
        raise HTTPException(status_code=404, detail="component revision summary not found")
    return result


@router.get(
    "/revisions/{revision_id}/component-revision-summary",
    response_model=ComponentRevisionSummaryRead | None,
)
def get_component_revision_summary_for_revision(
    revision_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> ComponentRevisionSummaryRead | None:
    service = ProjectService(db=db, data_dir=data_dir)
    result = service.get_component_revision_summary_by_revision(revision_id)
    return result


@router.get(
    "/revision-plans/{revision_plan_id}/success-results",
    response_model=list[RevisionSuccessResultRead],
)
def list_revision_success_results(
    revision_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[RevisionSuccessResultRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    results = service.list_revision_success_results(revision_plan_id)
    if results is None:
        raise HTTPException(status_code=404, detail="Revision Plan not found")
    return results


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
    response: Response,
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
    _set_latest_workflow_headers(response, db, plan.project_id)
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
    "/design-plans/{design_plan_id}/clarification-questions",
    response_model=list[DesignPlanClarificationQuestionRead],
)
def list_design_plan_clarification_questions(
    design_plan_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[DesignPlanClarificationQuestionRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    questions = service.list_design_plan_clarification_questions(design_plan_id)
    if questions is None:
        raise HTTPException(status_code=404, detail="Design Plan not found")
    return questions


@router.post(
    "/design-plans/{design_plan_id}/clarification-answers",
    response_model=DesignPlanRead,
    status_code=201,
)
async def submit_design_plan_clarification_answers(
    design_plan_id: str,
    payload: ClarificationAnswersCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    ai_provider: AiProvider = Depends(get_ai_provider),
) -> DesignPlanRead:
    service = ProjectService(db=db, data_dir=data_dir, ai_provider=ai_provider)
    try:
        plan = await service.submit_design_plan_clarification_answers(design_plan_id, payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
    cad_runner: Any = Depends(get_cad_runner),
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
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: Any = Depends(get_cad_runner),
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
    _set_latest_workflow_headers(response, db, revision.project_id)
    return revision


@router.post("/projects/{project_id}/revisions", response_model=RevisionRead, status_code=201)
async def create_manual_revision(
    project_id: str,
    payload: ManualRevisionCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: Any = Depends(get_cad_runner),
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
    cad_runner: Any = Depends(get_cad_runner),
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


def _artifact_size_for_token_estimate(data_dir: Path, artifact_path: str | None) -> int | None:
    if not artifact_path:
        return None
    relative_path = Path(artifact_path)
    if relative_path.is_absolute():
        return None
    root = data_dir.resolve()
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    try:
        return resolved.stat().st_size
    except OSError:
        return None


def _estimated_tokens(data_dir: Path, artifact_path: str | None) -> int | None:
    size = _artifact_size_for_token_estimate(data_dir, artifact_path)
    return None if size is None else max(1, (size + 3) // 4)


@router.get(
    "/projects/{project_id}/generation-attempts",
    response_model=list[GenerationAttemptEvidenceRead],
)
def list_generation_attempt_evidence(
    project_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[GenerationAttemptEvidenceRead]:
    service = ProjectService(db=db, data_dir=data_dir)
    if service.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    attempts = db.scalars(
        select(GenerationAttempt)
        .where(GenerationAttempt.project_id == project_id)
        .order_by(GenerationAttempt.attempt_number.asc(), GenerationAttempt.started_at.asc())
    ).all()
    evidence: list[GenerationAttemptEvidenceRead] = []
    for attempt in attempts:
        duration_ms = None
        if attempt.completed_at is not None:
            duration_ms = max(
                0,
                round((attempt.completed_at - attempt.started_at).total_seconds() * 1000),
            )
        evidence.append(
            GenerationAttemptEvidenceRead(
                attempt_id=attempt.id,
                attempt_number=attempt.attempt_number,
                provider=attempt.provider_id,
                model=attempt.model_id,
                status=attempt.status,
                failure_class=attempt.failure_class,
                prompt_version=attempt.prompt_version,
                started_at=attempt.started_at,
                completed_at=attempt.completed_at,
                duration_ms=duration_ms,
                provider_usage=(
                    json.loads(attempt.provider_usage_json)
                    if attempt.provider_usage_json
                    else None
                ),
                provider_request_id=attempt.provider_request_id,
                routing_metadata=(
                    json.loads(attempt.routing_metadata_json)
                    if attempt.routing_metadata_json
                    else {}
                ),
                provider_latency_ms=attempt.provider_latency_ms,
                estimated_prompt_tokens=_estimated_tokens(data_dir, attempt.prompt_path),
                estimated_output_tokens=_estimated_tokens(data_dir, attempt.raw_output_path),
                resulting_revision_id=attempt.resulting_revision_id,
            )
        )
    return evidence


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
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
    cad_runner: Any = Depends(get_cad_runner),
) -> RevisionOutputRead:
    service = ProjectService(db=db, data_dir=data_dir, cad_runner=cad_runner)
    try:
        output = await service.retry_revision_output(output_artifact_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if output is None:
        raise HTTPException(status_code=404, detail="revision output not found")
    project_id = db.scalar(select(WorkflowEvent.project_id).where(WorkflowEvent.revision_output_id == output.id))
    if project_id is not None:
        _set_latest_workflow_headers(response, db, project_id)
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
    response: Response,
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
    acceptance_run = db.scalar(
        select(WorkflowRun)
        .join(WorkflowEvent, WorkflowEvent.workflow_run_id == WorkflowRun.id)
        .where(
            WorkflowEvent.revision_id == candidate.id,
            WorkflowEvent.event_type == "candidate.accepted",
        )
        .order_by(WorkflowEvent.sequence_number.desc())
    )
    if acceptance_run is not None:
        _set_workflow_headers(response, acceptance_run)
    else:
        _set_latest_workflow_headers(response, db, candidate.project_id)
    return candidate


@router.post("/candidates/{revision_id}/reject", response_model=RevisionRead)
def reject_candidate_revision(
    revision_id: str,
    response: Response,
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
    _set_latest_workflow_headers(response, db, candidate.project_id)
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
    return FileResponse(source_path, media_type="text/plain", filename=source_path.name)


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


@router.get("/revision-outputs/{output_artifact_id}/step")
def get_revision_output_step(
    output_artifact_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    output = service.get_revision_output(output_artifact_id)
    step_path = service.resolve_revision_output_step(output_artifact_id)
    if output is None or step_path is None:
        raise HTTPException(status_code=404, detail="revision output STEP not found")
    return FileResponse(step_path, media_type="model/step", filename=Path(output.filename).with_suffix(".step").name)


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
    response: Response,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    service = ProjectService(db=db, data_dir=data_dir)
    export_path = service.build_revision_export(revision_id)
    if export_path is None:
        raise HTTPException(status_code=404, detail="revision not found")
    project_id = db.scalar(select(WorkflowEvent.project_id).where(WorkflowEvent.revision_id == revision_id))
    headers = {}
    if project_id is not None:
        _set_latest_workflow_headers(response, db, project_id)
        headers = {
            "X-Workflow-Run-Id": response.headers.get("X-Workflow-Run-Id", ""),
            "X-Workflow-Root-Run-Id": response.headers.get("X-Workflow-Root-Run-Id", ""),
            "X-Workflow-Correlation-Id": response.headers.get("X-Workflow-Correlation-Id", ""),
        }
    return FileResponse(
        export_path,
        media_type="application/zip",
        filename="volundr-project.zip",
        headers={key: value for key, value in headers.items() if value},
    )


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
