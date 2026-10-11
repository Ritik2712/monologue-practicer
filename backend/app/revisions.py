"""Later results made from a recording that already has one.

A stored result is never changed. When the user corrects the transcript, or the recording
is analysed again with new settings, the outcome is stored as a new revision next to the
earlier one, and both stay readable.
"""

from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app import feedback, job_queue, schemas, uploads
from app.calibration import store as calibration
from app.coaching.coach import Coach
from app.models import Analysis
from app.transcript_correction import correct_transcript


class RevisionError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def revision_infos(session: Session, analysis: Analysis) -> list[schemas.RevisionInfo]:
    """Every result made from the same recording as this one, oldest first."""
    family = job_queue.recording_family(session, job_queue.recording_root(analysis))
    return [
        schemas.RevisionInfo(
            analysis_id=member.id,
            revision=member.revision,
            reason=member.revision_reason,
            created_at=member.created_at,
            calibration_version=member.calibration_version,
        )
        for member in family
    ]


def create_corrected(
    session: Session,
    analysis: Analysis,
    corrections: list[schemas.SegmentCorrection],
    now: datetime,
    data_dir: Path | None = None,
) -> Analysis:
    """Stores a new revision of a recording whose transcript the user has corrected.

    Word counts and WPM are worked out again from the corrected words. For a take, the
    coaching is written from the fixed rules straight away; the user can then ask the AI
    model for it. A reference recording has no coaching, before or after.
    """
    body = schemas.AnalysisBody.model_validate(analysis.result)
    by_id = {segment.id: segment for segment in body.segments}
    wanted = {correction.segment_id: correction.text for correction in corrections}
    if any(segment_id not in by_id for segment_id in wanted):
        raise RevisionError(404, "unknown_target", "This recording has no such phrase.")

    corrected, changed = correct_transcript(body, wanted)
    if not changed:
        raise RevisionError(
            400, "nothing_changed", "The words are the same as before, so nothing was changed."
        )

    analysis_id = job_queue.new_id()
    root_id = job_queue.recording_root(analysis)
    revision = job_queue.next_revision(session, root_id)
    kept_path = None
    if uploads.audio_exists(analysis.audio_path, data_dir):
        kept_path = uploads.duplicate_audio(
            analysis.audio_path, uploads.RETAINED_DIR, analysis_id, data_dir, link=True
        )

    coaching = None
    if analysis.role != job_queue.REFERENCE:
        coaching = Coach(None).generate(
            corrected,
            now=now,
            settings=calibration.active(session).coaching_settings(),
            labels=feedback.pause_labels(session, analysis.id),
            use_model=False,
        )
    result = schemas.AnalysisResult(
        **corrected.model_dump(),
        analysis_id=analysis_id,
        job_id=analysis.job_id,
        created_at=now,
        role=analysis.role,
        title=analysis.title,
        revision=revision,
        revision_reason="transcript_corrected",
        audio_retained=kept_path is not None,
    )
    row = Analysis(
        id=analysis_id,
        job_id=analysis.job_id,
        created_at=now,
        role=analysis.role,
        title=analysis.title,
        profile=analysis.profile,
        language=analysis.language,
        duration_seconds=analysis.duration_seconds,
        schema_version=analysis.schema_version,
        settings_version=analysis.settings_version,
        # The phrases and pauses are the ones the earlier settings cut; that has not changed.
        calibration_version=analysis.calibration_version,
        root_id=root_id,
        revision=revision,
        revision_reason="transcript_corrected",
        result=result.model_dump(mode="json", by_alias=True, exclude={"coaching", "revisions"}),
        coaching=coaching.model_dump(mode="json", by_alias=True) if coaching else None,
        waveform=analysis.waveform,
        audio_path=kept_path,
    )
    session.add(row)
    session.flush()
    # The pauses are the very same ones, so what the user said about them still holds.
    feedback.copy_pause_labels(session, analysis.id, row, now)
    new_counts = {segment.id: segment.word_count or 0 for segment in corrected.segments}
    for segment_id in changed:
        feedback.record_correction(
            session, analysis, by_id[segment_id], new_counts[segment_id], revision, now
        )
    session.commit()
    return row


def language_hint(result: dict) -> str:
    """The language the user chose when the recording was first analysed, or "auto"."""
    language = result.get("language", {})
    code = language.get("code")
    return (
        code
        if language.get("source") == "declared" and code in ("en", "hi", "hinglish")
        else "auto"
    )


def create_reanalysis_job(
    session: Session, analysis: Analysis, now: datetime, data_dir: Path | None = None
) -> tuple[job_queue.Job, bool]:
    """Queues a fresh analysis of a kept recording, with the settings in force now.

    Returns the job and whether it is new: if one is already waiting or running for this
    result, that one is returned instead.
    """
    active = job_queue.active_reanalysis(session, analysis.id)
    if active is not None:
        return active, False
    if not uploads.audio_exists(analysis.audio_path, data_dir):
        raise RevisionError(
            409,
            "audio_not_kept",
            "Analysing again needs the recording, and it was not kept for this result.",
        )
    job_id = job_queue.new_id()
    # A copy of its own, so nothing the job does to its upload can touch the kept recording.
    audio_path = uploads.duplicate_audio(
        analysis.audio_path, uploads.UPLOADS_DIR, job_id, data_dir, link=False
    )
    original = session.get(job_queue.Job, analysis.job_id)
    try:
        job = job_queue.create_job(
            session,
            job_id=job_id,
            profile=analysis.profile,
            language_hint=language_hint(analysis.result),
            # The new revision can be played, and analysed again, like the one it came from.
            retain_audio=True,
            original_filename=original.original_filename if original else None,
            audio_path=audio_path,
            idempotency_key=None,
            now=now,
            role=analysis.role,
            title=analysis.title,
            source_analysis_id=analysis.id,
        )
    except Exception:
        uploads.delete_audio(audio_path, data_dir)
        raise
    return job, True
