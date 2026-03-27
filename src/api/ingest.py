import os
from datetime import datetime, timezone
from pathlib import Path
import aiofiles
import filetype
from fastapi import APIRouter, Depends, File, Form, UploadFile, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import get_db
from src.core.security import ingest_auth
from src.core.errors import error_response
from src.models.job import Job, JobStatus
from src.schemas.ingest import IngestResponse

router = APIRouter()

ALLOWED_AUDIO_MIMES = {"audio/mp4", "audio/ogg", "audio/mpeg", "audio/wav", "audio/x-wav"}


@router.post("/api/ingest", status_code=202)
async def ingest_audio(
    request: Request,
    audio: UploadFile = File(...),
    source: str = Form(default="unknown"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(ingest_auth),
):
    # 1. Read magic bytes for MIME validation
    header_bytes = await audio.read(261)
    kind = filetype.guess(header_bytes)
    if kind is None or kind.mime not in ALLOWED_AUDIO_MIMES:
        mime_detected = kind.mime if kind else "unknown"
        return error_response("INVALID_AUDIO", f"File type '{mime_detected}' is not an accepted audio format.", 400)

    # 2. Seek back to beginning
    await audio.seek(0)

    # 3. Generate server-side filename
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_source = "".join(c for c in source if c.isalnum() or c in "-_")[:32] or "unknown"
    ext = kind.extension
    filename = f"{ts}_{safe_source}.{ext}"

    # 4. Ensure raw directory exists
    raw_dir = Path(settings.DATA_DIR) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest_path = raw_dir / filename

    # 5. Stream file to disk
    max_bytes = settings.MAX_AUDIO_SIZE_MB * 1024 * 1024
    bytes_written = 0
    too_large = False
    async with aiofiles.open(dest_path, "wb") as f:
        while chunk := await audio.read(65536):
            bytes_written += len(chunk)
            if bytes_written > max_bytes:
                too_large = True
                break
            await f.write(chunk)

    if too_large:
        os.unlink(dest_path)
        return error_response("PAYLOAD_TOO_LARGE", f"File exceeds maximum size of {settings.MAX_AUDIO_SIZE_MB}MB.", 413)

    # 6. Create Job record
    job = Job(
        audio_path=str(dest_path),
        source_tag=safe_source,
        status=JobStatus.pending.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    return IngestResponse(
        job_id=job.id,
        status="pending",
        message="Audio received and queued for processing.",
    )
