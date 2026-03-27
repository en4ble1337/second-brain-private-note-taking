from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NoteSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    audio_duration_seconds: float | None
    cleaned_text: str
    raw_transcript: str
    audio_path: str
    llm_model: str


class JobStatusResponse(BaseModel):
    id: str
    status: str
    note_id: str | None
    error_message: str | None


class NoteListResponse(BaseModel):
    notes: list[NoteSchema]
    total: int
    page: int
