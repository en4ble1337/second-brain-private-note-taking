from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.errors import error_response
from src.models.job import Job
from src.models.note import Note
from src.schemas.note import NoteListResponse, NoteSchema, JobStatusResponse
from src.services import note_service

router = APIRouter(prefix="/api")


@router.get("/notes", response_model=NoteListResponse)
async def list_notes_api(
    q: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
):
    notes, total = await note_service.list_notes(db, query=q or None, page=page)
    return NoteListResponse(
        notes=[NoteSchema.model_validate(n) for n in notes],
        total=total,
        page=page,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        return error_response("NOT_FOUND", f"Job '{job_id}' not found.", 404)

    # Find associated note if complete
    note = await note_service.get_note_by_job_id(db, job_id)

    return JobStatusResponse(
        id=job.id,
        status=job.status,
        note_id=note.id if note else None,
        error_message=job.error_message,
    )
