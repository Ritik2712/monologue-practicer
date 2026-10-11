from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import job_queue, schemas
from app.dependencies import NowDep, SessionDep
from app.models import WorkerState

router = APIRouter(prefix="/api", tags=["health"])

BROKEN = schemas.Health(
    status="degraded",
    database="error",
    worker="not_running",
    speech_model="unknown",
    coach="unknown",
)


@router.get("/health", response_model=schemas.Health)
def health(session: SessionDep, now: NowDep) -> schemas.Health:
    """Whether the API can reach its database, and what the worker last reported.

    `status` covers the API and database only. Recordings also need the worker to be
    running and the speech model to be downloaded, which are reported separately. `coach`
    says whether the local language model could write coaching; without it, analysis still
    works and the coaching comes from fixed templates.
    """
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return BROKEN

    worker = "not_running"
    speech_model = "unknown"
    coach, coach_model = "unknown", None
    try:
        state = session.get(WorkerState, 1)
        if state is not None:
            speech_model = "ready" if state.speech_model_ready else "missing"
            coach, coach_model = state.coach_status or "unknown", state.coach_model
            if job_queue.worker_alive(session, now):
                worker = "running"
    except SQLAlchemyError:
        # The tables do not exist yet, or are out of date: migrations have not been run.
        return BROKEN
    return schemas.Health(
        status="ok",
        database="ok",
        worker=worker,
        speech_model=speech_model,
        coach=coach,
        coach_model=coach_model,
    )
