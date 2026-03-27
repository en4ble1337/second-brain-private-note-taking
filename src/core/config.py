from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    INGEST_TOKEN: str
    SECRET_KEY: str = "changeme"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"
    OLLAMA_TIMEOUT_SECONDS: int = 120
    WHISPER_MODEL: str = "base"
    DATA_DIR: str = "./data"
    MAX_AUDIO_SIZE_MB: int = 500
    WORKER_POLL_INTERVAL: int = 2
    HOST: str = "0.0.0.0"
    PORT: int = 80

    @field_validator("INGEST_TOKEN")
    @classmethod
    def ingest_token_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("INGEST_TOKEN must not be empty")
        return v


settings = Settings()
