"""The worker: a separate program that takes jobs from the queue one at a time and runs
the audio pipeline on them, so the API never has to wait for slow work.

Start it from the backend folder, next to the API:

    uv run python -m app.worker

Stop it with Ctrl+C. It finishes its current step, puts the job back in the queue and exits.
"""

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app import job_queue, uploads
from app.config import settings
from app.models import Job, WorkerState, utcnow
from app.pipeline.errors import JobCancelled, PipelineError, WorkerStopping
from app.pipeline.runner import PipelineDeps, run_analysis
from app.pipeline.settings import DEFAULT_SETTINGS, AnalysisSettings

logger = logging.getLogger("app.worker")

HEARTBEAT_SECONDS = 3
MAINTENANCE_SECONDS = 60
# An upload no job refers to is left alone this long, in case its job is just being created.
STRAY_UPLOAD_SECONDS = 3600

STAGE_DESCRIPTIONS = {
    "preparing_audio": "reading the audio",
    "detecting_speech": "detecting speech",
    "transcribing": "transcribing",
    "measuring_audio": "measuring the audio",
}


class Worker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        deps: PipelineDeps,
        *,
        data_dir: Path | None = None,
        analysis_settings: AnalysisSettings = DEFAULT_SETTINGS,
        max_audio_seconds: float | None = None,
        max_attempts: int = 2,
        failed_audio_retention_hours: float = 24,
        speech_model_ready: Callable[[], bool] = lambda: True,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session_factory = session_factory
        self.deps = deps
        self.data_dir = data_dir
        self.analysis_settings = analysis_settings
        self.max_audio_seconds = max_audio_seconds
        self.max_attempts = max_attempts
        self.failed_audio_retention_hours = failed_audio_retention_hours
        self.speech_model_ready = speech_model_ready
        self.clock = clock
        self.stop_event = threading.Event()
        self.current_job_id: str | None = None

    # --- One job -------------------------------------------------------------------------

    def process_next_job(self) -> bool:
        """Runs one queued job to the end. Returns False if there was nothing to do."""
        with self.session_factory() as session:
            job = job_queue.claim_next_job(session, self.clock())
            if job is None:
                return False
            job_id, short_id = job.id, job.id[:8]
            audio_path = job.audio_path
            profile, language = job.profile, job.language_hint
            attempt = job.attempt

        self.current_job_id = job_id
        started = time.monotonic()
        stage = "preparing_audio"
        logger.info("job %s started (attempt %d)", short_id, attempt)

        def on_stage(name: str) -> None:
            nonlocal stage
            stage = name
            with self.session_factory() as session:
                job_queue.set_stage(session, job_id, name, self.clock())
            logger.info("job %s: %s", short_id, name)

        def check() -> None:
            # Called by the pipeline between steps: the only places a job can stop safely.
            with self.session_factory() as session:
                if job_queue.is_cancel_requested(session, job_id):
                    raise JobCancelled
            if self.stop_event.is_set():
                raise WorkerStopping

        try:
            if not audio_path or not uploads.audio_exists(audio_path, self.data_dir):
                raise PipelineError("audio_missing", "The uploaded audio is no longer available.")
            body = run_analysis(
                uploads.absolute(audio_path, self.data_dir),
                profile=profile,
                language=language,
                settings=self.analysis_settings,
                max_seconds=self.max_audio_seconds,
                deps=self.deps,
                on_stage=on_stage,
                check=check,
            )
            check()
            with self.session_factory() as session:
                job = session.get(Job, job_id)
                saved = job_queue.complete_job(
                    session, job, body, self.analysis_settings.version, self.clock(), self.data_dir
                )
            if saved is None:
                raise JobCancelled
            logger.info("job %s succeeded in %.1fs", short_id, time.monotonic() - started)
        except JobCancelled:
            with self.session_factory() as session:
                job_queue.finish_cancelled(session, job_id, self.clock(), self.data_dir)
            logger.info("job %s cancelled", short_id)
        except WorkerStopping:
            with self.session_factory() as session:
                job_queue.release_job(session, job_id, self.clock())
            logger.info("job %s returned to the queue (worker stopping)", short_id)
        except PipelineError as error:
            self._fail(job_id, error.code, error.message, error.retryable)
            logger.warning("job %s failed: %s", short_id, error.code)
        except Exception as error:
            # The message shown to the user names the step and the kind of error only. The
            # full traceback, which contains local paths, is logged at debug level.
            self._fail(
                job_id,
                "unexpected_error",
                f"Something went wrong while {STAGE_DESCRIPTIONS.get(stage, stage)} "
                f"({type(error).__name__}).",
                True,
            )
            logger.error("job %s failed unexpectedly: %s", short_id, type(error).__name__)
            logger.debug("job %s traceback", short_id, exc_info=True)
        finally:
            self.current_job_id = None
        return True

    def _fail(self, job_id: str, code: str, message: str, retryable: bool) -> None:
        with self.session_factory() as session:
            job_queue.fail_job(
                session,
                job_id,
                code=code,
                message=message,
                retryable=retryable,
                now=self.clock(),
                data_dir=self.data_dir,
            )

    # --- Housekeeping --------------------------------------------------------------------

    def beat(self, *, starting: bool = False) -> None:
        """Tells the API this worker is alive, and which job it is still working on."""
        now = self.clock()
        with self.session_factory() as session:
            job_queue.report_worker(
                session,
                pid=os.getpid(),
                now=now,
                speech_model=self.deps.transcriber.name,
                speech_model_ready=self.speech_model_ready(),
                starting=starting,
            )
            if self.current_job_id:
                job_queue.touch_job(session, self.current_job_id, now)

    def recover(self, *, stale_after_seconds: float) -> None:
        with self.session_factory() as session:
            requeued, ended = job_queue.recover_orphaned_jobs(
                session,
                self.clock(),
                stale_after_seconds=stale_after_seconds,
                max_attempts=self.max_attempts,
                data_dir=self.data_dir,
            )
        if requeued or ended:
            logger.info("recovered interrupted jobs: %d requeued, %d ended", requeued, ended)

    def clean_up_files(self) -> None:
        with self.session_factory() as session:
            expired = job_queue.expire_failed_audio(
                session, self.clock(), self.failed_audio_retention_hours, self.data_dir
            )
            known = job_queue.referenced_upload_paths(session)
        stray = uploads.delete_stray_uploads(known, STRAY_UPLOAD_SECONDS, self.data_dir)
        if expired or stray:
            logger.info("removed %d expired and %d stray audio files", expired, stray)

    def another_worker_is_running(self) -> bool:
        with self.session_factory() as session:
            state = session.get(WorkerState, 1)
            if state is None or state.pid == os.getpid():
                return False
            if not job_queue.worker_alive(session, self.clock()):
                return False
            pid = state.pid
        try:
            os.kill(pid, 0)  # Signal 0 checks that the process exists without touching it.
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    # --- Main loop -----------------------------------------------------------------------

    def run_forever(self, poll_seconds: float) -> None:
        self.beat(starting=True)
        # No other worker is alive, so every job still marked running lost its worker.
        self.recover(stale_after_seconds=0)
        self.clean_up_files()

        heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat.start()
        last_maintenance = time.monotonic()
        try:
            while not self.stop_event.is_set():
                if time.monotonic() - last_maintenance >= MAINTENANCE_SECONDS:
                    self.recover(stale_after_seconds=job_queue.STALE_JOB_SECONDS)
                    self.clean_up_files()
                    last_maintenance = time.monotonic()
                if not self.process_next_job():
                    self.stop_event.wait(poll_seconds)
        finally:
            self.stop_event.set()
            heartbeat.join(timeout=HEARTBEAT_SECONDS + 1)

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(HEARTBEAT_SECONDS):
            try:
                self.beat()
            except Exception:
                logger.debug("heartbeat failed", exc_info=True)


def main() -> int:
    # Before anything imports huggingface_hub: the worker must never go online.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Library loggers can print details of the audio; keep them to warnings.
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)

    from app.db import SessionLocal
    from app.pipeline.transcribe import WhisperTranscriber
    from app.speech_model import local_model_path

    # Looking on disk is cheap but not free, and this is asked on every heartbeat.
    model_check = {"at": float("-inf"), "ready": False}

    def speech_model_ready() -> bool:
        if time.monotonic() - model_check["at"] > 30:
            model_check.update(at=time.monotonic(), ready=local_model_path() is not None)
        return model_check["ready"]

    transcriber = WhisperTranscriber(settings.whisper_model, settings.whisper_compute_type)
    worker = Worker(
        SessionLocal,
        PipelineDeps(transcriber=transcriber),
        max_audio_seconds=settings.max_audio_seconds,
        max_attempts=settings.max_job_attempts,
        failed_audio_retention_hours=settings.failed_audio_retention_hours,
        speech_model_ready=speech_model_ready,
    )
    if worker.another_worker_is_running():
        logger.error("Another worker is already running. Only one worker should run at a time.")
        return 1

    def request_stop(signum, frame) -> None:
        if worker.stop_event.is_set():
            raise KeyboardInterrupt
        logger.info("Stopping after the current step. Press Ctrl+C again to stop immediately.")
        worker.stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    if worker.speech_model_ready():
        logger.info("Worker ready. Speech model: %s.", settings.whisper_model)
    else:
        logger.warning(
            "Speech model '%s' is not downloaded. Jobs will fail until you run: "
            "uv run python -m app.speech_model download",
            settings.whisper_model,
        )
    try:
        worker.run_forever(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        logger.info("Stopped immediately. Any unfinished job is recovered at the next start.")
        return 130
    logger.info("Worker stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
