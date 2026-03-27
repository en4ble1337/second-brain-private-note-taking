from datetime import datetime
from uuid import uuid4
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.note import Note
from src.models.job import Job


async def create_note(
    db: AsyncSession,
    *,
    job_id: str,
    audio_path: str,
    raw_transcript: str,
    cleaned_text: str,
    audio_duration_seconds: float | None,
    llm_model: str,
) -> Note:
    """Create and persist a Note record. Sets search_vector for FTS5."""
    note = Note(
        id=str(uuid4()),
        job_id=job_id,
        created_at=datetime.utcnow(),
        audio_path=audio_path,
        raw_transcript=raw_transcript,
        cleaned_text=cleaned_text,
        audio_duration_seconds=audio_duration_seconds,
        llm_model=llm_model,
        search_vector=f"{raw_transcript} {cleaned_text}",
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def get_note(db: AsyncSession, note_id: str) -> Note | None:
    """Fetch a Note by primary key. Returns None if not found."""
    result = await db.execute(select(Note).where(Note.id == note_id))
    return result.scalar_one_or_none()


async def get_note_by_job_id(db: AsyncSession, job_id: str) -> Note | None:
    """Fetch a Note by its source job_id."""
    result = await db.execute(select(Note).where(Note.job_id == job_id))
    return result.scalar_one_or_none()


async def list_notes(
    db: AsyncSession,
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Note], int]:
    """Return paginated notes with total count.

    If query is provided, uses FTS5 search on search_vector.
    Otherwise returns all notes in reverse-chronological order.
    """
    if query and query.strip():
        return await _fts_search(db, query.strip(), page, page_size)

    # Count total
    count_result = await db.execute(select(func.count()).select_from(Note))
    total = count_result.scalar_one()

    # Fetch page
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Note).order_by(Note.created_at.desc()).offset(offset).limit(page_size)
    )
    notes = list(result.scalars().all())
    return notes, total


async def _fts_search(
    db: AsyncSession,
    query: str,
    page: int,
    page_size: int,
) -> tuple[list[Note], int]:
    """Search notes using SQLite FTS5. Returns (notes, total)."""
    # Get all matching rowids from FTS index
    fts_result = await db.execute(
        text("SELECT rowid FROM notes_fts WHERE notes_fts MATCH :q ORDER BY rank"),
        {"q": query},
    )
    rowids = [row[0] for row in fts_result.fetchall()]

    if not rowids:
        return [], 0

    total = len(rowids)

    # Paginate the rowids
    offset = (page - 1) * page_size
    page_rowids = rowids[offset : offset + page_size]

    if not page_rowids:
        return [], total

    # Fetch Note rows by rowid
    # SQLite rowid is the implicit integer primary key — we need to map back via rowid
    # Use a raw query to fetch notes by their SQLite rowid
    notes = []
    for rowid in page_rowids:
        result = await db.execute(
            text("SELECT id FROM note WHERE rowid = :rowid"),
            {"rowid": rowid},
        )
        row = result.fetchone()
        if row:
            note_result = await db.execute(select(Note).where(Note.id == row[0]))
            note = note_result.scalar_one_or_none()
            if note:
                notes.append(note)

    return notes, total
