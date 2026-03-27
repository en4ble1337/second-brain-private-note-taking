from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from faster_whisper import WhisperModel as WhisperModelType

_model: "WhisperModelType | None" = None
_executor = ThreadPoolExecutor(max_workers=1)


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        from src.core.config import settings
        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )
    return _model


def _transcribe_sync(audio_path: str) -> tuple[str, float]:
    model = _get_model()
    segments, info = model.transcribe(audio_path, beam_size=5)
    text = " ".join(segment.text.strip() for segment in segments)
    return text, info.duration


def save_transcript(audio_path: str, text: str) -> str:
    """Save transcript as .txt alongside the audio file. Returns transcript path."""
    audio = Path(audio_path)
    transcript_path = audio.with_suffix(".txt")
    transcript_path.write_text(text, encoding="utf-8")
    return str(transcript_path)


async def transcribe(audio_path: str) -> tuple[str, float]:
    """Transcribe audio file. Returns (raw_text, duration_seconds).
    Runs faster-whisper in a ThreadPoolExecutor to avoid blocking the event loop.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _transcribe_sync, audio_path)
    return result
