import shutil
import socket
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import get_db
from src.core.errors import error_response
from src.services import note_service

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_lan_ip() -> str:
    """Detect the device's LAN IP address."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "<YOUR_DEVICE_IP>"


@router.get("/", response_class=HTMLResponse)
async def inbox(
    request: Request,
    q: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    notes, total = await note_service.list_notes(db, query=q or None, page=page)

    # Disk warning check
    try:
        usage = shutil.disk_usage(settings.DATA_DIR)
        disk_warning = (usage.used / usage.total) > 0.80
    except Exception:
        disk_warning = False

    return templates.TemplateResponse("inbox.html", {
        "request": request,
        "notes": notes,
        "total": total,
        "page": page,
        "page_size": 20,
        "query": q,
        "disk_warning": disk_warning,
    })


@router.get("/notes/{note_id}", response_class=HTMLResponse)
async def note_detail(
    request: Request,
    note_id: str,
    db: AsyncSession = Depends(get_db),
):
    note = await note_service.get_note(db, note_id)
    if note is None:
        return error_response("NOT_FOUND", "Note not found.", 404)

    audio_filename = Path(note.audio_path).name

    return templates.TemplateResponse("note.html", {
        "request": request,
        "note": note,
        "audio_filename": audio_filename,
    })


@router.get("/setup", response_class=HTMLResponse)
async def setup_wizard(request: Request):
    from src.core.config import Settings
    _settings = Settings()
    lan_ip = get_lan_ip()
    masked_token = _settings.INGEST_TOKEN[:6] + "..." if len(_settings.INGEST_TOKEN) > 6 else "***"
    ingest_url = f"http://{lan_ip}/api/ingest"

    return templates.TemplateResponse("setup.html", {
        "request": request,
        "lan_ip": lan_ip,
        "masked_token": masked_token,
        "ingest_url": ingest_url,
    })
