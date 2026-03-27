import pytest
import pytest_asyncio
import io
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from src.core.database import Base, get_db
from src.core.security import ingest_auth
from src.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_wav_bytes():
    """Minimal WAV file header — enough for filetype to detect audio/wav"""
    return (
        b'RIFF'
        + b'\x24\x00\x00\x00'
        + b'WAVE'
        + b'fmt '
        + b'\x10\x00\x00\x00'
        + b'\x01\x00\x01\x00'
        + b'\x44\xac\x00\x00'
        + b'\x88\x58\x01\x00'
        + b'\x02\x00\x10\x00'
        + b'data'
        + b'\x00\x00\x00\x00'
    )


def make_m4a_bytes():
    """Minimal ftyp box for M4A — filetype detects as audio/mp4"""
    return (
        b'\x00\x00\x00\x20ftyp'
        + b'M4A '
        + b'\x00\x00\x02\x00'
        + b'M4A '
        + b'mp42'
        + b'isom'
        + b'\x00' * 200
    )


def make_pdf_bytes():
    """PDF magic bytes"""
    return b'%PDF-1.4\n' + b'\x00' * 200


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Re-read settings
    import importlib
    import src.core.config as cfg_module
    importlib.reload(cfg_module)
    import src.core.database as db_module
    importlib.reload(db_module)

    # Patch settings in the ingest module so DATA_DIR points to tmp_path
    import src.api.ingest as ingest_module
    new_settings = cfg_module.Settings()
    monkeypatch.setattr(ingest_module, "settings", new_settings)

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    import src.models  # register models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[ingest_auth] = lambda: None  # bypass auth for most tests

    yield session_factory, tmp_path

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def client(test_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, test_db[0], test_db[1]


@pytest_asyncio.fixture
async def auth_client(test_db):
    # Remove auth override to test real auth
    if ingest_auth in app.dependency_overrides:
        del app.dependency_overrides[ingest_auth]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides[ingest_auth] = lambda: None  # restore


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_ingest_valid_m4a_returns_202(client):
    ac, session_factory, tmp_path = client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "ios"},
    )
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "pending"
    assert body["message"] == "Audio received and queued for processing."


async def test_ingest_creates_job_record(client):
    ac, session_factory, tmp_path = client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "test"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    from sqlalchemy import select
    from src.models.job import Job
    async with session_factory() as session:
        result = await session.execute(select(Job))
        jobs = result.scalars().all()

    assert len(jobs) == 1
    assert jobs[0].id == job_id
    assert jobs[0].status == "pending"
    assert jobs[0].audio_path is not None


async def test_ingest_saves_file_to_disk(client):
    ac, session_factory, tmp_path = client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "ios"},
    )
    assert response.status_code == 202

    from sqlalchemy import select
    from src.models.job import Job
    import os
    async with session_factory() as session:
        result = await session.execute(select(Job))
        job = result.scalars().first()

    assert job is not None
    assert os.path.exists(job.audio_path)


async def test_ingest_missing_token_returns_401(auth_client):
    ac = auth_client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "ios"},
    )
    assert response.status_code == 401


async def test_ingest_wrong_token_returns_401(auth_client):
    ac = auth_client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        headers={"Authorization": "Bearer wrong-token-value"},
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "ios"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["error"]["code"] == "UNAUTHORIZED"


async def test_ingest_invalid_file_type_returns_400(client):
    ac, session_factory, tmp_path = client
    pdf_bytes = make_pdf_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        data={"source": "ios"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_AUDIO"


async def test_ingest_pdf_with_audio_content_type_rejected(client):
    ac, session_factory, tmp_path = client
    pdf_bytes = make_pdf_bytes()
    # Send PDF bytes but claim Content-Type audio/m4a — should still be rejected
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.m4a", io.BytesIO(pdf_bytes), "audio/m4a")},
        data={"source": "ios"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "INVALID_AUDIO"


async def test_ingest_source_tag_stored(client):
    ac, session_factory, tmp_path = client
    wav_bytes = make_wav_bytes()
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
        data={"source": "ios"},
    )
    assert response.status_code == 202

    from sqlalchemy import select
    from src.models.job import Job
    async with session_factory() as session:
        result = await session.execute(select(Job))
        job = result.scalars().first()

    assert job.source_tag == "ios"


async def test_ingest_default_source_tag(client):
    ac, session_factory, tmp_path = client
    wav_bytes = make_wav_bytes()
    # POST without source field
    response = await ac.post(
        "/api/ingest",
        files={"audio": ("test.wav", io.BytesIO(wav_bytes), "audio/wav")},
    )
    assert response.status_code == 202

    from sqlalchemy import select
    from src.models.job import Job
    async with session_factory() as session:
        result = await session.execute(select(Job))
        job = result.scalars().first()

    assert job.source_tag == "unknown"
