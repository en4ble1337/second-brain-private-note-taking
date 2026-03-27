import logging
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.job import Job, JobStatus
from src.services import transcription as transcription_service
from src.services import llm as llm_service
from src.services import note_service
from src.services.llm import LLMServiceError
from src.core.config import settings

logger = logging.getLogger(__name__)


async def run_pipeline(db: AsyncSession, job: Job) -> None:
    """Drive a Job through the full transcribe → clean → store pipeline.

    Updates Job.status at each stage. On LLM failure, falls back to raw_transcript.
    On transcription failure, marks Job as failed and re-raises.
    Always commits status changes immediately for durability.
    """
    try:
        # Stage 1: Transcribe
        job.status = JobStatus.transcribing.value
        await db.commit()

        raw_text, duration = await transcription_service.transcribe(job.audio_path)
        transcript_path = transcription_service.save_transcript(job.audio_path, raw_text)

        job.transcript_path = transcript_path
        job.audio_duration_seconds = duration
        await db.commit()

        # Stage 2: LLM cleanup
        job.status = JobStatus.cleaning.value
        await db.commit()

        llm_model_used = settings.OLLAMA_MODEL
        try:
            cleaned_text = await llm_service.cleanup(raw_text)
        except LLMServiceError as e:
            logger.warning(
                "LLM cleanup failed for job %s, using raw transcript: %s",
                job.id, str(e)
            )
            cleaned_text = raw_text
            llm_model_used = "none (fallback)"

        # Stage 3: Store note
        await note_service.create_note(
            db,
            job_id=job.id,
            audio_path=job.audio_path,
            raw_transcript=raw_text,
            cleaned_text=cleaned_text,
            audio_duration_seconds=duration,
            llm_model=llm_model_used,
        )

        job.status = JobStatus.complete.value
        job.completed_at = datetime.utcnow()
        await db.commit()

    except LLMServiceError:
        # Should never reach here — caught above — but guard just in case
        raise
    except Exception as e:
        logger.error(
            "Pipeline failed for job %s: %s",
            job.id, str(e), exc_info=True
        )
        job.status = JobStatus.failed.value
        job.error_message = str(e)
        job.completed_at = datetime.utcnow()
        await db.commit()
        raise
