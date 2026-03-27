import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import httpx
import ollama

from src.core.config import settings


# ---------------------------------------------------------------------------
# Test 1: happy path — returns cleaned text
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_returns_cleaned_text():
    mock_response = MagicMock()
    mock_response.response = "Call dentist. Work on homepage."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup
        result = await cleanup("uh I need to call the dentist um and work on homepage")

    assert result == "Call dentist. Work on homepage."


# ---------------------------------------------------------------------------
# Test 2: calls correct model from settings
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_calls_correct_model():
    mock_response = MagicMock()
    mock_response.response = "Cleaned text."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup
        await cleanup("some transcript")

    call_kwargs = mock_client.generate.call_args
    assert call_kwargs.kwargs.get("model") == settings.OLLAMA_MODEL or (
        len(call_kwargs.args) > 0 and call_kwargs.args[0] == settings.OLLAMA_MODEL
    )


# ---------------------------------------------------------------------------
# Test 3: prompt includes the raw transcript
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_includes_transcript_in_prompt():
    raw = "uh hello um world this is my note"

    mock_response = MagicMock()
    mock_response.response = "Hello world. This is my note."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup
        await cleanup(raw)

    call_kwargs = mock_client.generate.call_args
    prompt_arg = call_kwargs.kwargs.get("prompt") or call_kwargs.args[1]
    assert raw in prompt_arg


# ---------------------------------------------------------------------------
# Test 4: raises LLMServiceError on ollama.ResponseError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_raises_llm_error_on_response_error():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        side_effect=ollama.ResponseError("model not found")
    )

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup, LLMServiceError
        with pytest.raises(LLMServiceError):
            await cleanup("some transcript")


# ---------------------------------------------------------------------------
# Test 5: raises LLMServiceError on httpx.ConnectError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_raises_llm_error_on_connect_error():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup, LLMServiceError
        with pytest.raises(LLMServiceError):
            await cleanup("some transcript")


# ---------------------------------------------------------------------------
# Test 6: raises LLMServiceError with "timed out" on asyncio.TimeoutError
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_raises_llm_error_on_timeout():
    mock_client = MagicMock()
    mock_client.generate = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        from src.services.llm import cleanup, LLMServiceError
        with pytest.raises(LLMServiceError, match="timed out"):
            await cleanup("some transcript")


# ---------------------------------------------------------------------------
# Test 7: LLMServiceError is an Exception
# ---------------------------------------------------------------------------
def test_llm_service_error_is_exception():
    from src.services.llm import LLMServiceError
    err = LLMServiceError("test")
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Test 8: cleanup does NOT use run_in_executor
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cleanup_does_not_use_run_in_executor():
    mock_response = MagicMock()
    mock_response.response = "Cleaned text."

    mock_client = MagicMock()
    mock_client.generate = AsyncMock(return_value=mock_response)

    with patch("src.services.llm.ollama.AsyncClient", return_value=mock_client):
        loop = asyncio.get_event_loop()
        original_run_in_executor = loop.run_in_executor
        run_in_executor_called = []

        def tracking_run_in_executor(executor, func, *args):
            run_in_executor_called.append(True)
            return original_run_in_executor(executor, func, *args)

        loop.run_in_executor = tracking_run_in_executor
        try:
            from src.services.llm import cleanup
            await cleanup("some transcript")
        finally:
            loop.run_in_executor = original_run_in_executor

    assert not run_in_executor_called, "cleanup() should not use run_in_executor"
