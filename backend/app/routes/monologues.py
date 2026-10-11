from fastapi import APIRouter, HTTPException

from app import monologues, schemas
from app.dependencies import DataDirDep, SessionDep

router = APIRouter(prefix="/api", tags=["monologues"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


@router.get("/monologues", response_model=schemas.MonologueList)
def list_monologues(session: SessionDep) -> schemas.MonologueList:
    """The monologues being practised, the one practised or added most recently first.

    A monologue is a reference recording, in its newest revision, together with a count of
    the takes recorded for it. Add one by submitting a recording with `role=reference`.
    """
    return monologues.list_monologues(session)


@router.delete("/monologues/{monologue_id}", response_model=schemas.MonologueDeleted)
def delete_monologue(
    monologue_id: str, session: SessionDep, data_dir: DataDirDep
) -> schemas.MonologueDeleted:
    """Deletes a monologue: its reference recording in every revision, and all its takes."""
    resolved = monologues.resolve(session, monologue_id)
    try:
        deleted = monologues.delete_monologue(session, resolved, data_dir) if resolved else None
    except monologues.MonologueBusy:
        raise _error(
            409,
            "monologue_busy",
            "A recording of this monologue is still waiting or being analysed. Wait for it "
            "to finish, or cancel it, and then delete the monologue.",
        ) from None
    if deleted is None:
        raise _error(404, "monologue_not_found", "No monologue with this ID exists.")
    return deleted
