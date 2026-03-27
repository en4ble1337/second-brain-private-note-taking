from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse
from src.core.config import settings
from src.core.errors import error_response

router = APIRouter()


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    # Path traversal protection
    raw_dir = Path(settings.DATA_DIR) / "raw"
    try:
        target = (raw_dir / filename).resolve()
        if not str(target).startswith(str(raw_dir.resolve())):
            return error_response("NOT_FOUND", "File not found.", 404)
    except Exception:
        return error_response("NOT_FOUND", "File not found.", 404)

    if not target.exists() or not target.is_file():
        return error_response("NOT_FOUND", "Audio file not found.", 404)

    return FileResponse(str(target))
