"""The job queue: every change to a job's status goes through a function in this file.

There is no separate queue server. The queue is the `jobs` table: a job waiting to be
processed is simply a row whose status is "queued".

    queued ──▶ running ──▶ succeeded
       │          ├──────▶ failed      (retry puts it back to queued)
       └──────────┴──────▶ cancelled

There are three kinds of job. An "analysis" job measures an uploaded recording. A "coaching"
job has no audio: it only writes the coaching of an analysis that already exists again. A
"summary" job has neither audio nor an analysis: it asks the AI model to pick the most
telling of the notes written with the feedback.

An analysis job can also be a fresh analysis of a recording that was kept earlier. Its
result is stored as a new revision of that recording, next to the earlier result.

Status changes are written as "UPDATE ... WHERE status = <expected>", so if two things
happen at once (the user cancels just as the worker picks the job up) only one of them wins
and the other can tell that it lost.
"""

import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas, uploads
from app.models import Analysis, Job, StoredSummary, WorkerState

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

ANALYSIS = "analysis"
COACHING = "coaching"
SUMMARY = "summary"

TAKE = "take"
REFERENCE = "reference"

# The worker reports in every few seconds. Silent for this long means it is not running.
WORKER_ALIVE_SECONDS = 15
# A running job whose heartbeat is older than this has lost its worker.
STALE_JOB_SECONDS = 30


class DuplicateJob(Exception):
    """A job with the same idempotency key already exists."""

    def __init__(self, existing: Job) -> None:
        super().__init__("duplicate job")
        self.existing = existing


class JobConflict(Exception):
    """The requested change does not make sense for the job's current status."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def new_id() -> str:
    return uuid.uuid4().hex


# --- Creating ----------------------------------------------------------------------------


def find_by_idempotency_key(session: Session, key: str | None) -> Job | None:
    if not key:
        return None
    return session.execute(select(Job).where(Job.idempotency_key == key)).scalar_one_or_none()


def create_job(
    session: Session,
    *,
    job_id: str,
    profile: str,
    language_hint: str,
    retain_audio: bool,
    original_filename: str | None,
    audio_path: str,
    idempotency_key: str | None,
    now: datetime,
    role: str = TAKE,
    title: str | None = None,
    source_analysis_id: str | None = None,
) -> Job:
    job = Job(
        id=job_id,
        status=QUEUED,
        role=role,
        title=title,
        source_analysis_id=source_analysis_id,
        profile=profile,
        language_hint=language_hint,
        retain_audio=retain_audio,
        original_filename=original_filename,
        audio_path=audio_path,
        idempotency_key=idempotency_key or None,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        # Two identical submissions arrived together and the other one was saved first.
        session.rollback()
        existing = find_by_idempotency_key(session, idempotency_key)
        if existing is None:
            raise
        raise DuplicateJob(existing) from None
    return job


def create_coaching_job(session: Session, analysis: Analysis, now: datetime) -> tuple[Job, bool]:
    """Queues a job that writes the coaching of a stored analysis again.

    Returns the job and whether it is new. If one is already waiting or running for this
    analysis, that one is returned instead, so the language model is never asked twice.
    """
    active = session.execute(
        select(Job).where(
            Job.kind == COACHING,
            Job.analysis_id == analysis.id,
            Job.status.in_((QUEUED, RUNNING)),
        )
    ).scalar_one_or_none()
    if active is not None:
        return active, False
    job = Job(
        id=new_id(),
        kind=COACHING,
        status=QUEUED,
        role=analysis.role,
        profile=analysis.profile,
        language_hint="auto",
        retain_audio=False,
        analysis_id=analysis.id,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    return job, True


def create_summary_job(session: Session, now: datetime) -> tuple[Job, bool]:
    """Queues a job that asks the AI model to pick the most telling of the user's notes.

    Returns the job and whether it is new: if one is already waiting or running, that one
    is returned instead.
    """
    active = session.execute(
        select(Job).where(Job.kind == SUMMARY, Job.status.in_((QUEUED, RUNNING)))
    ).scalar_one_or_none()
    if active is not None:
        return active, False
    job = Job(
        id=new_id(),
        kind=SUMMARY,
        status=QUEUED,
        # A job row always says these; a summary belongs to no recording, so they mean nothing.
        role=TAKE,
        profile="custom",
        language_hint="auto",
        retain_audio=False,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    return job, True


def active_reanalysis(session: Session, analysis_id: str) -> Job | None:
    """A job that is already waiting or running to analyse this analysis's recording again."""
    return session.execute(
        select(Job).where(
            Job.kind == ANALYSIS,
            Job.source_analysis_id == analysis_id,
            Job.status.in_((QUEUED, RUNNING)),
        )
    ).scalar_one_or_none()


def recording_root(analysis: Analysis) -> str:
    """The ID shared by every result made from the same recording."""
    return analysis.root_id or analysis.id


def recording_family(session: Session, root_id: str) -> list[Analysis]:
    """Every result made from one recording, oldest revision first."""
    return list(
        session.execute(
            select(Analysis)
            .where((Analysis.root_id == root_id) | (Analysis.id == root_id))
            .order_by(Analysis.revision, Analysis.created_at, Analysis.id)
        ).scalars()
    )


def next_revision(session: Session, root_id: str) -> int:
    family = recording_family(session, root_id)
    # 2 at least: if the first result has since been deleted, this is still a later one.
    return max((analysis.revision for analysis in family), default=1) + 1


# --- Worker side -------------------------------------------------------------------------


def claim_next_job(session: Session, now: datetime) -> Job | None:
    """Takes the oldest queued job and marks it running. None if the queue is empty."""
    job_id = session.execute(
        select(Job.id).where(Job.status == QUEUED).order_by(Job.created_at, Job.id).limit(1)
    ).scalar_one_or_none()
    if job_id is None:
        return None
    claimed = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == QUEUED)
        .values(
            status=RUNNING,
            stage=None,
            attempt=Job.attempt + 1,
            started_at=now,
            finished_at=None,
            heartbeat_at=now,
            updated_at=now,
            error_code=None,
            error_message=None,
            error_retryable=False,
        )
    )
    session.commit()
    if claimed.rowcount != 1:
        return None
    return session.get(Job, job_id)


def set_stage(session: Session, job_id: str, stage: str, now: datetime) -> None:
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == RUNNING)
        .values(stage=stage, heartbeat_at=now, updated_at=now)
    )
    session.commit()


def touch_job(session: Session, job_id: str, now: datetime) -> None:
    """Heartbeat: proves a worker is still on this job."""
    session.execute(
        update(Job).where(Job.id == job_id, Job.status == RUNNING).values(heartbeat_at=now)
    )
    session.commit()


def is_cancel_requested(session: Session, job_id: str) -> bool:
    return bool(
        session.execute(select(Job.cancel_requested).where(Job.id == job_id)).scalar_one_or_none()
    )


def complete_job(
    session: Session,
    job: Job,
    body: schemas.AnalysisBody,
    settings_version: int,
    now: datetime,
    data_dir: Path | None = None,
    *,
    coaching: schemas.Coaching | None = None,
    waveform: schemas.Waveform | None = None,
) -> Analysis | None:
    """Stores the result and marks the job succeeded.

    Returns None, leaving the job untouched, if cancellation was requested at the last
    moment; the caller then finishes the job as cancelled.
    """
    analysis_id = new_id()
    # Read now: the UPDATE below clears the column, and with it this attribute.
    upload_path = job.audio_path
    kept_path = None
    if job.retain_audio and upload_path:
        kept_path = uploads.retain_audio(upload_path, analysis_id, data_dir)

    # A fresh analysis of a kept recording joins that recording's family as a new revision.
    root_id, revision, reason = analysis_id, 1, None
    if job.source_analysis_id:
        source = session.get(Analysis, job.source_analysis_id)
        root_id = recording_root(source) if source else job.source_analysis_id
        revision, reason = next_revision(session, root_id), "reanalysed"

    result = schemas.AnalysisResult(
        **body.model_dump(),
        analysis_id=analysis_id,
        job_id=job.id,
        created_at=now,
        role=job.role,
        title=job.title,
        revision=revision,
        revision_reason=reason,
        audio_retained=kept_path is not None,
    )
    analysis = Analysis(
        id=analysis_id,
        job_id=job.id,
        created_at=now,
        role=job.role,
        title=job.title,
        profile=result.profile,
        language=result.language.code[:16],
        duration_seconds=result.duration_seconds,
        schema_version=result.schema_version,
        settings_version=settings_version,
        calibration_version=int(body.settings.get("calibration_version", 1)),
        root_id=root_id,
        revision=revision,
        revision_reason=reason,
        # The coaching lives in its own column so it can be rewritten without the result,
        # and the family of revisions is looked up afresh whenever the result is read.
        result=result.model_dump(mode="json", by_alias=True, exclude={"coaching", "revisions"}),
        coaching=coaching.model_dump(mode="json", by_alias=True) if coaching else None,
        # Stored on its own as well: a picture for the screen, read by no measurement.
        waveform=waveform.model_dump(mode="json", by_alias=True) if waveform else None,
        audio_path=kept_path,
    )
    session.add(analysis)
    session.flush()
    finished = session.execute(
        update(Job)
        .where(Job.id == job.id, Job.status == RUNNING, Job.cancel_requested.is_(False))
        .values(
            status=SUCCEEDED,
            stage=None,
            analysis_id=analysis_id,
            audio_path=None,
            finished_at=now,
            updated_at=now,
        )
    )
    if finished.rowcount != 1:
        session.rollback()
        if kept_path:
            uploads.delete_audio(kept_path, data_dir)
        return None
    session.commit()
    if not kept_path:
        uploads.delete_audio(upload_path, data_dir)
    return analysis


def complete_coaching_job(
    session: Session, job_id: str, coaching: schemas.Coaching, now: datetime
) -> bool:
    """Replaces an analysis's coaching and marks the coaching job succeeded.

    Returns False, changing nothing, if the job was cancelled at the last moment or the
    analysis has been deleted. The measurements are never touched.
    """
    job = session.get(Job, job_id)
    analysis = session.get(Analysis, job.analysis_id) if job and job.analysis_id else None
    if analysis is None:
        return False
    analysis.coaching = coaching.model_dump(mode="json", by_alias=True)
    finished = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == RUNNING, Job.cancel_requested.is_(False))
        .values(status=SUCCEEDED, stage=None, finished_at=now, updated_at=now)
    )
    if finished.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True


def complete_summary_job(
    session: Session, job_id: str, summary: StoredSummary, now: datetime
) -> bool:
    """Stores the pick in place of the one before, and marks the job succeeded.

    Returns False, changing nothing, if the job was cancelled at the last moment.
    """
    session.merge(summary)
    finished = session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == RUNNING, Job.cancel_requested.is_(False))
        .values(status=SUCCEEDED, stage=None, finished_at=now, updated_at=now)
    )
    if finished.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True


def fail_job(
    session: Session,
    job_id: str,
    *,
    code: str,
    message: str,
    retryable: bool,
    now: datetime,
    data_dir: Path | None = None,
) -> None:
    """Marks a running job failed. The audio is kept only if a retry could succeed."""
    job = session.get(Job, job_id)
    if job is None or job.status != RUNNING:
        return
    keep_audio = retryable and uploads.audio_exists(job.audio_path, data_dir)
    if not keep_audio:
        uploads.delete_audio(job.audio_path, data_dir)
        job.audio_path = None
    job.status = FAILED
    job.stage = None
    job.cancel_requested = False
    job.error_code = code
    job.error_message = message
    job.error_retryable = keep_audio
    job.finished_at = now
    job.updated_at = now
    session.commit()


def finish_cancelled(
    session: Session, job_id: str, now: datetime, data_dir: Path | None = None
) -> None:
    """Called by the worker once it has really stopped working on the job."""
    job = session.get(Job, job_id)
    if job is None or job.status != RUNNING:
        return
    uploads.delete_audio(job.audio_path, data_dir)
    job.audio_path = None
    job.status = CANCELLED
    job.stage = None
    job.cancel_requested = False
    job.finished_at = now
    job.updated_at = now
    session.commit()


def release_job(session: Session, job_id: str, now: datetime) -> None:
    """Puts a running job back in the queue because the worker is shutting down."""
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == RUNNING)
        .values(
            status=QUEUED,
            stage=None,
            # Being interrupted is not the job's fault, so it does not use up an attempt.
            attempt=Job.attempt - 1,
            started_at=None,
            heartbeat_at=None,
            updated_at=now,
        )
    )
    session.commit()


# --- User actions ------------------------------------------------------------------------


def request_cancel(
    session: Session, job_id: str, now: datetime, data_dir: Path | None = None
) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)

    if job.status == QUEUED:
        cancelled = session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == QUEUED)
            .values(status=CANCELLED, finished_at=now, updated_at=now)
        )
        session.commit()
        session.refresh(job)
        if cancelled.rowcount == 1:
            # Nothing had started, so the job is cancelled here and now.
            uploads.delete_audio(job.audio_path, data_dir)
            job.audio_path = None
            session.commit()
            return job
        # The worker picked it up in the same instant: fall through and treat it as running.

    if job.status == RUNNING:
        # Only a request. The worker stops at its next safe point and then sets "cancelled";
        # until that happens the job is honestly still reported as running.
        session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == RUNNING)
            .values(cancel_requested=True, updated_at=now)
        )
        session.commit()
        session.refresh(job)
        return job

    if job.status == FAILED:
        # "I no longer want this": drop the audio that was being kept for a retry.
        uploads.delete_audio(job.audio_path, data_dir)
        job.audio_path = None
        job.error_retryable = False
        job.updated_at = now
        session.commit()
        return job

    if job.status == CANCELLED:
        return job
    raise JobConflict("already_finished", "This analysis has already finished.")


def retry_job(session: Session, job_id: str, now: datetime, data_dir: Path | None = None) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise LookupError(job_id)
    if job.status != FAILED:
        raise JobConflict("not_failed", "Only a failed analysis can be retried.")
    if not job.error_retryable:
        raise JobConflict(
            "not_retryable",
            "Retrying would fail in the same way. Please record or upload the audio again.",
        )
    if not uploads.audio_exists(job.audio_path, data_dir):
        job.audio_path = None
        job.error_retryable = False
        session.commit()
        raise JobConflict(
            "audio_gone",
            "The audio for this analysis is no longer stored. Please record or upload it again.",
        )
    session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == FAILED)
        .values(
            status=QUEUED,
            stage=None,
            attempt=0,
            cancel_requested=False,
            error_code=None,
            error_message=None,
            error_retryable=False,
            started_at=None,
            finished_at=None,
            heartbeat_at=None,
            updated_at=now,
        )
    )
    session.commit()
    session.refresh(job)
    return job


# --- Housekeeping ------------------------------------------------------------------------


def recover_orphaned_jobs(
    session: Session,
    now: datetime,
    *,
    stale_after_seconds: float,
    max_attempts: int,
    data_dir: Path | None = None,
) -> tuple[int, int]:
    """Deals with jobs left "running" by a worker that died. Returns (requeued, ended)."""
    cutoff = now - timedelta(seconds=stale_after_seconds)
    orphans = session.execute(
        select(Job).where(
            Job.status == RUNNING, (Job.heartbeat_at.is_(None)) | (Job.heartbeat_at <= cutoff)
        )
    ).scalars()

    requeued = ended = 0
    for job in orphans:
        has_audio = uploads.audio_exists(job.audio_path, data_dir)
        # What the job needs in order to run again: its audio, or the analysis to coach.
        # A summary needs nothing but the stored feedback.
        can_run = (
            True
            if job.kind == SUMMARY
            else job.analysis_id is not None
            if job.kind == COACHING
            else has_audio
        )
        job.stage = None
        job.heartbeat_at = None
        job.updated_at = now
        if job.cancel_requested:
            uploads.delete_audio(job.audio_path, data_dir)
            job.audio_path = None
            job.status = CANCELLED
            job.cancel_requested = False
            job.finished_at = now
            ended += 1
        elif can_run and job.attempt < max_attempts:
            job.status = QUEUED
            job.started_at = None
            requeued += 1
        else:
            if not has_audio:
                job.audio_path = None
            job.status = FAILED
            job.error_code = "worker_stopped"
            job.error_message = {
                COACHING: "The worker stopped while writing the coaching.",
                SUMMARY: "The worker stopped while writing the summary.",
            }.get(job.kind, "The worker stopped while analysing this recording.")
            job.error_retryable = has_audio
            job.finished_at = now
            ended += 1
    session.commit()
    return requeued, ended


def expire_failed_audio(
    session: Session, now: datetime, retention_hours: float, data_dir: Path | None = None
) -> int:
    """Deletes audio that was kept for a retry nobody asked for in time."""
    cutoff = now - timedelta(hours=retention_hours)
    expired = session.execute(
        select(Job).where(
            Job.status == FAILED, Job.audio_path.is_not(None), Job.finished_at <= cutoff
        )
    ).scalars()
    count = 0
    for job in expired:
        uploads.delete_audio(job.audio_path, data_dir)
        job.audio_path = None
        job.error_retryable = False
        count += 1
    session.commit()
    return count


def referenced_upload_paths(session: Session) -> set[str]:
    return set(session.execute(select(Job.audio_path).where(Job.audio_path.is_not(None))).scalars())


# --- Worker liveness ---------------------------------------------------------------------


def report_worker(
    session: Session,
    *,
    pid: int,
    now: datetime,
    speech_model: str,
    speech_model_ready: bool,
    starting: bool = False,
    coach_model: str | None = None,
    coach_status: str | None = None,
) -> None:
    state = session.get(WorkerState, 1)
    if state is None:
        state = WorkerState(id=1, pid=pid, started_at=now, heartbeat_at=now, speech_model="", speech_model_ready=False)  # fmt: skip
        session.add(state)
    if starting or state.pid != pid:
        state.started_at = now
    state.pid = pid
    state.heartbeat_at = now
    state.speech_model = speech_model
    state.speech_model_ready = speech_model_ready
    state.coach_model = coach_model
    state.coach_status = coach_status
    session.commit()


def worker_alive(session: Session, now: datetime) -> bool:
    state = session.get(WorkerState, 1)
    return state is not None and (now - state.heartbeat_at).total_seconds() <= WORKER_ALIVE_SECONDS


# --- Reading -----------------------------------------------------------------------------


def queue_position(session: Session, job: Job) -> int:
    """How many queued jobs are ahead of this one."""
    return session.execute(
        select(func.count())
        .select_from(Job)
        .where(
            Job.status == QUEUED,
            (Job.created_at < job.created_at)
            | ((Job.created_at == job.created_at) & (Job.id < job.id)),
        )
    ).scalar_one()


def to_status(
    session: Session, job: Job, now: datetime, data_dir: Path | None = None
) -> schemas.JobStatus:
    error = None
    if job.status == FAILED:
        error = schemas.JobError(
            code=job.error_code or "unknown",
            message=job.error_message or "The analysis failed.",
            retryable=job.error_retryable,
        )
    return schemas.JobStatus(
        job_id=job.id,
        kind=job.kind,
        role=job.role,
        status=job.status,
        stage=job.stage if job.status == RUNNING else None,
        cancel_requested=job.cancel_requested and job.status == RUNNING,
        error=error,
        analysis_id=job.analysis_id,
        source_analysis_id=job.source_analysis_id,
        can_retry=(
            job.status == FAILED
            and job.error_retryable
            and uploads.audio_exists(job.audio_path, data_dir)
        ),
        can_cancel=job.status in (QUEUED, RUNNING) and not job.cancel_requested,
        queue_position=queue_position(session, job) if job.status == QUEUED else None,
        worker_alive=worker_alive(session, now),
        attempt=job.attempt,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )
