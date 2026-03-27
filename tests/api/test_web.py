import pytest
import pytest_asyncio
from datetime import datetime
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from src.core.database import Base, get_db
from src.core.security import ingest_auth
import src.models


@pytest_asyncio.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INGEST_TOKEN", "test-token")

    # Patch settings.DATA_DIR on the web router and audio modules
    import src.web.router as web_router_module
    import src.api.audio as audio_module
    import src.core.config as config_module
    monkeypatch.setattr(web_router_module.settings, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(audio_module.settings, 'DATA_DIR', str(tmp_path))

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

    # Create raw dir
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def create_test_note(session_factory, cleaned_text="Test note content", raw_transcript="test raw"):
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
            audio_duration_seconds=5.0,
            llm_model="llama3.2:3b",
            search_vector=f"{raw_transcript} {cleaned_text}",
        )
        session.add(note)
        await session.commit()
        return note.id


async def test_inbox_returns_200(app_client):
    ac, session_factory = app_client
    response = await ac.get("/")
    assert response.status_code == 200


async def test_inbox_empty_state(app_client):
    ac, session_factory = app_client
    response = await ac.get("/")
    assert response.status_code == 200
    assert "No notes yet" in response.text


async def test_inbox_shows_notes(app_client):
    ac, session_factory = app_client
    note_id = await create_test_note(session_factory, cleaned_text="My unique note content here")
    response = await ac.get("/")
    assert response.status_code == 200
    assert "My unique note content here" in response.text


async def test_inbox_shows_timestamp(app_client):
    ac, session_factory = app_client
    await create_test_note(session_factory)
    response = await ac.get("/")
    assert response.status_code == 200
    # Should contain a formatted date like 2026-03-26
    import re
    assert re.search(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}', response.text)


async def test_note_detail_returns_200(app_client):
    ac, session_factory = app_client
    note_id = await create_test_note(session_factory)
    response = await ac.get(f"/notes/{note_id}")
    assert response.status_code == 200


async def test_note_detail_contains_cleaned_text(app_client):
    ac, session_factory = app_client
    note_id = await create_test_note(session_factory, cleaned_text="Detailed cleaned text for note")
    response = await ac.get(f"/notes/{note_id}")
    assert response.status_code == 200
    assert "Detailed cleaned text for note" in response.text


async def test_note_detail_contains_raw_transcript(app_client):
    ac, session_factory = app_client
    note_id = await create_test_note(session_factory, raw_transcript="raw transcript content here")
    response = await ac.get(f"/notes/{note_id}")
    assert response.status_code == 200
    assert "raw transcript content here" in response.text


async def test_note_detail_contains_audio_player(app_client):
    ac, session_factory = app_client
    note_id = await create_test_note(session_factory)
    response = await ac.get(f"/notes/{note_id}")
    assert response.status_code == 200
    assert "<audio" in response.text


async def test_note_detail_404_for_missing(app_client):
    ac, session_factory = app_client
    response = await ac.get("/notes/nonexistent")
    assert response.status_code == 404


async def test_audio_serve_existing_file(app_client, tmp_path):
    ac, session_factory = app_client
    # Create a real audio file in tmp_path/raw/
    audio_file = tmp_path / "raw" / "test_audio.m4a"
    audio_file.write_bytes(b"fake audio data")
    response = await ac.get("/audio/test_audio.m4a")
    assert response.status_code == 200


async def test_audio_serve_missing_file(app_client):
    ac, session_factory = app_client
    response = await ac.get("/audio/doesnotexist.m4a")
    assert response.status_code == 404


async def test_audio_path_traversal_rejected(app_client):
    ac, session_factory = app_client
    response = await ac.get("/audio/../../../etc/passwd")
    assert response.status_code == 404
