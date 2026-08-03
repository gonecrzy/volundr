from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_dir, require_developer_tools
from app.db.session import get_db
from app.schemas.gemini_benchmark import (
    GeminiBenchmarkClaimCreate,
    GeminiBenchmarkCompletionCreate,
    GeminiBenchmarkExperimentCreate,
    GeminiBenchmarkExperimentRead,
    GeminiBenchmarkFinishCreate,
    GeminiBenchmarkMembershipRead,
    GeminiBenchmarkModelAvailabilityCreate,
    GeminiBenchmarkReportRead,
)
from app.services.gemini_consistency.service import GeminiConsistencyService


router = APIRouter(
    prefix="/api/gemini-consistency",
    tags=["gemini-consistency"],
    dependencies=[Depends(require_developer_tools)],
)


@router.post("/experiments", response_model=GeminiBenchmarkExperimentRead, status_code=201)
def create_experiment(
    payload: GeminiBenchmarkExperimentCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkExperimentRead:
    try:
        experiment = GeminiConsistencyService(db=db, data_dir=data_dir).create(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return GeminiConsistencyService(db=db, data_dir=data_dir).read(experiment)


@router.get("/models")
async def discover_models(
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[dict]:
    try:
        return await GeminiConsistencyService(db=db, data_dir=data_dir).discover_models()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/experiments/{experiment_id}", response_model=GeminiBenchmarkExperimentRead)
def get_experiment(
    experiment_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkExperimentRead:
    service = GeminiConsistencyService(db=db, data_dir=data_dir)
    experiment = service.get(experiment_id)
    if experiment is None:
        raise HTTPException(status_code=404, detail="benchmark experiment not found")
    return service.read(experiment)


@router.post("/experiments/{experiment_id}/model-availability")
def record_model_availability(
    experiment_id: str,
    payload: GeminiBenchmarkModelAvailabilityCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    try:
        model = GeminiConsistencyService(db=db, data_dir=data_dir).record_model_availability(experiment_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "id": model.id,
        "requested_model": model.requested_model,
        "actual_model": model.actual_model,
        "availability_state": model.availability_state,
    }


@router.post("/experiments/{experiment_id}/runs/{run_id}/finish", response_model=dict)
def finish_run(
    experiment_id: str,
    run_id: str,
    payload: GeminiBenchmarkFinishCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    try:
        run = GeminiConsistencyService(db=db, data_dir=data_dir).finish_run(experiment_id, run_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": run.id, "state": run.state, "finished_at": run.finished_at}


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/cases/{case_id}/claim",
    response_model=GeminiBenchmarkMembershipRead,
)
def claim_case(
    experiment_id: str,
    run_id: str,
    case_id: str,
    payload: GeminiBenchmarkClaimCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkMembershipRead:
    service = GeminiConsistencyService(db=db, data_dir=data_dir)
    try:
        membership = service.claim(
            experiment_id=experiment_id,
            run_id=run_id,
            case_id=case_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return service.membership_read(membership)


@router.post(
    "/experiments/{experiment_id}/runs/{run_id}/cases/{case_id}/complete",
    response_model=GeminiBenchmarkMembershipRead,
)
def complete_case(
    experiment_id: str,
    run_id: str,
    case_id: str,
    payload: GeminiBenchmarkCompletionCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkMembershipRead:
    service = GeminiConsistencyService(db=db, data_dir=data_dir)
    try:
        membership = service.complete(
            experiment_id=experiment_id,
            run_id=run_id,
            case_id=case_id,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.membership_read(membership)


@router.post("/experiments/{experiment_id}/report", response_model=GeminiBenchmarkReportRead)
def report_experiment(
    experiment_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkReportRead:
    try:
        return GeminiConsistencyService(db=db, data_dir=data_dir).report(experiment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/experiments/{experiment_id}/finish", response_model=GeminiBenchmarkExperimentRead)
def finish_experiment(
    experiment_id: str,
    payload: GeminiBenchmarkFinishCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> GeminiBenchmarkExperimentRead:
    service = GeminiConsistencyService(db=db, data_dir=data_dir)
    try:
        experiment = service.finish(experiment_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.read(experiment)
