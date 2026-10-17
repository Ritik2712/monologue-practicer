from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response

from app import export, monologues
from app.dependencies import NowDep, SessionDep
from app.models import Analysis

router = APIRouter(prefix="/api", tags=["export"])


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _download(filename: str, text: str) -> Response:
    """A Markdown document the browser saves as a file instead of showing it."""
    return Response(
        content=text,
        media_type=export.MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/analyses/{analysis_id}/export")
def export_analysis(analysis_id: str, session: SessionDep) -> Response:
    """One analysis as a Markdown document: everything the result holds, written out.

    For a take of a monologue that includes the comparison with the monologue's original.
    Nothing is measured again and nothing stored is changed.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    return _download(*export.export_analysis(session, analysis))


@router.get("/export")
def export_many(
    session: SessionDep,
    now: NowDep,
    scope: Annotated[Literal["all", "general", "monologue"], Query()] = "all",
    monologue: Annotated[str | None, Query(max_length=32)] = None,
) -> Response:
    """Several analyses in one Markdown document, each recording in its newest revision.

    `scope=all` gives every monologue with its takes and then the General Practice takes.
    `scope=general` gives only the takes that belong to no monologue. `scope=monologue`
    with `monologue=<id>` gives one monologue's original and the takes recorded for it.
    """
    if scope == "general":
        return _download(*export.export_general(session, now))
    if scope == "monologue":
        monologue_id = monologues.resolve(session, monologue) if monologue else None
        if monologue_id is None:
            raise _error(404, "monologue_not_found", "No monologue with this ID exists.")
        return _download(*export.export_monologue(session, monologue_id, now))
    return _download(*export.export_everything(session, now))
