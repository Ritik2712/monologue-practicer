from fastapi import APIRouter, HTTPException

from app import job_queue, schemas
from app.dependencies import DataDirDep, NowDep, SessionDep
from app.models import Job

router = APIRouter(prefix="/api", tags=["jobs"])

NOT_FOUND = HTTPException(
    404, detail={"code": "job_not_found", "message": "No analysis job with this ID exists."}
)


@router.get("/jobs/{job_id}", response_model=schemas.JobStatus)
def get_job(
    job_id: str, session: SessionDep, data_dir: DataDirDep, now: NowDep
) -> schemas.JobStatus:
    """Where a job has got to. Cheap enough to poll every second or two."""
    job = session.get(Job, job_id)
    if job is None:
        raise NOT_FOUND
    return job_queue.to_status(session, job, now, data_dir)


@router.post("/jobs/{job_id}/cancel", response_model=schemas.JobStatus)
def cancel_job(
    job_id: str, session: SessionDep, data_dir: DataDirDep, now: NowDep
) -> schemas.JobStatus:
    """Asks for a job to stop.

    A queued job is cancelled immediately. A running job is only marked `cancelRequested`:
    it stays "running" until the worker reaches a safe point and really stops. On a failed
    job this discards the audio that was being kept for a retry.
    """
    try:
        job = job_queue.request_cancel(session, job_id, now, data_dir)
    except LookupError:
        raise NOT_FOUND from None
    except job_queue.JobConflict as conflict:
        raise HTTPException(
            409, detail={"code": conflict.code, "message": conflict.message}
        ) from None
    return job_queue.to_status(session, job, now, data_dir)


@router.post("/jobs/{job_id}/retry", response_model=schemas.JobStatus)
def retry_job(
    job_id: str, session: SessionDep, data_dir: DataDirDep, now: NowDep
) -> schemas.JobStatus:
    """Puts a failed job back in the queue, if its failure was the kind a retry can fix."""
    try:
        job = job_queue.retry_job(session, job_id, now, data_dir)
    except LookupError:
        raise NOT_FOUND from None
    except job_queue.JobConflict as conflict:
        raise HTTPException(
            409, detail={"code": conflict.code, "message": conflict.message}
        ) from None
    return job_queue.to_status(session, job, now, data_dir)
