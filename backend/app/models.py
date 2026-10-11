"""Database tables. Any change here needs a new Alembic migration."""

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator):
    """SQLite has no timezone support: store UTC, and always hand back timezone-aware values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to UtcDateTime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect):
        return None if value is None else value.replace(tzinfo=UTC)


class Job(Base):
    """One request to analyse a recording. The rows with status "queued" are the queue."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # "analysis" measures an uploaded recording. "coaching" only writes the coaching of an
    # analysis that already exists, and has no audio of its own.
    kind: Mapped[str] = mapped_column(String(16), default="analysis", server_default="analysis")
    # Whose recording this is: the user's own "take", or a "reference" to compare takes with.
    role: Mapped[str] = mapped_column(String(16), default="take", server_default="take")
    # The name the user gave a reference recording.
    title: Mapped[str | None] = mapped_column(String(120))
    # queued -> running -> succeeded | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), index=True)
    # What the worker is doing right now; only meaningful while running.
    stage: Mapped[str | None] = mapped_column(String(32))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    # How many times a worker has started this job.
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    # Sent by the browser so a double click cannot create two jobs.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)

    profile: Mapped[str] = mapped_column(String(32))
    language_hint: Mapped[str] = mapped_column(String(16))
    retain_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    # Display name only, never a path.
    original_filename: Mapped[str | None] = mapped_column(String(255))
    # Path of the uploaded file, relative to the data folder. Null once it has been deleted.
    audio_path: Mapped[str | None] = mapped_column(String(255))

    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_retryable: Mapped[bool] = mapped_column(Boolean, default=False)

    analysis_id: Mapped[str | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    # Refreshed by the worker every few seconds while it is running this job.
    heartbeat_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class Analysis(Base):
    """The stored result of a job that succeeded.

    The measurements in `result` are never changed afterwards. Only `coaching` can be
    written again, because it is an interpretation of them.
    """

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    # "take" or "reference". References are listed separately and get no coaching.
    role: Mapped[str] = mapped_column(String(16), default="take", server_default="take", index=True)
    title: Mapped[str | None] = mapped_column(String(120))
    profile: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16))
    duration_seconds: Mapped[float] = mapped_column(Float)
    schema_version: Mapped[int] = mapped_column(Integer)
    # Version of the thresholds that produced the numbers (also stored in full inside `result`).
    settings_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    # The complete AnalysisResult as JSON, without the coaching.
    result: Mapped[dict] = mapped_column(JSON)
    # The coaching for this result, as JSON. Null for results stored before coaching existed.
    coaching: Mapped[dict | None] = mapped_column(JSON)
    # The outline of the sound wave, for drawing only. Kept apart from the measurements,
    # which never read it. Null for results stored before waveforms existed.
    waveform: Mapped[dict | None] = mapped_column(JSON)
    # Only set when the user asked for the recording to be kept.
    audio_path: Mapped[str | None] = mapped_column(String(255))


class WorkerState(Base):
    """A single row (id 1) through which the worker tells the API that it is alive."""

    __tablename__ = "worker_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    heartbeat_at: Mapped[datetime] = mapped_column(UtcDateTime)
    speech_model: Mapped[str] = mapped_column(String(64))
    speech_model_ready: Mapped[bool] = mapped_column(Boolean)
    # The language model used for coaching, and whether it could answer when last checked:
    # ready, not_running, model_missing, not_local or off.
    coach_model: Mapped[str | None] = mapped_column(String(64))
    coach_status: Mapped[str | None] = mapped_column(String(32))
