import asyncio
import ollama
import httpx

from src.core.config import settings

CLEANUP_SYSTEM_PROMPT = """\
You are a note cleanup assistant. The user has provided a raw voice note transcript.
Your task: correct grammar, remove filler words (uh, um, like, you know, sort of),
preserve all meaningful content, and format as a clean note. If the transcript contains
multiple distinct items (tasks, ideas, reminders), format them as a bullet list starting
with "- ". Output only the cleaned note — no preamble, no commentary, no explanation.\
"""


class LLMServiceError(Exception):
    """Raised when Ollama is unreachable, returns an error, or times out."""
    pass


async def cleanup(raw_transcript: str) -> str:
    """Send raw transcript to local Ollama LLM for cleanup. Returns cleaned text.

    Raises LLMServiceError if Ollama is unreachable, returns an error, or times out.
    Does NOT handle the fallback — that is PipelineService's responsibility.
    """
    prompt = f"{CLEANUP_SYSTEM_PROMPT}\n\nRaw transcript:\n{raw_transcript}"

    try:
        client = ollama.AsyncClient(host=settings.OLLAMA_BASE_URL)
        response = await asyncio.wait_for(
            client.generate(model=settings.OLLAMA_MODEL, prompt=prompt),
            timeout=settings.OLLAMA_TIMEOUT_SECONDS,
        )
        return response.response
    except asyncio.TimeoutError as e:
        raise LLMServiceError(
            f"Ollama timed out after {settings.OLLAMA_TIMEOUT_SECONDS}s"
        ) from e
    except ollama.ResponseError as e:
        raise LLMServiceError(f"Ollama response error: {e}") from e
    except httpx.ConnectError as e:
        raise LLMServiceError(
            f"Cannot connect to Ollama at {settings.OLLAMA_BASE_URL}: {e}"
        ) from e
    except Exception as e:
        # Catch any other httpx or network errors
        if "connect" in str(e).lower() or "connection" in str(e).lower():
            raise LLMServiceError(f"Ollama connection error: {e}") from e
        raise
