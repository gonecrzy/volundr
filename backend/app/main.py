from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
