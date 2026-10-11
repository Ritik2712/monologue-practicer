from fastapi import APIRouter, HTTPException, Response

from app import feedback, feedback_summary, job_queue, schemas
from app.calibration import store as calibration
from app.dependencies import DataDirDep, NowDep, SessionDep
from app.models import Analysis

router = APIRouter(prefix="/api", tags=["feedback and calibration"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _analysis(session, analysis_id: str) -> Analysis:
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    return analysis


def _update(session, analysis: Analysis | None, adjustments=()) -> schemas.FeedbackUpdate:
    return schemas.FeedbackUpdate(
        items=feedback.list_items(session, analysis) if analysis else [],
        adjustments=[calibration.to_change(row) for row in adjustments],
        calibration=calibration.describe(session),
    )


@router.get("/analyses/{analysis_id}/feedback", response_model=schemas.FeedbackUpdate)
def list_feedback(analysis_id: str, session: SessionDep) -> schemas.FeedbackUpdate:
    """The feedback given on one analysis, with what each piece does, and the calibration."""
    return _update(session, _analysis(session, analysis_id))


@router.post("/analyses/{analysis_id}/feedback", response_model=schemas.FeedbackUpdate)
def give_feedback(
    analysis_id: str, request: schemas.FeedbackRequest, session: SessionDep, now: NowDep
) -> schemas.FeedbackUpdate:
    """Saves one piece of feedback on an analysis: a take, or a reference recording.

    Feedback on the same thing replaces what was said about it before; sending the same
    category again only changes its note. No stored measurement is ever changed. If this
    feedback completes a run of reports that agree, a setting is adjusted here and now, and
    `adjustments` says which and why.

    On a reference recording, mistakes in the measurement can be reported, but its pauses
    cannot be labelled and there is no coaching to rate.
    """
    analysis = _analysis(session, analysis_id)
    try:
        feedback.save(session, analysis, request, now)
    except feedback.FeedbackError as error:
        raise _error(error.status, error.code, error.message) from None
    return _update(session, analysis, calibration.evaluate(session, now))


@router.delete("/feedback/{feedback_id}", response_model=schemas.FeedbackUpdate)
def delete_feedback(feedback_id: str, session: SessionDep, now: NowDep) -> schemas.FeedbackUpdate:
    """Takes one piece of feedback back.

    An adjustment it already counted towards is not reversed by this; that is what
    `POST /api/calibration/undo` is for.
    """
    analysis_id = feedback.delete(session, feedback_id)
    if analysis_id is None:
        raise _error(404, "feedback_not_found", "No feedback with this ID exists.")
    # Taking away a report that disagreed can leave the rest agreeing enough to act on.
    adjustments = calibration.evaluate(session, now)
    return _update(session, session.get(Analysis, analysis_id), adjustments)


@router.get("/calibration", response_model=schemas.Calibration)
def get_calibration(session: SessionDep) -> schemas.Calibration:
    """The settings in force: every value, its allowed range, what changed it and why."""
    return calibration.describe(session)


@router.post("/calibration/undo", response_model=schemas.Calibration)
def undo_adjustment(session: SessionDep, now: NowDep) -> schemas.Calibration:
    """Puts back the value that the most recent automatic adjustment replaced."""
    if calibration.undo_last(session, now) is None:
        raise _error(409, "nothing_to_undo", "There is no adjustment to undo.")
    return calibration.describe(session)


@router.post("/calibration/reset", response_model=schemas.Calibration)
def reset_calibration(session: SessionDep, now: NowDep) -> schemas.Calibration:
    """Returns every setting to its default and starts the report counts again.

    Stored feedback is kept, and so are all results. Results made earlier still say which
    version of the settings produced them.
    """
    if calibration.reset(session, now) is None:
        raise _error(409, "already_default", "Every setting is already at its default.")
    return calibration.describe(session)


@router.put("/calibration/adaptive", response_model=schemas.Calibration)
def set_adaptive(
    request: schemas.AdaptiveRequest, session: SessionDep, now: NowDep
) -> schemas.Calibration:
    """Switches automatic adjustment on or off.

    While it is off, feedback is still saved and labels still shape the coaching, but no
    setting moves. Switching it on again acts on any reports that have built up meanwhile.
    """
    calibration.set_adaptive(session, request.enabled, now)
    return calibration.describe(session)


@router.get("/feedback-summary", response_model=schemas.FeedbackSummary)
def get_feedback_summary(
    session: SessionDep, now: NowDep, data_dir: DataDirDep
) -> schemas.FeedbackSummary:
    """What all the stored feedback adds up to.

    `facts` are counted and written by code, here and now, so they are always current.
    `notes` are the notes you wrote with your feedback, word for word. `picked` is the few
    of them the local AI model last picked out as the most telling, if it was asked;
    `stale` says the notes have changed since. Nothing here changes a setting.
    """
    return feedback_summary.describe(session, now, data_dir)


@router.post(
    "/feedback-summary",
    response_model=schemas.FeedbackSummary,
    status_code=202,
    responses={
        200: {"model": schemas.FeedbackSummary, "description": "One is already in progress"}
    },
)
def request_feedback_summary(
    response: Response, session: SessionDep, now: NowDep, data_dir: DataDirDep
) -> schemas.FeedbackSummary:
    """Asks the local AI model to pick out the most telling of your notes.

    Returns at once; `job` says how it is going, and `GET /api/feedback-summary` can be
    polled until it is done. The model is given your notes as text and nothing else, and
    answers only with which notes it picks: nothing it writes is ever shown, and the
    counts are never worded by it.
    """
    if len(feedback_summary.build_digest(session).candidates) < feedback_summary.MIN_NOTES:
        raise _error(409, "too_few_notes", feedback_summary.TOO_FEW)
    _, created = job_queue.create_summary_job(session, now)
    if not created:
        response.status_code = 200
    return feedback_summary.describe(session, now, data_dir)
