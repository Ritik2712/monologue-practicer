from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from app import history, job_queue, profiles, revisions, schemas, uploads
from app.comparison.compare import compare
from app.comparison.settings import DEFAULT_COMPARISON_SETTINGS
from app.config import settings
from app.dependencies import DataDirDep, NowDep, SessionDep
from app.models import Analysis
from app.pipeline.audio import probe_audio
from app.pipeline.errors import PipelineError

router = APIRouter(prefix="/api", tags=["analyses"])


# Room for the form fields and multipart boundaries that travel with the file.
REQUEST_OVERHEAD_BYTES = 64 * 1024
MAX_TITLE_CHARACTERS = 120
DEFAULT_REFERENCE_TITLE = "Reference recording"


def reference_title(given: str | None, filename: str | None) -> str:
    """The name a reference is listed under: what the user typed, else the file's name."""
    title = " ".join((given or "").split())
    if not title and filename:
        # "knocks-scene.final.mp3" -> "knocks-scene.final"
        title = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (title or DEFAULT_REFERENCE_TITLE)[:MAX_TITLE_CHARACTERS]


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
    role: Annotated[schemas.Role, Form()] = "take",
    title: Annotated[str | None, Form(max_length=300)] = None,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> schemas.JobStatus:
    """Accepts a recording, queues it for analysis and returns at once with a job to poll.

    Nothing slow happens here. The file is checked, saved, and a job row is created; the
    worker does the rest. Sending the same `Idempotency-Key` header again returns the
    original job instead of creating a second one.

    `role` says what the recording is: one of the user's own takes (the default), or a
    `reference` to compare takes against. A reference is measured in exactly the same way,
    is listed separately, gets no coaching, and can be given a `title`.
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
            role=role,
            title=(
                reference_title(title, uploads.display_name(audio.filename))
                if role == job_queue.REFERENCE
                else None
            ),
        )
    except job_queue.DuplicateJob as duplicate:
        uploads.delete_audio(audio_path, data_dir)
        response.status_code = 200
        return job_queue.to_status(session, duplicate.existing, now, data_dir)
    except Exception:
        uploads.delete_audio(audio_path, data_dir)
        raise
    return job_queue.to_status(session, job, now, data_dir)


def _result(session, analysis: Analysis) -> schemas.AnalysisResult:
    result = schemas.AnalysisResult.model_validate(analysis.result)
    # The recording can be deleted later without touching the measurements.
    result.audio_retained = analysis.audio_path is not None
    if analysis.coaching:
        result.coaching = schemas.Coaching.model_validate(analysis.coaching)
    # Looked up now, so an older result also lists the revisions made after it.
    result.revisions = revisions.revision_infos(session, analysis)
    return result


@router.get("/analyses/{analysis_id}", response_model=schemas.AnalysisResult)
def get_analysis(analysis_id: str, session: SessionDep) -> schemas.AnalysisResult:
    """The stored result of a finished analysis, exactly as it was measured.

    `revisions` lists every result made from the same recording: the first analysis, and
    any later one made by correcting the transcript or analysing the recording again.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    return _result(session, analysis)


@router.post(
    "/analyses/{analysis_id}/transcript", response_model=schemas.AnalysisResult, status_code=201
)
def correct_transcript(
    analysis_id: str,
    request: schemas.TranscriptCorrectionRequest,
    session: SessionDep,
    data_dir: DataDirDep,
    now: NowDep,
) -> schemas.AnalysisResult:
    """Stores a new revision of a recording with the words of some phrases corrected.

    Word counts and WPM are worked out again from the corrected words and each phrase's own
    measured length. Nothing measured from the sound changes, and the result that was
    corrected stays as it was. Returns the new revision.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    try:
        revision = revisions.create_corrected(session, analysis, request.corrections, now, data_dir)
    except revisions.RevisionError as error:
        raise _error(error.status, error.code, error.message) from None
    return _result(session, revision)


@router.post(
    "/analyses/{analysis_id}/reanalysis",
    response_model=schemas.JobStatus,
    status_code=202,
    responses={200: {"model": schemas.JobStatus, "description": "One is already in progress"}},
)
def analyse_again(
    analysis_id: str, response: Response, session: SessionDep, data_dir: DataDirDep, now: NowDep
) -> schemas.JobStatus:
    """Queues a fresh analysis of this result's kept recording, with the current settings.

    Returns at once with a job to poll. The new result is stored as a further revision of
    the same recording; this one is not changed. Needs the recording to have been kept.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    try:
        job, created = revisions.create_reanalysis_job(session, analysis, now, data_dir)
    except revisions.RevisionError as error:
        raise _error(error.status, error.code, error.message) from None
    if not created:
        response.status_code = 200
    return job_queue.to_status(session, job, now, data_dir)


@router.get("/analyses/{analysis_id}/waveform", response_model=schemas.Waveform)
def get_waveform(analysis_id: str, session: SessionDep) -> schemas.Waveform:
    """The outline of the recording's sound wave, for drawing.

    A picture only. No measurement is taken from it, and fetching it changes nothing. It
    is stored when the recording is analysed, so it is there even if the audio was not kept.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    if not analysis.waveform:
        raise _error(
            404,
            "waveform_not_stored",
            "No waveform was stored for this recording. It was analysed before waveforms "
            "were added.",
        )
    return schemas.Waveform.model_validate(analysis.waveform)


@router.get("/analyses/{analysis_id}/comparison/{reference_id}", response_model=schemas.Comparison)
def compare_with_reference(
    analysis_id: str, reference_id: str, session: SessionDep
) -> schemas.Comparison:
    """Sets one analysis against a reference recording.

    Worked out on the spot from the two stored results, which takes a few thousandths of a
    second. Nothing is stored and neither result is changed, so the same question always
    gets the same answer.
    """
    take = session.get(Analysis, analysis_id)
    if take is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    reference = session.get(Analysis, reference_id)
    if reference is None or reference.role != job_queue.REFERENCE:
        raise _error(404, "reference_not_found", "No reference recording with this ID exists.")
    if take.id == reference.id:
        raise _error(400, "same_recording", "A recording cannot be compared with itself.")
    return compare(
        schemas.AnalysisBody.model_validate(take.result),
        schemas.AnalysisBody.model_validate(reference.result),
        DEFAULT_COMPARISON_SETTINGS,
        take_id=take.id,
        reference_id=reference.id,
        reference_title=reference.title,
    )


@router.post(
    "/analyses/{analysis_id}/coaching",
    response_model=schemas.JobStatus,
    status_code=202,
    responses={200: {"model": schemas.JobStatus, "description": "One is already in progress"}},
)
def regenerate_coaching(
    analysis_id: str, response: Response, session: SessionDep, data_dir: DataDirDep, now: NowDep
) -> schemas.JobStatus:
    """Asks for this analysis's coaching to be written again by the local language model.

    Returns at once with a job to poll, like submitting a recording does. The measurements
    are not touched and no audio is needed. If the language model cannot answer, the job
    fails and the coaching that was already there stays as it is.
    """
    analysis = session.get(Analysis, analysis_id)
    if analysis is None:
        raise _error(404, "analysis_not_found", "No analysis with this ID exists.")
    job, created = job_queue.create_coaching_job(session, analysis, now)
    if not created:
        response.status_code = 200
    return job_queue.to_status(session, job, now, data_dir)


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
    role: schemas.Role = "take",
) -> schemas.AnalysisList:
    """Past analyses, newest first, with the headline numbers of each.

    Lists the user's own takes unless `role=reference` asks for the reference recordings.
    """
    return history.list_analyses(session, limit=limit, offset=offset, role=role)


@router.delete("/analyses", response_model=schemas.HistoryCleared)
def clear_history(
    session: SessionDep, data_dir: DataDirDep, role: schemas.Role = "take"
) -> schemas.HistoryCleared:
    """Deletes every stored result of one role, its finished jobs, and all their audio.

    Clears the history of takes unless `role=reference` is given. The other is never
    touched, and neither are jobs still queued or running.
    """
    return history.clear_history(session, data_dir, role=role)


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
