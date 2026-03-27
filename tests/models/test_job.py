"""Tests for Job ORM model and JobStatus enum."""
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
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# JobStatus enum tests
# ---------------------------------------------------------------------------

def test_job_status_enum_values():
    """JobStatus must contain exactly: pending, transcribing, cleaning, complete, failed."""
    from src.models.job import JobStatus

    values = {s.value for s in JobStatus}
    assert values == {"pending", "transcribing", "cleaning", "complete", "failed"}


def test_job_status_is_str_enum():
    """JobStatus should subclass str so it serialises naturally."""
    from src.models.job import JobStatus

    assert issubclass(JobStatus, str)
    assert JobStatus.pending == "pending"
    assert JobStatus.transcribing == "transcribing"
    assert JobStatus.cleaning == "cleaning"
    assert JobStatus.complete == "complete"
    assert JobStatus.failed == "failed"


# ---------------------------------------------------------------------------
# Job persistence tests
# ---------------------------------------------------------------------------

async def test_job_id_is_auto_generated_uuid(db_session):
    """Job.id is set automatically to a UUID string on insert."""
    from sqlalchemy import select
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(Job))
    persisted = result.scalars().first()

    assert persisted is not None
    assert persisted.id is not None
    # UUID4 format: 8-4-4-4-12 hex chars
    import re
    uuid_pattern = re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    )
    assert uuid_pattern.match(persisted.id), f"Not a valid UUIDv4: {persisted.id}"


async def test_job_default_status_is_pending(db_session):
    """Job.status defaults to 'pending'."""
    from sqlalchemy import select
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(Job))
    persisted = result.scalars().first()

    assert persisted.status == "pending"


async def test_job_default_source_tag_is_unknown(db_session):
    """Job.source_tag defaults to 'unknown'."""
    from sqlalchemy import select
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(Job))
    persisted = result.scalars().first()

    assert persisted.source_tag == "unknown"


async def test_job_received_at_is_set_automatically(db_session):
    """Job.received_at is populated automatically on insert."""
    from datetime import datetime
    from sqlalchemy import select
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(Job))
    persisted = result.scalars().first()

    assert persisted.received_at is not None
    assert isinstance(persisted.received_at, datetime)


async def test_job_all_fields_persist_correctly(db_session):
    """All Job fields round-trip through the database correctly."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from src.models.job import Job, JobStatus

    now = datetime.now(timezone.utc)
    job = Job(
        audio_path="/audio/clip.wav",
        status=JobStatus.transcribing.value,
        source_tag="phone",
        transcript_path="/transcripts/clip.txt",
        audio_duration_seconds=12.5,
        error_message=None,
        completed_at=None,
    )
    db_session.add(job)
    await db_session.commit()
    job_id = job.id

    result = await db_session.execute(select(Job).where(Job.id == job_id))
    persisted = result.scalars().first()

    assert persisted is not None
    assert persisted.id == job_id
    assert persisted.audio_path == "/audio/clip.wav"
    assert persisted.status == "transcribing"
    assert persisted.source_tag == "phone"
    assert persisted.transcript_path == "/transcripts/clip.txt"
    assert persisted.audio_duration_seconds == pytest.approx(12.5)
    assert persisted.error_message is None
    assert persisted.completed_at is None


async def test_job_nullable_fields_accept_none(db_session):
    """transcript_path, audio_duration_seconds, error_message, completed_at can be NULL."""
    from sqlalchemy import select
    from src.models.job import Job

    job = Job(audio_path="/audio/test.wav")
    db_session.add(job)
    await db_session.commit()

    result = await db_session.execute(select(Job))
    persisted = result.scalars().first()

    assert persisted.transcript_path is None
    assert persisted.audio_duration_seconds is None
    assert persisted.error_message is None
    assert persisted.completed_at is None


async def test_job_ids_are_unique_across_two_inserts(db_session):
    """Two Job rows must have different auto-generated ids."""
    from sqlalchemy import select
    from src.models.job import Job

    job1 = Job(audio_path="/a.wav")
    job2 = Job(audio_path="/b.wav")
    db_session.add_all([job1, job2])
    await db_session.commit()

    result = await db_session.execute(select(Job))
    all_jobs = result.scalars().all()
    ids = [j.id for j in all_jobs]

    assert len(set(ids)) == 2


async def test_job_table_name_is_job(db_session):
    """The ORM table name must be 'job' (not 'jobs')."""
    from src.models.job import Job
    assert Job.__tablename__ == "job"


# ---------------------------------------------------------------------------
# IngestResponse schema test (co-located)
# ---------------------------------------------------------------------------

def test_ingest_response_serialises_correctly():
    """IngestResponse.model_dump() has the correct keys and values."""
    from src.schemas.ingest import IngestResponse

    resp = IngestResponse(job_id="abc-123", status="pending", message="queued")
    data = resp.model_dump()

    assert data == {"job_id": "abc-123", "status": "pending", "message": "queued"}


def test_error_detail_schema():
    """ErrorDetail has code and message fields."""
    from src.schemas.ingest import ErrorDetail

    detail = ErrorDetail(code="TOO_LARGE", message="File exceeds limit")
    data = detail.model_dump()

    assert "code" in data
    assert "message" in data
    assert data["code"] == "TOO_LARGE"


def test_error_response_schema():
    """ErrorResponse wraps an ErrorDetail under the 'error' key."""
    from src.schemas.ingest import ErrorDetail, ErrorResponse

    detail = ErrorDetail(code="NOT_FOUND", message="Resource missing")
    resp = ErrorResponse(error=detail)
    data = resp.model_dump()

    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
