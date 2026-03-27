import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text, select
from src.core.database import Base
import src.models  # register models


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
        await conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts "
            "USING fts5(search_vector, content='note', content_rowid='rowid')"
        ))
        await conn.execute(text(
            "CREATE TRIGGER IF NOT EXISTS notes_fts_insert AFTER INSERT ON note BEGIN "
            "INSERT INTO notes_fts(rowid, search_vector) VALUES (new.rowid, new.search_vector); END"
        ))
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def pending_job(db, tmp_path):
    from src.models.job import Job, JobStatus
    from uuid import uuid4
    # Create a fake audio file
    audio_file = tmp_path / "test_audio.wav"
    audio_file.write_bytes(b"fake audio content")
    job = Job(
        id=str(uuid4()),
        audio_path=str(audio_file),
        source_tag="test",
        status=JobStatus.pending.value,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def test_pipeline_happy_path(db, pending_job):
    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock) as mock_transcribe, \
         patch('src.services.pipeline.transcription_service.save_transcript', return_value="/data/raw/test.txt") as mock_save, \
         patch('src.services.pipeline.llm_service.cleanup', new_callable=AsyncMock) as mock_cleanup:

        mock_transcribe.return_value = ("Hello world", 5.0)
        mock_cleanup.return_value = "Hello world."

        from src.services.pipeline import run_pipeline
        await run_pipeline(db, pending_job)

        await db.refresh(pending_job)
        assert pending_job.status == "complete"
        assert pending_job.completed_at is not None
        assert pending_job.transcript_path == "/data/raw/test.txt"
        assert pending_job.audio_duration_seconds == 5.0

        # Check note was created
        from src.services.note_service import get_note_by_job_id
        note = await get_note_by_job_id(db, pending_job.id)
        assert note is not None
        assert note.cleaned_text == "Hello world."
        assert note.raw_transcript == "Hello world"


async def test_pipeline_llm_failure_fallback(db, pending_job):
    from src.services.llm import LLMServiceError
    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock) as mock_transcribe, \
         patch('src.services.pipeline.transcription_service.save_transcript', return_value="/data/raw/test.txt"), \
         patch('src.services.pipeline.llm_service.cleanup', new_callable=AsyncMock) as mock_cleanup:

        mock_transcribe.return_value = ("Raw transcript text", 3.0)
        mock_cleanup.side_effect = LLMServiceError("Ollama not available")

        from src.services.pipeline import run_pipeline
        await run_pipeline(db, pending_job)  # should NOT raise

        await db.refresh(pending_job)
        assert pending_job.status == "complete"

        from src.services.note_service import get_note_by_job_id
        note = await get_note_by_job_id(db, pending_job.id)
        assert note is not None
        assert note.cleaned_text == "Raw transcript text"
        assert note.llm_model == "none (fallback)"


async def test_pipeline_transcription_failure(db, pending_job):
    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock) as mock_transcribe:
        mock_transcribe.side_effect = RuntimeError("CTranslate2 error")

        from src.services.pipeline import run_pipeline
        with pytest.raises(RuntimeError, match="CTranslate2 error"):
            await run_pipeline(db, pending_job)

        await db.refresh(pending_job)
        assert pending_job.status == "failed"
        assert "CTranslate2 error" in pending_job.error_message
        assert pending_job.completed_at is not None

        from src.services.note_service import get_note_by_job_id
        note = await get_note_by_job_id(db, pending_job.id)
        assert note is None


async def test_pipeline_status_transitions(db, pending_job):
    status_history = []
    original_commit = db.commit

    async def tracking_commit():
        # Read the in-memory status before committing — pipeline sets it on the object first
        status_history.append(pending_job.status)
        await original_commit()

    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock, return_value=("text", 1.0)), \
         patch('src.services.pipeline.transcription_service.save_transcript', return_value="/tmp/t.txt"), \
         patch('src.services.pipeline.llm_service.cleanup', new_callable=AsyncMock, return_value="cleaned"):

        with patch.object(db, 'commit', side_effect=tracking_commit):
            from src.services.pipeline import run_pipeline
            await run_pipeline(db, pending_job)

    assert "transcribing" in status_history
    assert "cleaning" in status_history
    assert "complete" in status_history
    # transcribing must come before cleaning, cleaning before complete
    assert status_history.index("transcribing") < status_history.index("cleaning")
    assert status_history.index("cleaning") < status_history.index("complete")


async def test_pipeline_sets_llm_model_on_success(db, pending_job):
    from src.core.config import settings

    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock) as mock_transcribe, \
         patch('src.services.pipeline.transcription_service.save_transcript', return_value="/data/raw/test.txt"), \
         patch('src.services.pipeline.llm_service.cleanup', new_callable=AsyncMock) as mock_cleanup:

        mock_transcribe.return_value = ("Some transcript", 2.0)
        mock_cleanup.return_value = "Some cleaned transcript."

        from src.services.pipeline import run_pipeline
        await run_pipeline(db, pending_job)

        from src.services.note_service import get_note_by_job_id
        note = await get_note_by_job_id(db, pending_job.id)
        assert note is not None
        assert note.llm_model == settings.OLLAMA_MODEL


async def test_pipeline_note_has_audio_path(db, pending_job):
    with patch('src.services.pipeline.transcription_service.transcribe', new_callable=AsyncMock) as mock_transcribe, \
         patch('src.services.pipeline.transcription_service.save_transcript', return_value="/data/raw/test.txt"), \
         patch('src.services.pipeline.llm_service.cleanup', new_callable=AsyncMock) as mock_cleanup:

        mock_transcribe.return_value = ("Audio transcript", 4.0)
        mock_cleanup.return_value = "Audio transcript cleaned."

        from src.services.pipeline import run_pipeline
        await run_pipeline(db, pending_job)

        from src.services.note_service import get_note_by_job_id
        note = await get_note_by_job_id(db, pending_job.id)
        assert note is not None
        assert note.audio_path == pending_job.audio_path
