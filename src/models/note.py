from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class Note(Base):
    __tablename__ = "note"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True, default=lambda: str(uuid4()))
    job_id: Mapped[str] = mapped_column(sa.String, sa.ForeignKey("job.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    audio_path: Mapped[str] = mapped_column(sa.String)
    raw_transcript: Mapped[str] = mapped_column(sa.Text)
    cleaned_text: Mapped[str] = mapped_column(sa.Text)
    audio_duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    llm_model: Mapped[str] = mapped_column(sa.String(128), default="")
    search_vector: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
