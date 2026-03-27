"""Tests for Note ORM model and NoteSchema Pydantic schema."""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

import src.models  # noqa: F401 — registers Job/Note with Base.metadata before create_all
from src.core.database import Base


@pytest_asyncio.fixture
async def db_session():
    # StaticPool keeps a single in-memory connection alive so create_all and
    # subsequent session operations all see the same SQLite database.
    # The event listener enables SQLite FK enforcement on every new connection.
    from sqlalchemy import event

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helper: create a Job row
# ---------------------------------------------------------------------------

async def _create_job(session):
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    session.add(job)
    await session.commit()
    return job


# ---------------------------------------------------------------------------
# Note persistence tests
# ---------------------------------------------------------------------------

async def test_note_id_is_auto_generated(db_session):
    """Note.id is populated automatically with a UUID string."""
    import re
    from sqlalchemy import select
    from src.models.note import Note

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/test.wav",
        raw_transcript="hello world",
        cleaned_text="Hello world.",
    )
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Note))
    persisted = result.scalars().first()

    assert persisted is not None
    assert persisted.id is not None
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(persisted.id), f"Not a valid UUIDv4: {persisted.id}"


async def test_note_created_at_is_set_automatically(db_session):
    """Note.created_at is populated on insert."""
    from datetime import datetime
    from sqlalchemy import select
    from src.models.note import Note

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/test.wav",
        raw_transcript="raw",
        cleaned_text="clean",
    )
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Note))
    persisted = result.scalars().first()

    assert persisted.created_at is not None
    assert isinstance(persisted.created_at, datetime)


async def test_note_all_fields_persist_correctly(db_session):
    """All Note fields round-trip through the database."""
    from sqlalchemy import select
    from src.models.note import Note

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/clip.wav",
        raw_transcript="um so uh yeah",
        cleaned_text="Yes.",
        audio_duration_seconds=7.3,
        llm_model="mistral-7b",
        search_vector="yes hello world",
    )
    db_session.add(note)
    await db_session.commit()
    note_id = note.id

    result = await db_session.execute(select(Note).where(Note.id == note_id))
    persisted = result.scalars().first()

    assert persisted is not None
    assert persisted.id == note_id
    assert persisted.job_id == job.id
    assert persisted.audio_path == "/audio/clip.wav"
    assert persisted.raw_transcript == "um so uh yeah"
    assert persisted.cleaned_text == "Yes."
    assert persisted.audio_duration_seconds == pytest.approx(7.3)
    assert persisted.llm_model == "mistral-7b"
    assert persisted.search_vector == "yes hello world"


async def test_note_nullable_fields_accept_none(db_session):
    """audio_duration_seconds and search_vector can be NULL."""
    from sqlalchemy import select
    from src.models.note import Note

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/x.wav",
        raw_transcript="raw",
        cleaned_text="clean",
    )
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Note))
    persisted = result.scalars().first()

    assert persisted.audio_duration_seconds is None
    assert persisted.search_vector is None


async def test_note_job_id_fk_constraint_raises_integrity_error(db_session):
    """Creating a Note with a non-existent job_id raises an IntegrityError."""
    from sqlalchemy.exc import IntegrityError
    from src.models.note import Note

    note = Note(
        job_id="nonexistent-job-id-that-does-not-exist",
        audio_path="/audio/x.wav",
        raw_transcript="raw",
        cleaned_text="clean",
    )
    db_session.add(note)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_note_job_id_is_unique(db_session):
    """Two Notes cannot share the same job_id (UNIQUE constraint)."""
    from sqlalchemy.exc import IntegrityError
    from src.models.note import Note

    job = await _create_job(db_session)
    note1 = Note(
        job_id=job.id,
        audio_path="/audio/a.wav",
        raw_transcript="raw",
        cleaned_text="clean",
    )
    db_session.add(note1)
    await db_session.commit()

    note2 = Note(
        job_id=job.id,
        audio_path="/audio/b.wav",
        raw_transcript="raw2",
        cleaned_text="clean2",
    )
    db_session.add(note2)
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_note_table_name_is_note(db_session):
    """The ORM table name must be 'note' (not 'notes')."""
    from src.models.note import Note
    assert Note.__tablename__ == "note"


async def test_note_default_llm_model_is_empty_string(db_session):
    """Note.llm_model defaults to empty string."""
    from sqlalchemy import select
    from src.models.note import Note

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/x.wav",
        raw_transcript="raw",
        cleaned_text="clean",
    )
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Note))
    persisted = result.scalars().first()

    assert persisted.llm_model == ""


# ---------------------------------------------------------------------------
# NoteSchema Pydantic tests
# ---------------------------------------------------------------------------

async def test_note_schema_from_orm_instance(db_session):
    """NoteSchema.model_validate() works on a real ORM Note instance."""
    from sqlalchemy import select
    from src.models.note import Note
    from src.schemas.note import NoteSchema

    job = await _create_job(db_session)
    note = Note(
        job_id=job.id,
        audio_path="/audio/test.wav",
        raw_transcript="some raw text",
        cleaned_text="Some raw text.",
        audio_duration_seconds=5.0,
        llm_model="gpt-4",
    )
    db_session.add(note)
    await db_session.commit()

    result = await db_session.execute(select(Note))
    persisted = result.scalars().first()

    schema_obj = NoteSchema.model_validate(persisted)

    assert schema_obj.id == persisted.id
    assert schema_obj.cleaned_text == "Some raw text."
    assert schema_obj.raw_transcript == "some raw text"
    assert schema_obj.audio_path == "/audio/test.wav"
    assert schema_obj.llm_model == "gpt-4"
    assert schema_obj.audio_duration_seconds == pytest.approx(5.0)
    assert schema_obj.created_at is not None


def test_note_schema_model_dump_has_correct_keys():
    """NoteSchema.model_dump() contains all required keys."""
    from datetime import datetime, timezone
    from src.schemas.note import NoteSchema

    schema_obj = NoteSchema(
        id="note-1",
        created_at=datetime.now(timezone.utc),
        audio_duration_seconds=3.5,
        cleaned_text="Cleaned.",
        raw_transcript="raw",
        audio_path="/audio/x.wav",
        llm_model="mistral",
    )
    data = schema_obj.model_dump()

    expected_keys = {"id", "created_at", "audio_duration_seconds", "cleaned_text",
                     "raw_transcript", "audio_path", "llm_model"}
    assert expected_keys.issubset(data.keys())


def test_job_status_response_schema():
    """JobStatusResponse has correct fields including nullable note_id and error_message."""
    from src.schemas.note import JobStatusResponse

    resp = JobStatusResponse(
        id="job-1",
        status="complete",
        note_id="note-1",
        error_message=None,
    )
    data = resp.model_dump()

    assert data["id"] == "job-1"
    assert data["status"] == "complete"
    assert data["note_id"] == "note-1"
    assert data["error_message"] is None


def test_note_list_response_schema():
    """NoteListResponse has notes list, total, and page fields."""
    from datetime import datetime, timezone
    from src.schemas.note import NoteSchema, NoteListResponse

    note = NoteSchema(
        id="n-1",
        created_at=datetime.now(timezone.utc),
        audio_duration_seconds=None,
        cleaned_text="Hi.",
        raw_transcript="hi",
        audio_path="/audio/hi.wav",
        llm_model="",
    )
    resp = NoteListResponse(notes=[note], total=1, page=1)
    data = resp.model_dump()

    assert data["total"] == 1
    assert data["page"] == 1
    assert len(data["notes"]) == 1
