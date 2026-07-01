from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["dashboard"])

_DASHBOARD_HTML = Path(__file__).resolve().parents[2] / "static" / "dashboard.html"


@router.get("/dashboard")
async def dashboard_page() -> FileResponse:
    return FileResponse(_DASHBOARD_HTML, media_type="text/html")
