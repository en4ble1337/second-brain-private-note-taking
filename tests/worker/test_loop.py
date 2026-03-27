import asyncio
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from src.core.database import Base
import src.models


@pytest_asyncio.fixture
async def session_factory(tmp_path, monkeypatch):
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
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def make_pending_job(session_factory, tmp_path):
    from src.models.job import Job, JobStatus
    audio = tmp_path / "test.wav"
    audio.write_bytes(b"fake")
    async with session_factory() as db:
        job = Job(id=str(uuid4()), audio_path=str(audio), status=JobStatus.pending.value)
        db.add(job)
        await db.commit()
        return job.id


async def test_process_next_pending_job_returns_false_when_empty(session_factory):
    from src.worker.loop import process_next_pending_job
    result = await process_next_pending_job(session_factory)
    assert result is False


async def test_process_next_pending_job_processes_pending_job(session_factory, tmp_path):
    from src.worker.loop import process_next_pending_job
    await make_pending_job(session_factory, tmp_path)

    with patch('src.worker.loop.pipeline.run_pipeline', new_callable=AsyncMock) as mock_pipeline:
        result = await process_next_pending_job(session_factory)

    assert result is True
    mock_pipeline.assert_called_once()


async def test_process_next_pending_job_claims_job_immediately(session_factory, tmp_path):
    from src.worker.loop import process_next_pending_job
    from src.models.job import JobStatus
    await make_pending_job(session_factory, tmp_path)

    captured_status = []

    async def capture_status(db, job):
        captured_status.append(job.status)

    with patch('src.worker.loop.pipeline.run_pipeline', side_effect=capture_status):
        await process_next_pending_job(session_factory)

    assert len(captured_status) == 1
    assert captured_status[0] == JobStatus.transcribing.value


async def test_worker_continues_after_pipeline_error(session_factory, tmp_path):
    from src.worker.loop import process_next_pending_job
    await make_pending_job(session_factory, tmp_path)

    async def raise_error(db, job):
        # Simulate pipeline marking job as failed before re-raising
        from src.models.job import JobStatus
        job.status = JobStatus.failed.value
        await db.commit()
        raise RuntimeError("pipeline exploded")

    with patch('src.worker.loop.pipeline.run_pipeline', side_effect=raise_error):
        # Should not raise — worker swallows the exception
        result = await process_next_pending_job(session_factory)

    assert result is True


async def test_run_worker_loop_cancels_cleanly(session_factory):
    from src.worker.loop import run_worker_loop
    task = asyncio.create_task(run_worker_loop(session_factory))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # expected
    # If we get here without other exceptions, the test passes


async def test_run_worker_loop_processes_job(session_factory, tmp_path):
    job_id = await make_pending_job(session_factory, tmp_path)

    with patch('src.worker.loop.pipeline.run_pipeline', new_callable=AsyncMock) as mock_pipeline:
        from src.worker.loop import run_worker_loop
        task = asyncio.create_task(run_worker_loop(session_factory))
        await asyncio.sleep(0.1)  # let one iteration run
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert mock_pipeline.called
