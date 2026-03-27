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
async def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INGEST_TOKEN", "test-token-123456")

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

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


async def seed_note_and_job(session_factory, cleaned_text="Hello world.", raw_transcript="Hello world"):
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
        return job.id, note.id


async def test_get_notes_returns_200_json(api_client):
    ac, session_factory = api_client
    response = await ac.get("/api/notes")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]


async def test_get_notes_returns_correct_schema(api_client):
    ac, session_factory = api_client
    response = await ac.get("/api/notes")
    assert response.status_code == 200
    body = response.json()
    assert "notes" in body
    assert "total" in body
    assert "page" in body
    assert isinstance(body["notes"], list)


async def test_get_notes_empty(api_client):
    ac, session_factory = api_client
    response = await ac.get("/api/notes")
    assert response.status_code == 200
    body = response.json()
    assert body == {"notes": [], "total": 0, "page": 1}


async def test_get_notes_with_data(api_client):
    ac, session_factory = api_client
    job_id, note_id = await seed_note_and_job(session_factory, cleaned_text="My cleaned text")
    response = await ac.get("/api/notes")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["notes"]) == 1
    note = body["notes"][0]
    assert "id" in note
    assert "cleaned_text" in note
    assert "created_at" in note
    assert note["cleaned_text"] == "My cleaned text"


async def test_get_notes_search(api_client):
    ac, session_factory = api_client
    await seed_note_and_job(
        session_factory,
        cleaned_text="Call dentist tomorrow.",
        raw_transcript="Call dentist tomorrow",
    )

    # Search that should match
    response = await ac.get("/api/notes?q=dentist")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["notes"]) == 1

    # Search that should not match
    response = await ac.get("/api/notes?q=xyzzy")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["notes"] == []


async def test_get_job_status_complete(api_client):
    ac, session_factory = api_client
    job_id, note_id = await seed_note_and_job(session_factory)
    response = await ac.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["note_id"] == note_id
    assert body["id"] == job_id


async def test_get_job_status_not_found(api_client):
    ac, session_factory = api_client
    response = await ac.get("/api/jobs/nonexistent-id")
    assert response.status_code == 404
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "NOT_FOUND"


async def test_get_job_status_no_note(api_client):
    ac, session_factory = api_client
    from src.models.job import Job, JobStatus
    async with session_factory() as session:
        job = Job(id=str(uuid4()), audio_path="/data/raw/test.m4a", status=JobStatus.pending.value)
        session.add(job)
        await session.commit()
        job_id = job.id

    response = await ac.get(f"/api/jobs/{job_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["note_id"] is None
    assert body["status"] == "pending"
