import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from src.models.job import Job, JobStatus
from src.services import pipeline
from src.core.config import settings

logger = logging.getLogger(__name__)


async def process_next_pending_job(session_factory: async_sessionmaker) -> bool:
    """Pick up one pending Job and run it through the pipeline.

    Returns True if a job was processed, False if the queue was empty.
    Catches all exceptions from run_pipeline so the worker loop continues.
    """
    async with session_factory() as db:
        # Find the oldest pending job
        result = await db.execute(
            select(Job)
            .where(Job.status == JobStatus.pending.value)
            .order_by(Job.received_at.asc())
            .limit(1)
        )
        job = result.scalar_one_or_none()

        if job is None:
            return False

        # Immediately claim it to prevent double-processing
        job.status = JobStatus.transcribing.value
        await db.commit()

        try:
            await pipeline.run_pipeline(db, job)
        except Exception as e:
            logger.error(
                "Worker: unhandled exception for job %s: %s",
                job.id, str(e), exc_info=True
            )
            # Job is already marked failed by run_pipeline before re-raising

        return True


async def run_worker_loop(session_factory: async_sessionmaker) -> None:
    """Continuously poll for pending jobs and process them one at a time.

    Runs until cancelled (via asyncio.CancelledError on app shutdown).
    """
    logger.info("Worker loop started, poll interval=%ss", settings.WORKER_POLL_INTERVAL)
    while True:
        try:
            await process_next_pending_job(session_factory)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Worker loop error (continuing): %s", str(e), exc_info=True)
        await asyncio.sleep(settings.WORKER_POLL_INTERVAL)
