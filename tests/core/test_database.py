"""Tests for src/core/database.py — async SQLite engine, init_db, get_db."""
import pytest
import pytest_asyncio
from pathlib import Path


@pytest.mark.asyncio
async def test_init_db_creates_db_file(tmp_path, monkeypatch):
    """init_db() creates the brain.db file in DATA_DIR/db/."""
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import src.core.config as cfg_mod
    import src.core.database as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    from src.core.database import init_db
    await init_db()

    db_file = tmp_path / "db" / "brain.db"
    assert db_file.exists(), f"brain.db not found at {db_file}"


@pytest.mark.asyncio
async def test_init_db_creates_notes_fts_table(tmp_path, monkeypatch):
    """init_db() creates the notes_fts FTS5 virtual table."""
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import src.core.config as cfg_mod
    import src.core.database as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    from src.core.database import init_db
    await init_db()

    # Query sqlite_master to confirm the virtual table exists
    from sqlalchemy import text
    from src.core.database import engine as eng
    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='notes_fts'")
        )
        rows = result.fetchall()
    assert len(rows) == 1, "notes_fts virtual table not found"


@pytest.mark.asyncio
async def test_init_db_creates_fts_triggers_when_note_table_exists(tmp_path, monkeypatch):
    """init_db() creates all three FTS sync triggers when the note table is present."""
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import src.core.config as cfg_mod
    import src.core.database as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    from src.core.database import init_db, Base
    from sqlalchemy import Column, Integer, Text

    # Register a minimal 'note' table with Base so create_all() creates it
    # (mimicking what Directive 003 ORM models will do)
    from sqlalchemy.orm import DeclarativeBase
    from src.core.database import Base

    # Use SQLAlchemy Table directly to avoid redefining class across test runs
    from sqlalchemy import Table, MetaData, Column, Integer, Text
    note_table = Table(
        "note",
        Base.metadata,
        Column("rowid", Integer, primary_key=True),
        Column("search_vector", Text, nullable=True),
        keep_existing=True,
    )

    await init_db()

    from sqlalchemy import text
    from src.core.database import engine as eng
    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='trigger'")
        )
        trigger_names = {row[0] for row in result.fetchall()}

    assert "notes_fts_insert" in trigger_names
    assert "notes_fts_update" in trigger_names
    assert "notes_fts_delete" in trigger_names


@pytest.mark.asyncio
async def test_init_db_is_idempotent(tmp_path, monkeypatch):
    """Calling init_db() twice does not raise an error."""
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import src.core.config as cfg_mod
    import src.core.database as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    from src.core.database import init_db
    await init_db()
    await init_db()  # Should not raise


@pytest.mark.asyncio
async def test_get_db_yields_async_session(tmp_path, monkeypatch):
    """get_db() yields an AsyncSession that can execute queries."""
    monkeypatch.setenv("INGEST_TOKEN", "test-token")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    import importlib
    import src.core.config as cfg_mod
    import src.core.database as db_mod
    importlib.reload(cfg_mod)
    importlib.reload(db_mod)

    from src.core.database import init_db, get_db
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text

    await init_db()

    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    # Execute a trivial query to confirm session is live
    result = await session.execute(text("SELECT 1"))
    assert result.scalar() == 1
    # Close the generator
    try:
        await gen.aclose()
    except Exception:
        pass
