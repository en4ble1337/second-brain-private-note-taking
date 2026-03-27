from contextlib import asynccontextmanager
from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    from src.core.database import init_db, AsyncSessionLocal
    await init_db()

    # Warm up Whisper model in background thread (avoids cold-start on first job)
    import asyncio
    from src.services.transcription import _get_model
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _get_model)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Whisper warmup skipped: %s", e)

    # Launch background worker
    from src.worker.loop import run_worker_loop
    worker_task = asyncio.create_task(run_worker_loop(AsyncSessionLocal))

    yield

    # Graceful shutdown
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Local Second Brain", lifespan=lifespan)

from src.api.ingest import router as ingest_router
app.include_router(ingest_router)

from fastapi.staticfiles import StaticFiles
from src.web.router import router as web_router
from src.api.audio import router as audio_router
from src.api.notes import router as notes_router

app.mount("/static", StaticFiles(directory="src/web/static"), name="static")
app.include_router(web_router)
app.include_router(audio_router)
app.include_router(notes_router)
