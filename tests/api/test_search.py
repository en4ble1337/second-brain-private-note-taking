import pytest
import pytest_asyncio
from collections import namedtuple
from datetime import datetime
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from src.core.database import Base, get_db
from src.core.security import ingest_auth
import src.models
from unittest.mock import patch


@pytest_asyncio.fixture
async def search_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INGEST_TOKEN", "test-token")

    import src.web.router as web_router_module
    monkeypatch.setattr(web_router_module.settings, 'DATA_DIR', str(tmp_path))

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

    async def override_get_db():
        async with session_factory() as session:
            yield session

    from src.main import app
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[ingest_auth] = lambda: None
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def seed_note(session_factory, cleaned_text, raw_transcript="raw text"):
    from src.models.job import Job, JobStatus
    from src.models.note import Note
    async with session_factory() as session:
        job = Job(id=str(uuid4()), audio_path="/data/raw/test.m4a", status=JobStatus.complete.value)
        session.add(job)
        await session.commit()
        note = Note(
            id=str(uuid4()),
            job_id=job.id,
            created_at=datetime.utcnow(),
            audio_path="/data/raw/test.m4a",
            raw_transcript=raw_transcript,
            cleaned_text=cleaned_text,
            audio_duration_seconds=3.0,
            llm_model="llama3.2:3b",
            search_vector=f"{raw_transcript} {cleaned_text}",
        )
        session.add(note)
        await session.commit()
        return note.id


async def test_search_returns_matching_notes(search_client):
    ac, session_factory = search_client
    await seed_note(session_factory, cleaned_text="Call the dentist tomorrow")
    response = await ac.get("/?q=dentist")
    assert response.status_code == 200
    assert "Call the dentist tomorrow" in response.text


async def test_search_no_match_returns_empty(search_client):
    ac, session_factory = search_client
    await seed_note(session_factory, cleaned_text="Call the dentist tomorrow")
    response = await ac.get("/?q=xyzzy123")
    assert response.status_code == 200
    assert "No notes" in response.text or "0 notes" in response.text


async def test_search_empty_query_returns_all(search_client):
    ac, session_factory = search_client
    await seed_note(session_factory, cleaned_text="First note content here")
    await seed_note(session_factory, cleaned_text="Second note content here")
    response = await ac.get("/?q=")
    assert response.status_code == 200
    assert "First note content here" in response.text
    assert "Second note content here" in response.text


async def test_search_retains_query_in_form(search_client):
    ac, session_factory = search_client
    response = await ac.get("/?q=dentist")
    assert response.status_code == 200
    assert 'value="dentist"' in response.text


async def test_search_shows_result_count(search_client):
    ac, session_factory = search_client
    await seed_note(session_factory, cleaned_text="Call the dentist tomorrow")
    response = await ac.get("/?q=dentist")
    assert response.status_code == 200
    assert "1" in response.text


DiskUsage = namedtuple('DiskUsage', ['total', 'used', 'free'])


async def test_disk_warning_shown_when_over_80_percent(search_client):
    ac, session_factory = search_client
    with patch('src.web.router.shutil.disk_usage', return_value=DiskUsage(total=100, used=85, free=15)):
        response = await ac.get("/")
    assert response.status_code == 200
    assert "disk-warning" in response.text


async def test_disk_warning_not_shown_when_under_80_percent(search_client):
    ac, session_factory = search_client
    with patch('src.web.router.shutil.disk_usage', return_value=DiskUsage(total=100, used=50, free=50)):
        response = await ac.get("/")
    assert response.status_code == 200
    assert "disk-warning" not in response.text
