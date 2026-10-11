"""The HTTP API, from upload to fetching the result."""

from dataclasses import replace

import pytest

from app import uploads
from app.routes import analyses as analyses_route
from tests.conftest import wav_bytes


def upload(client, content: bytes | None = None, *, filename="take.wav", content_type="audio/wav",
           key: str | None = None, **form):  # fmt: skip
    return client.post(
        "/api/analyses",
        files={"audio": (filename, wav_bytes(9.0) if content is None else content, content_type)},
        data=form,
        headers={"Idempotency-Key": key} if key else {},
    )


def stored_uploads(data_dir) -> list[str]:
    folder = data_dir / uploads.UPLOADS_DIR
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


@pytest.fixture
def limits(monkeypatch):
    """Lets a test shrink the upload limits."""

    def apply(**changes) -> None:
        monkeypatch.setattr(analyses_route, "settings", replace(analyses_route.settings, **changes))

    return apply


# --- Health ------------------------------------------------------------------------------


def test_health_reports_the_database_the_worker_and_the_speech_model(client, make_worker, clock):
    assert client.get("/api/health").json() == {
        "status": "ok",
        "database": "ok",
        "worker": "not_running",
        "speechModel": "unknown",
    }

    make_worker().beat()
    assert client.get("/api/health").json() == {
        "status": "ok",
        "database": "ok",
        "worker": "running",
        "speechModel": "ready",
    }

    clock.advance(seconds=60)  # the worker has gone quiet
    assert client.get("/api/health").json()["worker"] == "not_running"


def test_only_local_pages_may_call_the_api(client):
    local = client.get("/api/health", headers={"Origin": "http://localhost:3101"})
    remote = client.get("/api/health", headers={"Origin": "http://localhost.evil.example"})
    assert local.headers.get("access-control-allow-origin") == "http://localhost:3101"
    assert "access-control-allow-origin" not in remote.headers


# --- Submitting --------------------------------------------------------------------------


def test_submitting_returns_a_job_straight_away(client, data_dir):
    response = upload(client, profile="walter_white", language="hi")

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert job["stage"] is None
    assert job["analysisId"] is None
    assert job["error"] is None
    assert job["queuePosition"] == 0
    assert job["canCancel"] is True
    assert job["canRetry"] is False
    # Nothing will happen until a worker is started, and the response says so.
    assert job["workerAlive"] is False
    assert stored_uploads(data_dir) == [f"{job['jobId']}.wav"]

    assert client.get(f"/api/jobs/{job['jobId']}").json() == job


def test_a_repeated_idempotency_key_returns_the_first_job_and_stores_nothing_new(client, data_dir):
    first = upload(client, key="double-click")
    second = upload(client, key="double-click")
    third = upload(client, key="another-take")

    assert (first.status_code, second.status_code, third.status_code) == (202, 200, 202)
    assert second.json()["jobId"] == first.json()["jobId"]
    assert third.json()["jobId"] != first.json()["jobId"]
    assert len(stored_uploads(data_dir)) == 2


def test_a_browser_recording_is_accepted_by_its_content_type(client):
    # MediaRecorder uploads often have no useful file name.
    response = upload(client, filename="blob", content_type="audio/wav;codecs=1")
    assert response.status_code == 202


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("notes.txt", "text/plain"), ("photo.png", "image/png"), ("blob", "application/octet-stream")],
)
def test_files_that_are_not_audio_types_are_refused(client, data_dir, filename, content_type):
    response = upload(client, b"hello", filename=filename, content_type=content_type)
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_type"
    assert stored_uploads(data_dir) == []


def test_a_file_that_only_claims_to_be_audio_is_refused_and_not_kept(client, data_dir):
    response = upload(client, b"definitely not audio" * 50, filename="fake.mp3")
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unreadable_audio"
    assert stored_uploads(data_dir) == []


def test_an_empty_file_is_refused(client, data_dir):
    response = upload(client, b"")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_file"
    assert stored_uploads(data_dir) == []


def test_a_file_far_over_the_size_limit_is_refused_before_it_is_read(client, data_dir, limits):
    limits(max_upload_bytes=10_000)
    response = upload(client)  # about 288 kB
    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "file_too_large",
        "message": "The file is larger than the 0.00953674 MB limit.",
    }
    assert stored_uploads(data_dir) == []


def test_a_file_just_over_the_size_limit_is_refused_while_saving_and_not_kept(
    client, data_dir, limits
):
    content = wav_bytes(9.0)
    # Within the allowance for form overhead, so only measuring the file itself catches it.
    limits(max_upload_bytes=len(content) - 100)
    response = upload(client, content)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "file_too_large"
    assert stored_uploads(data_dir) == []

    limits(max_upload_bytes=len(content))
    assert upload(client, content).status_code == 202


def test_a_refused_upload_still_carries_cors_headers(client, limits):
    limits(max_upload_bytes=10_000)
    response = client.post(
        "/api/analyses",
        files={"audio": ("take.wav", wav_bytes(9.0), "audio/wav")},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_a_recording_over_the_length_limit_is_refused_and_not_kept(client, data_dir, limits):
    limits(max_audio_seconds=5.0)
    response = upload(client)  # 9 seconds
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "audio_too_long"
    assert stored_uploads(data_dir) == []


def test_invalid_form_values_get_the_standard_error_shape(client, data_dir):
    response = upload(client, profile="darth_vader")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_request"
    assert "profile" in detail["message"]

    missing = client.post("/api/analyses", data={"profile": "custom"})
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "invalid_request"
    assert stored_uploads(data_dir) == []


# --- Polling, results --------------------------------------------------------------------


def test_the_full_journey_from_upload_to_result(client, data_dir, make_worker, clock):
    job_id = upload(client, profile="thomas_shelby", language="en").json()["jobId"]
    worker = make_worker()
    worker.beat()

    waiting = client.get(f"/api/jobs/{job_id}").json()
    assert (waiting["status"], waiting["workerAlive"]) == ("queued", True)

    clock.advance(seconds=2)
    worker.process_next_job()

    done = client.get(f"/api/jobs/{job_id}").json()
    assert done["status"] == "succeeded"
    assert done["stage"] is None
    assert done["canCancel"] is False
    assert done["attempt"] == 1
    assert done["startedAt"] is not None
    assert done["finishedAt"] is not None
    assert stored_uploads(data_dir) == []

    result = client.get(f"/api/analyses/{done['analysisId']}").json()
    assert result["schemaVersion"] == 1
    assert result["analysisId"] == done["analysisId"]
    assert result["jobId"] == job_id
    assert result["revision"] == 1
    assert result["profile"] == "thomas_shelby"
    assert result["language"] == {"code": "en", "source": "declared", "confidence": None}
    assert result["audioRetained"] is False
    assert result["durationSeconds"] == pytest.approx(9.0, abs=0.01)
    assert result["metrics"]["speechActiveWpm"] == {
        "value": 180.0,
        "unit": "words/minute",
        "quality": "measured",
        "note": "Total words / speaking time. Pauses are excluded.",
    }
    assert result["metrics"]["breathCount"]["quality"] == "unavailable"
    assert len(result["segments"]) == 2
    assert len(result["pauses"]) == 1
    assert len(result["words"]) == 18


def test_kept_audio_is_reported_on_the_result(client, data_dir, make_worker):
    job_id = upload(client, retainAudio="true").json()["jobId"]
    make_worker().process_next_job()
    analysis_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]

    assert client.get(f"/api/analyses/{analysis_id}").json()["audioRetained"] is True
    assert stored_uploads(data_dir) == []
    assert (data_dir / uploads.RETAINED_DIR / f"{analysis_id}.wav").is_file()


def test_unknown_ids_are_404s_with_the_standard_error_shape(client):
    for method, path in [
        ("get", "/api/jobs/nope"),
        ("post", "/api/jobs/nope/cancel"),
        ("post", "/api/jobs/nope/retry"),
        ("get", "/api/analyses/nope"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 404, path
        assert set(response.json()["detail"]) == {"code", "message"}, path


# --- Cancel and retry --------------------------------------------------------------------


def test_cancelling_a_queued_job(client, data_dir, make_worker):
    job_id = upload(client).json()["jobId"]

    cancelled = client.post(f"/api/jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert stored_uploads(data_dir) == []

    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"
    assert make_worker().process_next_job() is False


def test_cancelling_a_running_job_shows_as_running_until_the_worker_stops(
    client, data_dir, make_worker, transcriber
):
    job_id = upload(client).json()["jobId"]
    seen = {}

    def cancel_mid_job() -> None:
        seen.update(client.post(f"/api/jobs/{job_id}/cancel").json())

    transcriber.during = cancel_mid_job
    make_worker().process_next_job()

    assert (seen["status"], seen["cancelRequested"], seen["canCancel"]) == ("running", True, False)
    final = client.get(f"/api/jobs/{job_id}").json()
    assert (final["status"], final["cancelRequested"], final["analysisId"]) == (
        "cancelled",
        False,
        None,
    )
    assert stored_uploads(data_dir) == []


def test_a_finished_job_can_be_neither_cancelled_nor_retried(client, make_worker):
    job_id = upload(client).json()["jobId"]
    make_worker().process_next_job()

    cancel = client.post(f"/api/jobs/{job_id}/cancel")
    retry = client.post(f"/api/jobs/{job_id}/retry")
    assert (cancel.status_code, cancel.json()["detail"]["code"]) == (409, "already_finished")
    assert (retry.status_code, retry.json()["detail"]["code"]) == (409, "not_failed")


def test_a_failed_job_explains_itself_and_can_be_retried(
    client, data_dir, make_worker, transcriber
):
    job_id = upload(client).json()["jobId"]
    transcriber.error = RuntimeError("model crashed")
    worker = make_worker()
    worker.process_next_job()

    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["status"] == "failed"
    assert failed["error"] == {
        "code": "unexpected_error",
        "message": "Something went wrong while transcribing (RuntimeError).",
        "retryable": True,
    }
    assert failed["canRetry"] is True

    transcriber.error = None
    retried = client.post(f"/api/jobs/{job_id}/retry").json()
    assert (retried["status"], retried["error"], retried["jobId"]) == ("queued", None, job_id)

    worker.process_next_job()
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"
    assert stored_uploads(data_dir) == []


def test_a_failure_that_would_repeat_cannot_be_retried(client, data_dir, limits, make_worker):
    # The header check passes, but the worker is given a shorter limit than the API.
    job_id = upload(client).json()["jobId"]
    make_worker(max_audio_seconds=2.0).process_next_job()

    failed = client.get(f"/api/jobs/{job_id}").json()
    assert failed["error"]["code"] == "audio_too_long"
    assert failed["error"]["retryable"] is False
    assert failed["canRetry"] is False
    assert stored_uploads(data_dir) == []

    retry = client.post(f"/api/jobs/{job_id}/retry")
    assert (retry.status_code, retry.json()["detail"]["code"]) == (409, "not_retryable")
