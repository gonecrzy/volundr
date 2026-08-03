from fastapi import APIRouter

from app.core.config import settings


router = APIRouter(prefix="/api", tags=["capabilities"])


@router.get("/capabilities")
def get_capabilities() -> dict[str, bool]:
    return {"developer_tools_enabled": bool(settings.developer_tools_enabled)}
