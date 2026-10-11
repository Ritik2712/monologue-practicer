from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from app import history, job_queue, profiles, schemas, uploads
from app.config import settings
from app.dependencies import DataDirDep, NowDep, SessionDep
from app.models import Analysis
from app.pipeline.audio import probe_audio
from app.pipeline.errors import PipelineError

router = APIRouter(prefix="/api", tags=["analyses"])


# Room for the form fields and multipart boundaries that travel with the file.
REQUEST_OVERHEAD_BYTES = 64 * 1024


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _too_large_message() -> str:
    return f"The file is larger than the {settings.max_upload_bytes / (1024 * 1024):g} MB limit."


def upload_is_too_large(content_length: str | None) -> str | None:
    """Judges an upload by its declared size, before any of it has been received.

    Returns the message to refuse it with, or None to let it through. The file is measured
    again as it is saved, so a missing or untrue header gains nothing.
    """
    try:
        declared = int(content_length or 0)
    except ValueError:
        return None
    if declared > settings.max_upload_bytes + REQUEST_OVERHEAD_BYTES:
        return _too_large_message()
    return None


@router.post(
    "/analyses",
    response_model=schemas.JobStatus,
    status_code=202,
    responses={200: {"model": schemas.JobStatus, "description": "Same Idempotency-Key as before"}},
)
def submit_analysis(
    response: Response,
    session: SessionDep,
    data_dir: DataDirDep,
    now: NowDep,
    audio: Annotated[UploadFile, File(description="The recording to analyse")],
    profile: Annotated[schemas.Profile, Form()] = "custom",
    language: Annotated[schemas.LanguageHint, Form()] = "auto",
    retain_audio: Annotated[bool, Form(alias="retainAudio")] = False,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> schemas.JobStatus:
    """Accepts a recording, queues it for analysis and returns at once with a job to poll.

    Nothing slow happens here. The file is checked, saved, and a job row is created; the
    worker does the rest. Sending the same `Idempotency-Key` header again returns the
    original job instead of creating a second one.
    """
    existing = job_queue.find_by_idempotency_key(session, idempotency_key)
    if existing is not None:
        response.status_code = 200
        return job_queue.to_status(session, existing, now, data_dir)

    extension = uploads.pick_extension(audio.filename, audio.content_type)
    if extension is None:
        raise _error(
            415,
            "unsupported_type",
            "This file type is not supported. Use WAV, MP3, M4A, OGG, FLAC or WebM audio.",
        )

    job_id = job_queue.new_id()
    try:
        audio_path, size = uploads.save_upload(
            audio.file, job_id, extension, settings.max_upload_bytes, data_dir
        )
    except uploads.UploadTooLarge:
        raise _error(413, "file_too_large", _too_large_message()) from None
    if size == 0:
        uploads.delete_audio(audio_path, data_dir)
        raise _error(400, "empty_file", "The file is empty. No audio was received.")

    # A quick look at the header, so a file that is plainly not audio is refused now
    # rather than failing a job a few seconds later.
    try:
        probe = probe_audio(uploads.absolute(audio_path, data_dir))
    except PipelineError as error:
        uploads.delete_audio(audio_path, data_dir)
        raise _error(415, error.code, error.message) from None
    if not probe.has_audio:
        uploads.delete_audio(audio_path, data_dir)
        raise _error(415, "no_audio_stream", "This file has no audio track.")
    if probe.duration_seconds is not None and probe.duration_seconds > settings.max_audio_seconds:
        uploads.delete_audio(audio_path, data_dir)
        raise _error(
            413,
            "audio_too_long",
            f"The recording is longer than the {settings.max_audio_seconds / 60:g}-minute limit.",
        )

    try:
        job = job_queue.create_job(
            session,
            job_id=job_id,
            profile=profile,
            language_hint=language,
            retain_audio=retain_audio,
            original_filename=uploads.display_name(audio.filename),
            audio_path=audio_path,
            idempotency_key=idempotency_key,
            now=now,
        )
    except job_queue.DuplicateJob as duplicate:
        uploads.delete_audio(audio_path, data_dir)
        response.status_code = 200
        return job_queue.to_status(session, duplicate.existing, now, data_dir)
    except Exception:
        uploads.delete_audio(audio_path, data_dir)
        raise
    return job_queue.to_status(session, job, now, data_dir)


@router.get("/analyses/{analysis_id}", response_model=schemas.AnalysisResult)
def get_analysis(analysis_id: str, session: SessionDep) -> schemas.AnalysisResult:
    """The stored result of a finished analysis, exactly as it was measured."""
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    result = schemas.AnalysisResult.model_validate(analysis.result)
    # The recording can be deleted later without touching the measurements.
    result.audio_retained = analysis.audio_path is not None
    return result


@router.get("/analysis-options", response_model=schemas.AnalysisOptions)
def get_analysis_options() -> schemas.AnalysisOptions:
    """Everything the submission form needs: delivery profiles, languages and upload limits."""
    return schemas.AnalysisOptions(
        profiles=[
            schemas.DeliveryProfile(
                id=profile.id,
                name=profile.name,
                summary=profile.summary,
                targets=list(profile.targets),
                focus=[
                    schemas.FocusMetric(metric=f.metric, label=f.label, looks_for=f.looks_for)
                    for f in profile.focus
                ],
                not_measured=list(profile.not_measured),
            )
            for profile in profiles.PROFILES
        ],
        profile_note=profiles.PROFILE_NOTE,
        languages=[
            schemas.LanguageOption(id=code, label=label, note=note)
            for code, label, note in profiles.LANGUAGES
        ],
        limits=schemas.UploadLimits(
            max_upload_bytes=settings.max_upload_bytes,
            max_audio_seconds=settings.max_audio_seconds,
            accepted_extensions=sorted(uploads.ALLOWED_EXTENSIONS),
        ),
    )


@router.get("/analyses", response_model=schemas.AnalysisList)
def list_analyses(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> schemas.AnalysisList:
    """Past analyses, newest first, with the headline numbers of each."""
    return history.list_analyses(session, limit=limit, offset=offset)


@router.delete("/analyses", response_model=schemas.HistoryCleared)
def clear_history(session: SessionDep, data_dir: DataDirDep) -> schemas.HistoryCleared:
    """Deletes every stored result, every finished job, and all audio belonging to them.

    Jobs still queued or running are not touched.
    """
    return history.clear_history(session, data_dir)


@router.delete("/analyses/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: str, session: SessionDep, data_dir: DataDirDep) -> None:
    """Deletes one result, its kept recording if any, and the job that produced it."""
    if not history.delete_analysis(session, analysis_id, data_dir):
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")


@router.get("/analyses/{analysis_id}/audio")
def get_analysis_audio(analysis_id: str, session: SessionDep, data_dir: DataDirDep) -> FileResponse:
    """The recording itself, if the user asked for it to be kept."""
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    if not uploads.audio_exists(analysis.audio_path, data_dir):
        raise _error(404, "audio_not_kept", "The recording for this analysis was not kept.")
    path = uploads.absolute(analysis.audio_path, data_dir)
    return FileResponse(
        path, media_type=uploads.CONTENT_TYPE_BY_EXTENSION.get(path.suffix.lower(), "audio/*")
    )


@router.delete("/analyses/{analysis_id}/audio", status_code=204)
def delete_analysis_audio(analysis_id: str, session: SessionDep, data_dir: DataDirDep) -> None:
    """Deletes only the kept recording. The measurements stay."""
    removed = history.delete_kept_audio(session, analysis_id, data_dir)
    if removed is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    if not removed:
        raise _error(404, "audio_not_kept", "The recording for this analysis was not kept.")
