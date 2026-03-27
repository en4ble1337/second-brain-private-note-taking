from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import NullPool
from sqlalchemy import text

Base = declarative_base()
engine = None  # initialized by init_db
AsyncSessionLocal = None


async def init_db():
    global engine, AsyncSessionLocal
    import src.models  # noqa: F401 — registers Job, Note with Base before create_all
    from src.core.config import Settings
    from pathlib import Path

    settings = Settings()
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.DATA_DIR + "/db").mkdir(parents=True, exist_ok=True)
    db_path = str(Path(settings.DATA_DIR) / "db" / "brain.db")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts "
            "USING fts5(search_vector, content='note', content_rowid='rowid')"
        ))
        # Check whether the 'note' table exists before creating triggers that reference it.
        # The 'note' table is defined in Directive 003 (ORM models). When models are registered
        # with Base before init_db() is called, create_all() above will have created it.
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='note'")
        )
        note_table_exists = result.fetchone() is not None

        if note_table_exists:
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


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
