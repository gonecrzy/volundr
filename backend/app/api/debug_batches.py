from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_data_dir, require_developer_tools
from app.db.session import get_db
from app.models.debug_batch import DebugBatch
from fastapi.responses import FileResponse

from app.schemas.debug_batch import (
    DebugBatchFrontendEventsCreate,
    DebugBatchFrontendEventsRead,
    DebugBatchRead,
    DebugBatchSummary,
    DebugBatchStart,
)
from app.services.debug_batches.comparison import DebugBatchComparisonService
from app.services.debug_batches.evidence import record_frontend_events
from app.services.debug_batches.reports import DebugBatchReportService
from app.services.debug_batches.service import DebugBatchService


router = APIRouter(prefix="/api/debug-batches", tags=["debug-batches"])


def _not_implemented() -> None:
    raise HTTPException(status_code=501, detail="debug batch operation is not implemented")


@router.post("", response_model=DebugBatchRead, status_code=201, dependencies=[Depends(require_developer_tools)])
def start_debug_batch(
    payload: DebugBatchStart,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DebugBatchRead:
    try:
        batch = DebugBatchService(db=db, data_dir=data_dir).start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DebugBatchService(db=db, data_dir=data_dir).read(batch)


@router.get("", response_model=list[DebugBatchRead], dependencies=[Depends(require_developer_tools)])
def list_debug_batches(
    state: str | None = None,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> list[DebugBatchRead]:
    query = select(DebugBatch).order_by(DebugBatch.started_at.desc(), DebugBatch.id.desc())
    if state is not None:
        query = query.where(DebugBatch.state == state)
    service = DebugBatchService(db=db, data_dir=data_dir)
    return [service.read(batch) for batch in db.scalars(query).all()]


@router.get("/{batch_id}", response_model=DebugBatchRead, dependencies=[Depends(require_developer_tools)])
def get_debug_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DebugBatchRead:
    service = DebugBatchService(db=db, data_dir=data_dir)
    batch = service.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="debug batch not found")
    return service.read(batch)


@router.post("/{batch_id}/finish", response_model=DebugBatchRead, dependencies=[Depends(require_developer_tools)])
def finish_debug_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DebugBatchRead:
    service = DebugBatchService(db=db, data_dir=data_dir)
    try:
        batch = service.finish(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return service.read(batch)


@router.get(
    "/{batch_id}/report",
    response_model=DebugBatchSummary,
    dependencies=[Depends(require_developer_tools)],
)
def get_debug_batch_report(
    batch_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DebugBatchSummary:
    service = DebugBatchService(db=db, data_dir=data_dir)
    batch = service.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="debug batch not found")
    try:
        generated = DebugBatchReportService(db=db, data_dir=data_dir).generate(batch_id)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"report generation failed: {exc}") from exc
    report = generated["report"]
    review_path = Path(generated["root_path"]) / "codex-review.md"
    return DebugBatchSummary(
        batch=service.read(batch),
        summary=report,
        report_path=generated["report_path"],
        codex_review_instruction=review_path.read_text(encoding="utf-8"),
    )


@router.get("/{batch_id}/evidence.zip", dependencies=[Depends(require_developer_tools)])
def download_debug_batch_evidence(
    batch_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> FileResponse:
    try:
        archive_path = DebugBatchReportService(db=db, data_dir=data_dir).build_archive(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(archive_path, media_type="application/zip", filename=f"debug-batch-{batch_id}.zip")


@router.post(
    "/{batch_id}/frontend-events",
    response_model=DebugBatchFrontendEventsRead,
    status_code=201,
    dependencies=[Depends(require_developer_tools)],
)
def record_debug_batch_frontend_events(
    batch_id: str,
    payload: DebugBatchFrontendEventsCreate,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> DebugBatchFrontendEventsRead:
    try:
        accepted_count = record_frontend_events(
            db=db, data_dir=data_dir, batch_id=batch_id, payload=payload
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DebugBatchFrontendEventsRead(accepted_count=accepted_count)


@router.get("/{batch_id}/comparison", dependencies=[Depends(require_developer_tools)])
def get_debug_batch_comparison(
    batch_id: str,
    db: Session = Depends(get_db),
    data_dir: Path = Depends(get_data_dir),
) -> dict:
    try:
        return DebugBatchComparisonService(db=db, data_dir=data_dir).compare(batch_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
