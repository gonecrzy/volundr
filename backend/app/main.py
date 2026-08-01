from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.projects import router as projects_router
from app.core.config import settings
from app.db.session import SessionLocal
from app.services.workflow.observability import WorkflowRecorder


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database_path = settings.data_dir / "app.db"
    if database_path.is_file():
        with SessionLocal() as session:
            WorkflowRecorder(db=session, data_dir=settings.data_dir).classify_stale_runs(
                max_running_seconds=settings.workflow_stale_seconds,
            )
    yield


app = FastAPI(title="Volundr API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def readiness() -> dict[str, object]:
    checks: dict[str, str] = {"database": "unknown", "artifact_storage": "unknown"}
    if not settings.data_dir.is_dir():
        checks["artifact_storage"] = "unavailable"
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    checks["artifact_storage"] = "ok"
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        checks["database"] = "unavailable"
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks}) from exc
    checks["database"] = "ok"
    return {"status": "ready", "checks": checks}
