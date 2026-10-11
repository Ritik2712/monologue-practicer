"""Listing, viewing and deleting past analyses, and the options the form offers."""

from app import uploads
from app.config import settings
from app.schemas import Metrics
from tests.conftest import wav_bytes


def analyse(client, make_worker, **form) -> str:
    """Uploads a recording, runs it, and returns the analysis ID."""
    job_id = client.post(
        "/api/analyses",
        files={"audio": (form.pop("filename", "take.wav"), wav_bytes(9.0), "audio/wav")},
        data=form,
    ).json()["jobId"]
    make_worker().process_next_job()
    return client.get(f"/api/jobs/{job_id}").json()["analysisId"]


def files_in(data_dir, folder: str) -> list[str]:
    path = data_dir / folder
    return sorted(item.name for item in path.iterdir()) if path.is_dir() else []


# --- Form options ------------------------------------------------------------------------


def test_options_list_the_profiles_languages_and_limits(client):
    options = client.get("/api/analysis-options").json()

    assert [profile["id"] for profile in options["profiles"]] == [
        "walter_white",
        "joker",
        "thomas_shelby",
        "custom",
    ]
    assert [language["id"] for language in options["languages"]] == ["auto", "en", "hi", "hinglish"]
    assert "not a measurement of any actor's voice" in options["profileNote"]
    assert options["limits"] == {
        "maxUploadBytes": settings.max_upload_bytes,
        "maxAudioSeconds": settings.max_audio_seconds,
        "acceptedExtensions": sorted(uploads.ALLOWED_EXTENSIONS),
    }

    walter = options["profiles"][0]
    assert walter["name"] == "Walter White"
    assert walter["targets"]
    assert walter["notMeasured"] == ["Clarity of consonants"]
    custom = options["profiles"][-1]
    assert (custom["targets"], custom["focus"], custom["notMeasured"]) == ([], [], [])


def test_every_profile_focus_points_at_a_metric_that_really_exists(client):
    real_metrics = {field.alias for field in Metrics.model_fields.values()}
    for profile in client.get("/api/analysis-options").json()["profiles"]:
        for focus in profile["focus"]:
            assert focus["metric"] in real_metrics, (profile["id"], focus["metric"])


# --- History list ------------------------------------------------------------------------


def test_history_is_empty_at_first(client):
    assert client.get("/api/analyses").json() == {"items": [], "total": 0}


def test_history_lists_newest_first_with_headline_numbers(client, make_worker, clock):
    first = analyse(client, make_worker, profile="joker", filename="first.wav")
    clock.advance(minutes=5)
    second = analyse(client, make_worker, profile="walter_white", language="en")

    history = client.get("/api/analyses").json()
    assert history["total"] == 2
    assert [item["analysisId"] for item in history["items"]] == [second, first]

    newest, oldest = history["items"]
    assert (newest["profile"], newest["language"], newest["originalFilename"]) == (
        "walter_white",
        "en",
        "take.wav",
    )
    assert (oldest["profile"], oldest["originalFilename"]) == ("joker", "first.wav")
    assert newest["durationSeconds"] == 9.0
    assert newest["audioRetained"] is False
    assert newest["revision"] == 1
    assert newest["metrics"]["speechActiveWpm"]["value"] == 180.0
    assert newest["metrics"]["pauseCount"]["value"] == 1
    assert newest["metrics"]["longestPauseSeconds"]["value"] == 1.5
    assert "pitch_unavailable" in newest["warningCodes"]
    # The list stays light: the full transcript and word list are not in it.
    assert "transcript" not in newest
    assert "words" not in newest


def test_history_is_paged(client, make_worker, clock):
    ids = []
    for _ in range(3):
        ids.append(analyse(client, make_worker))
        clock.advance(minutes=1)

    page = client.get("/api/analyses", params={"limit": 2}).json()
    assert page["total"] == 3
    assert [item["analysisId"] for item in page["items"]] == [ids[2], ids[1]]

    rest = client.get("/api/analyses", params={"limit": 2, "offset": 2}).json()
    assert [item["analysisId"] for item in rest["items"]] == [ids[0]]

    assert client.get("/api/analyses", params={"limit": 0}).status_code == 422
    assert client.get("/api/analyses", params={"limit": 101}).status_code == 422


# --- Kept recordings ---------------------------------------------------------------------


def test_a_kept_recording_can_be_played_back_and_then_deleted_on_its_own(
    client, make_worker, data_dir
):
    analysis_id = analyse(client, make_worker, retainAudio="true")

    audio = client.get(f"/api/analyses/{analysis_id}/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/wav"
    assert audio.content == wav_bytes(9.0)

    assert client.delete(f"/api/analyses/{analysis_id}/audio").status_code == 204
    assert files_in(data_dir, uploads.RETAINED_DIR) == []

    # The measurements are untouched; only the recording has gone.
    result = client.get(f"/api/analyses/{analysis_id}").json()
    assert result["audioRetained"] is False
    assert result["metrics"]["speechActiveWpm"]["value"] == 180.0
    assert client.get("/api/analyses").json()["items"][0]["audioRetained"] is False

    again = client.delete(f"/api/analyses/{analysis_id}/audio")
    assert (again.status_code, again.json()["detail"]["code"]) == (404, "audio_not_kept")


def test_there_is_no_audio_to_play_when_it_was_not_kept(client, make_worker):
    analysis_id = analyse(client, make_worker)
    response = client.get(f"/api/analyses/{analysis_id}/audio")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "audio_not_kept")


def test_audio_requests_for_unknown_analyses_are_404s(client):
    for method in ("get", "delete"):
        response = getattr(client, method)("/api/analyses/nope/audio")
        assert (response.status_code, response.json()["detail"]["code"]) == (
            404,
            "analysis_not_found",
        )


# --- Deleting ----------------------------------------------------------------------------


def test_deleting_an_analysis_removes_its_result_job_and_kept_recording(
    client, make_worker, data_dir
):
    keep = analyse(client, make_worker)
    doomed = analyse(client, make_worker, retainAudio="true")
    doomed_job = client.get(f"/api/analyses/{doomed}").json()["jobId"]
    assert files_in(data_dir, uploads.RETAINED_DIR) == [f"{doomed}.wav"]

    assert client.delete(f"/api/analyses/{doomed}").status_code == 204

    assert client.get(f"/api/analyses/{doomed}").status_code == 404
    assert client.get(f"/api/jobs/{doomed_job}").status_code == 404
    assert files_in(data_dir, uploads.RETAINED_DIR) == []
    remaining = client.get("/api/analyses").json()
    assert [item["analysisId"] for item in remaining["items"]] == [keep]

    assert client.delete(f"/api/analyses/{doomed}").status_code == 404


def test_clearing_history_removes_everything_finished_and_nothing_still_in_progress(
    client, make_worker, data_dir, transcriber
):
    analyse(client, make_worker)
    analyse(client, make_worker, retainAudio="true")

    # A failed job that is still holding its upload for a retry.
    transcriber.error = RuntimeError("boom")
    failed_job = client.post(
        "/api/analyses", files={"audio": ("bad.wav", wav_bytes(9.0), "audio/wav")}
    ).json()["jobId"]
    make_worker().process_next_job()
    transcriber.error = None

    # And one that has not started yet.
    waiting_job = client.post(
        "/api/analyses", files={"audio": ("next.wav", wav_bytes(9.0), "audio/wav")}
    ).json()["jobId"]
    assert files_in(data_dir, uploads.UPLOADS_DIR) == sorted(
        [f"{failed_job}.wav", f"{waiting_job}.wav"]
    )

    cleared = client.delete("/api/analyses")

    assert cleared.status_code == 200
    assert cleared.json() == {"deletedAnalyses": 2, "deletedJobs": 3}
    assert client.get("/api/analyses").json() == {"items": [], "total": 0}
    assert files_in(data_dir, uploads.RETAINED_DIR) == []
    assert client.get(f"/api/jobs/{failed_job}").status_code == 404
    # The queued job and its upload survive, and it can still run.
    assert files_in(data_dir, uploads.UPLOADS_DIR) == [f"{waiting_job}.wav"]
    assert client.get(f"/api/jobs/{waiting_job}").json()["status"] == "queued"
    make_worker().process_next_job()
    assert client.get("/api/analyses").json()["total"] == 1
