import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import src.services.transcription as trans_module


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    def __init__(self, duration):
        self.duration = duration


# 1. test_transcribe_returns_text_and_duration
async def test_transcribe_returns_text_and_duration():
    with patch.object(trans_module, '_transcribe_sync', return_value=("Hello world", 5.0)):
        result = await trans_module.transcribe("fake.m4a")
        assert result == ("Hello world", 5.0)


# 2. test_transcribe_runs_in_executor (verifies sync func is called via executor)
async def test_transcribe_runs_in_executor():
    with patch.object(trans_module, '_transcribe_sync', return_value=("test", 3.0)) as mock_sync:
        result = await trans_module.transcribe("test.wav")
        assert result == ("test", 3.0)
        mock_sync.assert_called_once_with("test.wav")


# 3. test_model_singleton
def test_model_singleton():
    trans_module._model = None  # reset singleton
    with patch('faster_whisper.WhisperModel') as MockModel:
        MockModel.return_value = MagicMock()
        m1 = trans_module._get_model()
        m2 = trans_module._get_model()
        assert m1 is m2
        assert MockModel.call_count == 1
    trans_module._model = None  # clean up


# 4. test_model_init_args
def test_model_init_args():
    trans_module._model = None
    with patch('faster_whisper.WhisperModel') as MockModel:
        MockModel.return_value = MagicMock()
        trans_module._get_model()
        MockModel.assert_called_once()
        args, kwargs = MockModel.call_args
        assert kwargs.get('device') == 'cpu' or (len(args) > 1 and args[1] == 'cpu')
        assert kwargs.get('compute_type') == 'int8'
    trans_module._model = None  # clean up


# 5. test_save_transcript_creates_txt_file
def test_save_transcript(tmp_path):
    audio_file = tmp_path / "20240115T143022Z_ios.m4a"
    audio_file.touch()
    result_path = trans_module.save_transcript(str(audio_file), "Hello world")
    txt_file = tmp_path / "20240115T143022Z_ios.txt"
    assert txt_file.exists()
    assert txt_file.read_text() == "Hello world"
    assert result_path == str(txt_file)


# 6. test_save_transcript_returns_path (string type)
def test_save_transcript_returns_path(tmp_path):
    audio_file = tmp_path / "audio.m4a"
    audio_file.touch()
    result_path = trans_module.save_transcript(str(audio_file), "Some text")
    assert isinstance(result_path, str)


# 7. test_transcribe_propagates_error
async def test_transcribe_propagates_error():
    with patch.object(trans_module, '_transcribe_sync', side_effect=RuntimeError("CTranslate2 error")):
        with pytest.raises(RuntimeError, match="CTranslate2 error"):
            await trans_module.transcribe("bad.m4a")


# 8. test_transcribe_sync_joins_segments
def test_transcribe_sync_joins_segments():
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (
        iter([FakeSegment(" Hello"), FakeSegment(" world")]),
        FakeInfo(duration=5.0)
    )
    with patch.object(trans_module, '_get_model', return_value=fake_model):
        text, duration = trans_module._transcribe_sync("test.wav")
        assert text == "Hello world"
        assert duration == 5.0
