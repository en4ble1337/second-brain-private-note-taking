import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from src.core.database import Base
import src.models  # register all models


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create FTS5 virtual table (same as init_db)
        await conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts "
            "USING fts5(search_vector, content='note', content_rowid='rowid')"
        ))
        await conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON note BEGIN "
            "INSERT INTO notes_fts(rowid, search_vector) VALUES (new.rowid, new.search_vector); END"
        ))
        await conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS notes_fts_update AFTER UPDATE ON note BEGIN "
            "DELETE FROM notes_fts WHERE rowid=old.rowid; "
            "INSERT INTO notes_fts(rowid, search_vector) VALUES (new.rowid, new.search_vector); END"
        ))
        await conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS notes_fts_delete AFTER DELETE ON note BEGIN "
            "DELETE FROM notes_fts WHERE rowid=old.rowid; END"
        ))

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def make_job(db) -> str:
    from src.models.job import Job, JobStatus
    job = Job(id=str(uuid4()), audio_path="/data/raw/test.m4a", status=JobStatus.pending.value)
    db.add(job)
    await db.commit()
    return job.id


async def make_note(db, *, raw_transcript="hello world", cleaned_text="Hello world", created_at=None):
    from src.services.note_service import create_note
    job_id = await make_job(db)
    kwargs = dict(
        job_id=job_id,
        audio_path="/data/raw/test.m4a",
        raw_transcript=raw_transcript,
        cleaned_text=cleaned_text,
        audio_duration_seconds=10.0,
        llm_model="test-model",
    )
    note = await create_note(db, **kwargs)
    if created_at is not None:
        # Patch created_at directly after creation for ordering tests
        from sqlalchemy import update
        from src.models.note import Note
        await db.execute(update(Note).where(Note.id == note.id).values(created_at=created_at))
        await db.commit()
        await db.refresh(note)
    return note


# ── Test 1 ────────────────────────────────────────────────────────────────────

async def test_create_note_returns_note(db):
    from src.services.note_service import create_note
    job_id = await make_job(db)
    note = await create_note(
        db,
        job_id=job_id,
        audio_path="/data/raw/test.m4a",
        raw_transcript="dentist appointment",
        cleaned_text="Call dentist",
        audio_duration_seconds=5.0,
        llm_model="whisper-1",
    )
    from src.models.note import Note
    assert isinstance(note, Note)
    assert note.id  # non-empty


# ── Test 2 ────────────────────────────────────────────────────────────────────

async def test_create_note_sets_search_vector(db):
    from src.services.note_service import create_note
    job_id = await make_job(db)
    note = await create_note(
        db,
        job_id=job_id,
        audio_path="/data/raw/test.m4a",
        raw_transcript="dentist",
        cleaned_text="Call dentist",
        audio_duration_seconds=None,
        llm_model="whisper-1",
    )
    assert note.search_vector == "dentist Call dentist"


# ── Test 3 ────────────────────────────────────────────────────────────────────

async def test_create_note_persists_to_db(db):
    from src.services.note_service import create_note, get_note
    job_id = await make_job(db)
    note = await create_note(
        db,
        job_id=job_id,
        audio_path="/data/raw/test.m4a",
        raw_transcript="dentist",
        cleaned_text="Call dentist",
        audio_duration_seconds=None,
        llm_model="whisper-1",
    )
    fetched = await get_note(db, note.id)
    assert fetched is not None
    assert fetched.id == note.id


# ── Test 4 ────────────────────────────────────────────────────────────────────

async def test_get_note_returns_none_for_missing(db):
    from src.services.note_service import get_note
    result = await get_note(db, "nonexistent-id")
    assert result is None


# ── Test 5 ────────────────────────────────────────────────────────────────────

async def test_list_notes_returns_reverse_chrono(db):
    from src.services.note_service import list_notes
    base = datetime(2025, 1, 1, 12, 0, 0)
    n1 = await make_note(db, raw_transcript="note one", cleaned_text="note one", created_at=base)
    n2 = await make_note(db, raw_transcript="note two", cleaned_text="note two", created_at=base + timedelta(hours=1))
    n3 = await make_note(db, raw_transcript="note three", cleaned_text="note three", created_at=base + timedelta(hours=2))

    notes, total = await list_notes(db)
    assert total == 3
    assert notes[0].id == n3.id  # newest first
    assert notes[1].id == n2.id
    assert notes[2].id == n1.id


# ── Test 6 ────────────────────────────────────────────────────────────────────

async def test_list_notes_pagination(db):
    from src.services.note_service import list_notes
    for i in range(25):
        await make_note(db, raw_transcript=f"note {i}", cleaned_text=f"Note {i}")

    notes_p1, total_p1 = await list_notes(db, page=1)
    notes_p2, total_p2 = await list_notes(db, page=2)

    assert len(notes_p1) == 20
    assert len(notes_p2) == 5
    assert total_p1 == 25
    assert total_p2 == 25


# ── Test 7 ────────────────────────────────────────────────────────────────────

async def test_list_notes_empty(db):
    from src.services.note_service import list_notes
    notes, total = await list_notes(db)
    assert notes == []
    assert total == 0


# ── Test 8 ────────────────────────────────────────────────────────────────────

async def test_fts_search_finds_matching_note(db):
    from src.services.note_service import list_notes
    note = await make_note(db, raw_transcript="reminder", cleaned_text="Call the dentist tomorrow")
    await make_note(db, raw_transcript="grocery list", cleaned_text="Buy milk and eggs")

    results, total = await list_notes(db, query="dentist")
    assert total == 1
    assert len(results) == 1
    assert results[0].id == note.id


# ── Test 9 ────────────────────────────────────────────────────────────────────

async def test_fts_search_no_match_returns_empty(db):
    from src.services.note_service import list_notes
    await make_note(db, raw_transcript="grocery list", cleaned_text="Buy milk and eggs")

    results, total = await list_notes(db, query="xyzzy_no_such_word")
    assert results == []
    assert total == 0


# ── Test 10 ───────────────────────────────────────────────────────────────────

async def test_fts_search_is_case_insensitive(db):
    from src.services.note_service import list_notes
    await make_note(db, raw_transcript="DENTIST APPOINTMENT", cleaned_text="DENTIST")

    results, total = await list_notes(db, query="dentist")
    assert total == 1
    assert len(results) == 1


# ── Test 11 ───────────────────────────────────────────────────────────────────

async def test_get_note_by_job_id(db):
    from src.services.note_service import get_note_by_job_id, create_note
    job_id = await make_job(db)
    note = await create_note(
        db,
        job_id=job_id,
        audio_path="/data/raw/test.m4a",
        raw_transcript="testing",
        cleaned_text="Testing job lookup",
        audio_duration_seconds=3.5,
        llm_model="whisper-1",
    )
    fetched = await get_note_by_job_id(db, job_id)
    assert fetched is not None
    assert fetched.id == note.id
    assert fetched.job_id == job_id
