"""The worker: a separate program that takes jobs from the queue one at a time and runs
the audio pipeline and the coaching on them, so the API never has to wait for slow work.

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

from app import feedback, feedback_summary, job_queue, schemas, uploads
from app.calibration import store as calibration
from app.coaching.coach import Coach, CoachingUnavailable
from app.config import settings
from app.models import Analysis, Job, WorkerState, utcnow
from app.pipeline.errors import JobCancelled, PipelineError, WorkerStopping
from app.pipeline.runner import PipelineDeps, run_analysis
from app.pipeline.settings import DEFAULT_SETTINGS, AnalysisSettings
from app.pipeline.waveform import waveform_outline

logger = logging.getLogger("app.worker")

HEARTBEAT_SECONDS = 3
MAINTENANCE_SECONDS = 60
# An upload no job refers to is left alone this long, in case its job is just being created.
STRAY_UPLOAD_SECONDS = 3600
# How often the worker asks Ollama whether the language model is available.
COACH_CHECK_SECONDS = 15

STAGE_DESCRIPTIONS = {
    "preparing_audio": "reading the audio",
    "detecting_speech": "detecting speech",
    "transcribing": "transcribing",
    "measuring_audio": "measuring the audio",
    "generating_feedback": "writing the coaching",
    "summarising_feedback": "picking out notes",
}


COACH_HELP = {
    "not_running": "Start Ollama (open the Ollama app, or run: ollama serve).",
    "model_missing": "The model '{model}' is not installed. To install it: ollama pull {model}",
    "not_local": "OLLAMA_BASE_URL must point at this computer, e.g. http://localhost:11434.",
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
        coach: Coach | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.session_factory = session_factory
        self.deps = deps
        # With no language model given, coaching comes from fixed templates.
        self.coach = coach or Coach(None)
        self._coach_status: str | None = None
        self._coach_checked_at = float("-inf")
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
            kind, role, attempt = job.kind, job.role, job.attempt
            # Copied out now: the row is not read again until the job finishes.
            audio_path, analysis_id = job.audio_path, job.analysis_id
            profile, language = job.profile, job.language_hint
            voice_goal = job.voice_goal

        self.current_job_id = job_id
        started = time.monotonic()
        stage = "preparing_audio"
        logger.info("%s job %s started (attempt %d)", kind, short_id, attempt)

        def on_stage(name: str) -> None:
            nonlocal stage
            stage = name
            with self.session_factory() as session:
                job_queue.set_stage(session, job_id, name, self.clock())
            logger.info("job %s: %s", short_id, name)

        def check() -> None:
            # Called between steps: the only places a job can stop safely.
            with self.session_factory() as session:
                if job_queue.is_cancel_requested(session, job_id):
                    raise JobCancelled
            if self.stop_event.is_set():
                raise WorkerStopping

        try:
            if kind == job_queue.COACHING:
                saved = self._write_coaching_again(job_id, analysis_id, on_stage, check)
            elif kind == job_queue.SUMMARY:
                saved = self._sum_up_feedback(job_id, on_stage, check)
            else:
                saved = self._analyse(
                    job_id, audio_path, profile, language, role, voice_goal, on_stage, check
                )
            if not saved:
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
                kind == job_queue.ANALYSIS,
            )
            logger.error("job %s failed unexpectedly: %s", short_id, type(error).__name__)
            logger.debug("job %s traceback", short_id, exc_info=True)
        finally:
            self.current_job_id = None
        return True

    def _analyse(
        self,
        job_id: str,
        audio_path: str | None,
        profile: str,
        language: str,
        role: str,
        voice_goal: str,
        on_stage: Callable[[str], None],
        check: Callable[[], None],
    ) -> bool:
        """Measures the recording, writes its coaching and stores both. False if cancelled.

        A reference recording is measured in exactly the same way but gets no coaching:
        there is nothing to coach the original performer on.
        """
        if not audio_path or not uploads.audio_exists(audio_path, self.data_dir):
            raise PipelineError("audio_missing", "The uploaded audio is no longer available.")
        # The calibration in force when the job starts is the one the whole job uses, and
        # its version number is stored with the result.
        with self.session_factory() as session:
            active = calibration.active(session)
        analysis_settings = active.analysis_settings(self.analysis_settings)
        pictures: list[schemas.Waveform] = []
        body = run_analysis(
            uploads.absolute(audio_path, self.data_dir),
            profile=profile,
            language=language,
            voice_goal=voice_goal,
            settings=analysis_settings,
            max_seconds=self.max_audio_seconds,
            deps=self.deps,
            on_stage=on_stage,
            check=check,
            on_audio=lambda samples: pictures.append(waveform_outline(samples)),
        )
        check()
        coaching = None
        if role != job_queue.REFERENCE:
            on_stage("generating_feedback")
            coaching = self._coach_safely(
                body, check, active.coaching_settings(self.coach.settings)
            )
            check()
        with self.session_factory() as session:
            job = session.get(Job, job_id)
            saved = job_queue.complete_job(
                session,
                job,
                body,
                analysis_settings.version,
                self.clock(),
                self.data_dir,
                coaching=coaching,
                waveform=pictures[0] if pictures else None,
            )
        return saved is not None

    def _coach_safely(
        self, body: schemas.AnalysisBody, check: Callable[[], None], settings
    ) -> schemas.Coaching | None:
        """Coaching must never cost the user their measurements.

        If the coaching step breaks in a way nobody planned for, the result is saved
        without coaching, and the screen offers to write it again.
        """
        try:
            return self.coach.generate(body, now=self.clock(), check=check, settings=settings)
        except (JobCancelled, WorkerStopping):
            raise
        except Exception as error:
            logger.error("coaching failed unexpectedly: %s", type(error).__name__)
            logger.debug("coaching traceback", exc_info=True)
            return None

    def _write_coaching_again(
        self,
        job_id: str,
        analysis_id: str | None,
        on_stage: Callable[[str], None],
        check: Callable[[], None],
    ) -> bool:
        """Asks the language model for new coaching on a stored analysis. False if cancelled."""
        with self.session_factory() as session:
            analysis = session.get(Analysis, analysis_id) if analysis_id else None
            stored = analysis.result if analysis else None
            before = (analysis.coaching or {}) if analysis else {}
            labels = feedback.pause_labels(session, analysis_id) if analysis else {}
            settings = calibration.active(session).coaching_settings(self.coach.settings)
        if stored is None:
            raise PipelineError("analysis_gone", "The analysis this coaching was for was deleted.")
        body = schemas.AnalysisBody.model_validate(stored)
        # The user has labelled pauses since the coaching was written: coaching from the
        # templates that takes the labels in is then already an improvement.
        labels_changed = labels != (before.get("labelsUsed") or {})
        on_stage("generating_feedback")
        try:
            # Otherwise template coaching would be no improvement on what is stored, so
            # anything short of an answer from the model fails the job and changes nothing.
            coaching = self.coach.generate(
                body,
                now=self.clock(),
                check=check,
                require_model=not labels_changed,
                settings=settings,
                labels=labels,
            )
        except CoachingUnavailable as error:
            raise PipelineError(error.code, error.message) from None
        check()
        with self.session_factory() as session:
            return job_queue.complete_coaching_job(session, job_id, coaching, self.clock())

    def _sum_up_feedback(
        self, job_id: str, on_stage: Callable[[str], None], check: Callable[[], None]
    ) -> bool:
        """Asks the language model to pick the most telling notes. False if cancelled.

        Anything short of a usable answer fails the job and stores nothing: the notes
        themselves are on the screen either way. No setting is touched.
        """
        with self.session_factory() as session:
            digest = feedback_summary.build_digest(session)
        on_stage("summarising_feedback")
        try:
            picked = feedback_summary.pick(self.coach.llm, digest, check)
        except feedback_summary.SummaryUnavailable as error:
            raise PipelineError(error.code, error.message) from None
        check()
        with self.session_factory() as session:
            return job_queue.complete_summary_job(
                session,
                job_id,
                feedback_summary.to_row(digest, picked, self.clock()),
                self.clock(),
            )

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
                coach_model=self.coach.model_name,
                coach_status=self.coach_status(),
            )
            if self.current_job_id:
                job_queue.touch_job(session, self.current_job_id, now)

    def coach_status(self) -> str:
        """Whether the language model could answer, checked afresh every few seconds."""
        if time.monotonic() - self._coach_checked_at > COACH_CHECK_SECONDS:
            self._coach_status = self.coach.status()
            self._coach_checked_at = time.monotonic()
        return self._coach_status or "unknown"

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
    # Library loggers can print details of the audio or the requests; keep them to warnings.
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from app.db import SessionLocal
    from app.llm import OllamaChat
    from app.pipeline.transcribe import WhisperTranscriber
    from app.speech_model import local_model_path

    # Looking on disk is cheap but not free, and this is asked on every heartbeat.
    model_check = {"at": float("-inf"), "ready": False}

    def speech_model_ready() -> bool:
        if time.monotonic() - model_check["at"] > 30:
            model_check.update(at=time.monotonic(), ready=local_model_path() is not None)
        return model_check["ready"]

    transcriber = WhisperTranscriber(settings.whisper_model, settings.whisper_compute_type)
    language_model = (
        OllamaChat(
            settings.ollama_model,
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.ollama_timeout_seconds,
            context_tokens=settings.ollama_context_tokens,
        )
        if settings.ai_coaching
        else None
    )
    worker = Worker(
        SessionLocal,
        PipelineDeps(transcriber=transcriber),
        coach=Coach(language_model),
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
    coach_status = worker.coach_status()
    if coach_status == "ready":
        logger.info("AI coaching ready. Language model: %s.", settings.ollama_model)
    elif coach_status == "off":
        logger.info("AI coaching is switched off (AI_COACHING=off). Coaching uses fixed rules.")
    else:
        # Never fixed automatically: this app does not start Ollama or download models.
        logger.warning(
            "AI coaching is not available (%s). Analyses still work; coaching will use fixed "
            "rules. %s",
            coach_status,
            COACH_HELP.get(coach_status, "").format(model=settings.ollama_model),
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
