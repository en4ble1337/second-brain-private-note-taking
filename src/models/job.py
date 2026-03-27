from datetime import datetime
from enum import Enum
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class JobStatus(str, Enum):
    pending = "pending"
    transcribing = "transcribing"
    cleaning = "cleaning"
    complete = "complete"
    failed = "failed"


class Job(Base):
    __tablename__ = "job"

    id: Mapped[str] = mapped_column(sa.String, primary_key=True, default=lambda: str(uuid4()))
    status: Mapped[str] = mapped_column(sa.String, default=JobStatus.pending.value)
    source_tag: Mapped[str] = mapped_column(sa.String(64), default="unknown")
    audio_path: Mapped[str] = mapped_column(sa.String)
    transcript_path: Mapped[str | None] = mapped_column(sa.String, nullable=True)
    audio_duration_seconds: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
