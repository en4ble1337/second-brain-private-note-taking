"""Tests for src/core/config.py — Settings loading and validation."""
import os
import pytest


def test_settings_loads_ingest_token(monkeypatch):
    """INGEST_TOKEN is loaded correctly from environment."""
    monkeypatch.setenv("INGEST_TOKEN", "abc123token")
    from src.core.config import Settings
    s = Settings(_env_file=None)
    assert s.INGEST_TOKEN == "abc123token"


def test_settings_missing_ingest_token_raises(monkeypatch):
    """Missing INGEST_TOKEN raises a ValidationError."""
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    from src.core.config import Settings
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_settings_empty_ingest_token_raises(monkeypatch):
    """Empty INGEST_TOKEN raises a ValidationError."""
    monkeypatch.setenv("INGEST_TOKEN", "")
    from src.core.config import Settings
    with pytest.raises(Exception):
        Settings(_env_file=None)


def test_settings_defaults(monkeypatch):
    """Optional fields have correct defaults."""
    monkeypatch.setenv("INGEST_TOKEN", "mytoken")
    from src.core.config import Settings
    s = Settings(_env_file=None)
    assert s.SECRET_KEY == "changeme"
    assert s.OLLAMA_BASE_URL == "http://127.0.0.1:11434"
    assert s.OLLAMA_MODEL == "llama3.2:3b"
    assert s.OLLAMA_TIMEOUT_SECONDS == 120
    assert s.WHISPER_MODEL == "base"
    assert s.DATA_DIR == "./data"
    assert s.MAX_AUDIO_SIZE_MB == 500
    assert s.WORKER_POLL_INTERVAL == 2
    assert s.HOST == "0.0.0.0"
    assert s.PORT == 80


def test_settings_overrides_from_env(monkeypatch):
    """Environment variables override defaults."""
    monkeypatch.setenv("INGEST_TOKEN", "tok123")
    monkeypatch.setenv("OLLAMA_MODEL", "mistral:7b")
    monkeypatch.setenv("MAX_AUDIO_SIZE_MB", "250")
    monkeypatch.setenv("PORT", "8080")
    from src.core.config import Settings
    s = Settings(_env_file=None)
    assert s.OLLAMA_MODEL == "mistral:7b"
    assert s.MAX_AUDIO_SIZE_MB == 250
    assert s.PORT == 8080
