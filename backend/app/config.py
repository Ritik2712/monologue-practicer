"""Runtime settings, read from environment variables (optionally via the repo-root .env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")


# The frontend dev server may land on any free port, so any localhost origin is allowed.
LOCAL_ORIGIN_REGEX = r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"


@dataclass(frozen=True)
class Settings:
    database_url: str
    # Extra origins on top of localhost, e.g. a phone on the same network.
    frontend_origins: tuple[str, ...]
    # Where uploaded and retained audio lives. Never inside the repository's tracked files.
    data_dir: Path
    max_upload_bytes: int
    max_audio_seconds: float
    # faster-whisper model name (tiny, base, small, medium, large-v3) or a local folder.
    whisper_model: str
    whisper_compute_type: str
    # How long the audio of a failed-but-retryable job is kept so that Retry can work.
    failed_audio_retention_hours: float
    # How many times a job is started again after the worker died while running it.
    max_job_attempts: int
    worker_poll_seconds: float
    log_level: str
    # False switches the language model off: coaching then comes from fixed templates only.
    ai_coaching: bool
    # The Ollama server and model used for coaching. The address must be on this computer.
    ollama_base_url: str
    ollama_model: str
    # How long one answer from the model may take before it is abandoned.
    ollama_timeout_seconds: float
    # How much text the model can take in at once, in tokens.
    ollama_context_tokens: int


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def get_settings() -> Settings:
    default_db = f"sqlite:///{BACKEND_DIR / 'data' / 'monologue_coach.db'}"
    origins = os.environ.get("FRONTEND_ORIGINS") or ""
    data_dir = Path(os.environ.get("DATA_DIR") or BACKEND_DIR / "data").expanduser().resolve()
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or default_db,
        frontend_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        data_dir=data_dir,
        max_upload_bytes=int(_number("MAX_UPLOAD_MB", 50) * 1024 * 1024),
        max_audio_seconds=_number("MAX_AUDIO_MINUTES", 10) * 60,
        whisper_model=os.environ.get("WHISPER_MODEL") or "small",
        whisper_compute_type=os.environ.get("WHISPER_COMPUTE_TYPE") or "int8",
        failed_audio_retention_hours=_number("FAILED_AUDIO_RETENTION_HOURS", 24),
        max_job_attempts=int(_number("MAX_JOB_ATTEMPTS", 2)),
        worker_poll_seconds=_number("WORKER_POLL_SECONDS", 1),
        log_level=(os.environ.get("LOG_LEVEL") or "INFO").upper(),
        ai_coaching=(os.environ.get("AI_COACHING") or "on").strip().lower()
        not in ("off", "0", "false", "no"),
        ollama_base_url=os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434",
        ollama_model=os.environ.get("OLLAMA_MODEL") or "llama3.1:8b",
        ollama_timeout_seconds=_number("OLLAMA_TIMEOUT_SECONDS", 180),
        ollama_context_tokens=int(_number("OLLAMA_CONTEXT_TOKENS", 8192)),
    )


settings = get_settings()
