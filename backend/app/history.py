"""Listing and deleting stored analyses: the "history" the General Practice screen shows.

Deleting always removes the files that go with a row, so nothing is left behind on disk.
"""

from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import job_queue, schemas, uploads
from app.models import Analysis, Job

# The metrics shown in a history row and used to compare one attempt with another.
SUMMARY_METRICS = (
    "totalWordCount",
    "speechActiveWpm",
    "wholeClipWpm",
    "typicalSegmentWpm",
    "paceVariation",
    "pauseCount",
    "medianPauseSeconds",
    "longestPauseSeconds",
    "pauseRatio",
    "energyVariation",
    "pitchVariationSemitones",
)

FINISHED = (job_queue.SUCCEEDED, job_queue.FAILED, job_queue.CANCELLED)


def summarize(analysis: Analysis, original_filename: str | None) -> schemas.AnalysisSummary:
    stored_metrics = analysis.result.get("metrics", {})
    metrics = {
        name: schemas.MetricValue.model_validate(stored_metrics[name])
        for name in SUMMARY_METRICS
        # Results saved before a metric existed simply do not have it.
        if name in stored_metrics
    }
    return schemas.AnalysisSummary(
        analysis_id=analysis.id,
        job_id=analysis.job_id,
        created_at=analysis.created_at,
        role=analysis.role,
        title=analysis.title,
        profile=analysis.profile,
        language=analysis.language,
        duration_seconds=analysis.duration_seconds,
        revision=analysis.revision,
        revision_reason=analysis.revision_reason,
        audio_retained=analysis.audio_path is not None,
        original_filename=original_filename,
        metrics=metrics,
        warning_codes=[warning["code"] for warning in analysis.result.get("warnings", [])],
        settings=analysis.result.get("settings", {}),
    )


def list_analyses(
    session: Session, *, limit: int, offset: int, role: str = job_queue.TAKE
) -> schemas.AnalysisList:
    """Newest first. Takes and references are listed separately."""
    total = session.execute(
        select(func.count()).select_from(Analysis).where(Analysis.role == role)
    ).scalar_one()
    rows = session.execute(
        select(Analysis, Job.original_filename)
        .outerjoin(Job, Job.id == Analysis.job_id)
        .where(Analysis.role == role)
        .order_by(Analysis.created_at.desc(), Analysis.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return schemas.AnalysisList(
        items=[summarize(analysis, filename) for analysis, filename in rows], total=total
    )


def delete_analysis(session: Session, analysis_id: str, data_dir: Path | None = None) -> bool:
    """Removes the result, its kept recording and the job that produced it."""
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        return False
    uploads.delete_audio(analysis.audio_path, data_dir)
    session.execute(delete(Job).where(Job.analysis_id == analysis_id))
    session.delete(analysis)
    session.commit()
    return True


def delete_kept_audio(
    session: Session, analysis_id: str, data_dir: Path | None = None
) -> bool | None:
    """Removes only the recording and keeps the measurements.

    None if there is no such analysis; False if it had no kept recording.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        return None
    if analysis.audio_path is None:
        return False
    uploads.delete_audio(analysis.audio_path, data_dir)
    analysis.audio_path = None
    session.commit()
    return True


def clear_history(
    session: Session, data_dir: Path | None = None, *, role: str = job_queue.TAKE
) -> schemas.HistoryCleared:
    """Removes every stored result of one role, and its finished jobs, with all their audio.

    The history of takes and the library of references are cleared separately, so clearing
    one never empties the other. Jobs that are still queued or running are left alone,
    along with their uploads.
    """
    analyses = session.execute(select(Analysis).where(Analysis.role == role)).scalars().all()
    for analysis in analyses:
        uploads.delete_audio(analysis.audio_path, data_dir)
    finished = (Job.status.in_(FINISHED)) & (Job.role == role)
    finished_jobs = session.execute(select(Job).where(finished)).scalars().all()
    for job in finished_jobs:
        # A failed job may still be holding its upload for a retry.
        uploads.delete_audio(job.audio_path, data_dir)

    session.execute(delete(Job).where(finished))
    session.execute(delete(Analysis).where(Analysis.role == role))
    session.commit()
    return schemas.HistoryCleared(deleted_analyses=len(analyses), deleted_jobs=len(finished_jobs))
