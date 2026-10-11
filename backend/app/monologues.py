"""Monologues: a reference recording and the takes recorded for it, seen as one thing.

Nothing is stored under the name "monologue". Every revision of one reference recording
is one monologue, identified by that recording's root ID, and a take belongs to it through
its `monologue_id` column. This module is that view: resolving an ID, listing, deleting.
"""

from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import job_queue, schemas, uploads
from app.models import Analysis, Job


class MonologueBusy(Exception):
    """A recording of this monologue is still waiting or being analysed."""


def resolve(session: Session, analysis_id: str) -> str | None:
    """The monologue an ID names, or None if it names none.

    Accepts the monologue's own ID or the ID of any revision of its reference recording,
    so a caller can pass whichever it has.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is not None:
        if analysis.role != job_queue.REFERENCE:
            return None
        return job_queue.recording_root(analysis)
    # The first revision may have been deleted while later ones remain.
    return analysis_id if job_queue.monologue_exists(session, analysis_id) else None


def reference_revisions(session: Session, monologue_id: str) -> list[Analysis]:
    """Every revision of a monologue's reference recording, oldest first."""
    return [
        analysis
        for analysis in job_queue.recording_family(session, monologue_id)
        if analysis.role == job_queue.REFERENCE
    ]


def list_monologues(session: Session) -> schemas.MonologueList:
    """Every monologue, the one practised or added most recently first."""
    references = session.execute(
        select(Analysis)
        .where(Analysis.role == job_queue.REFERENCE)
        .order_by(Analysis.revision, Analysis.created_at, Analysis.id)
    ).scalars()
    families: dict[str, list[Analysis]] = {}
    for reference in references:
        families.setdefault(job_queue.recording_root(reference), []).append(reference)

    # A take whose transcript was corrected, or that was analysed again, is still one take.
    recording = func.coalesce(Analysis.root_id, Analysis.id)
    takes = {
        monologue_id: (count, latest)
        for monologue_id, count, latest in session.execute(
            select(
                Analysis.monologue_id,
                func.count(func.distinct(recording)),
                func.max(Analysis.created_at),
            )
            .where(Analysis.role == job_queue.TAKE, Analysis.monologue_id.is_not(None))
            .group_by(Analysis.monologue_id)
        )
    }

    items = []
    for monologue_id, revisions in families.items():
        newest = revisions[-1]
        take_count, last_take_at = takes.get(monologue_id, (0, None))
        items.append(
            schemas.Monologue(
                monologue_id=monologue_id,
                reference_id=newest.id,
                title=newest.title or "Monologue",
                created_at=revisions[0].created_at,
                language=newest.language,
                duration_seconds=newest.duration_seconds,
                audio_retained=newest.audio_path is not None,
                revision=newest.revision,
                revision_count=len(revisions),
                take_count=take_count,
                last_take_at=last_take_at,
                settings=newest.result.get("settings", {}),
            )
        )
    items.sort(key=lambda item: item.last_take_at or item.created_at, reverse=True)
    return schemas.MonologueList(items=items)


def delete_monologue(
    session: Session, monologue_id: str, data_dir: Path | None = None
) -> schemas.MonologueDeleted | None:
    """Removes a monologue: every revision of its reference, and every take recorded for it.

    Their kept recordings, their jobs and the feedback given on them go too. Returns None
    if there is no such monologue. Raises MonologueBusy while one of its recordings is
    still waiting or being worked on, so that nothing is left half made.
    """
    references = reference_revisions(session, monologue_id)
    if not references:
        return None
    takes = list(
        session.execute(
            select(Analysis).where(
                Analysis.role == job_queue.TAKE, Analysis.monologue_id == monologue_id
            )
        ).scalars()
    )
    analysis_ids = [analysis.id for analysis in (*references, *takes)]
    belongs = (
        (Job.monologue_id == monologue_id)
        | Job.analysis_id.in_(analysis_ids)
        | Job.source_analysis_id.in_(analysis_ids)
    )
    in_progress = session.execute(
        select(Job.id)
        .where(Job.status.in_((job_queue.QUEUED, job_queue.RUNNING)), belongs)
        .limit(1)
    ).first()
    if in_progress is not None:
        raise MonologueBusy

    for analysis in (*references, *takes):
        uploads.delete_audio(analysis.audio_path, data_dir)
    for job in session.execute(select(Job).where(belongs)).scalars():
        # A failed job may still be holding its upload for a retry.
        uploads.delete_audio(job.audio_path, data_dir)
    session.execute(delete(Job).where(belongs))
    session.execute(delete(Analysis).where(Analysis.id.in_(analysis_ids)))
    session.commit()
    # A corrected or re-analysed take is one take, however many results it has.
    recordings = {job_queue.recording_root(take) for take in takes}
    return schemas.MonologueDeleted(
        deleted_references=len(references), deleted_takes=len(recordings)
    )
