"""The worker running real jobs end to end, with speech detection and transcription scripted."""

import os
import time

from sqlalchemy import select

from app import job_queue, uploads
from app.coaching.coach import Coach
from app.models import Analysis, Job, WorkerState
from app.pipeline.errors import PipelineError
from tests.conftest import FakeChat, answer_within


def get(session_factory, job_id: str) -> Job:
    with session_factory() as session:
        return session.get(Job, job_id)


def analyses(session_factory) -> list[Analysis]:
    with session_factory() as session:
        return list(session.execute(select(Analysis)).scalars())


def upload_files(data_dir) -> list[str]:
    folder = data_dir / uploads.UPLOADS_DIR
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


def test_nothing_to_do_on_an_empty_queue(make_worker):
    assert make_worker().process_next_job() is False


def test_a_job_runs_to_success_and_its_upload_is_deleted(
    session_factory, data_dir, add_job, make_worker, clock
):
    job_id = add_job(profile="joker", language_hint="en")

    assert make_worker().process_next_job() is True

    job = get(session_factory, job_id)
    assert job.status == "succeeded"
    assert job.stage is None
    assert job.audio_path is None
    assert job.finished_at == clock()
    assert upload_files(data_dir) == []

    (analysis,) = analyses(session_factory)
    assert job.analysis_id == analysis.id
    assert analysis.job_id == job_id
    assert analysis.profile == "joker"
    assert analysis.language == "en"
    assert analysis.revision == 1
    assert analysis.settings_version == 3
    assert analysis.audio_path is None

    result = analysis.result
    assert result["schemaVersion"] == 1
    assert result["analysisId"] == analysis.id
    assert result["jobId"] == job_id
    assert result["audioRetained"] is False
    assert result["settings"]["min_pause_ms"] == 500
    # The scripted recording: 12 words in 4 s, a 1.5 s pause, then 6 words in 2 s.
    assert [segment["segmentWpm"] for segment in result["segments"]] == [180.0, 180.0]
    assert result["metrics"]["speechActiveWpm"]["value"] == 180.0
    assert result["metrics"]["wholeClipWpm"]["value"] == 120.0  # 18 words in a 9 s clip
    assert result["metrics"]["longestPauseSeconds"]["value"] == 1.5


def test_the_job_reports_each_stage_while_it_runs(
    session_factory, add_job, make_worker, transcriber
):
    job_id = add_job()
    seen: list[tuple[str, str | None]] = []
    transcriber.during = lambda: seen.append(
        (get(session_factory, job_id).status, get(session_factory, job_id).stage)
    )
    make_worker().process_next_job()
    assert seen == [("running", "transcribing")]


def test_jobs_are_processed_one_at_a_time_in_order(session_factory, add_job, make_worker):
    first, second = add_job(), add_job()
    worker = make_worker()

    worker.process_next_job()
    assert get(session_factory, first).status == "succeeded"
    assert get(session_factory, second).status == "queued"

    worker.process_next_job()
    assert get(session_factory, second).status == "succeeded"
    assert worker.process_next_job() is False


def test_audio_is_kept_only_when_the_user_asked_for_it(
    session_factory, data_dir, add_job, make_worker
):
    add_job(retain_audio=True)
    make_worker().process_next_job()

    (analysis,) = analyses(session_factory)
    assert analysis.audio_path == f"audio/{analysis.id}.wav"
    assert uploads.audio_exists(analysis.audio_path, data_dir)
    assert analysis.result["audioRetained"] is True
    assert upload_files(data_dir) == []


def test_a_file_that_is_not_audio_fails_for_good_and_is_deleted(
    session_factory, data_dir, add_job, make_worker
):
    job_id = add_job(content=b"not audio at all" * 100, extension=".mp3")

    make_worker().process_next_job()

    job = get(session_factory, job_id)
    assert job.status == "failed"
    assert job.error_code == "unreadable_audio"
    assert not job.error_retryable
    assert job.audio_path is None
    assert upload_files(data_dir) == []
    assert analyses(session_factory) == []


def test_an_unexpected_error_fails_the_job_without_leaking_details(
    session_factory, data_dir, add_job, make_worker, transcriber
):
    job_id = add_job()
    transcriber.error = RuntimeError(
        f"cannot open {data_dir}/secret/path.bin: 'private transcript'"
    )

    make_worker().process_next_job()

    job = get(session_factory, job_id)
    assert job.status == "failed"
    assert job.error_code == "unexpected_error"
    assert job.error_message == "Something went wrong while transcribing (RuntimeError)."
    assert str(data_dir) not in job.error_message
    # It might work next time, so the audio is kept for a retry.
    assert job.error_retryable
    assert uploads.audio_exists(job.audio_path, data_dir)


def test_a_missing_speech_model_fails_with_instructions_and_succeeds_on_retry(
    session_factory, data_dir, clock, add_job, make_worker, transcriber
):
    job_id = add_job()
    transcriber.error = PipelineError(
        "speech_model_missing", "Run: uv run python -m app.speech_model download", retryable=True
    )
    worker = make_worker()
    worker.process_next_job()

    job = get(session_factory, job_id)
    assert (job.status, job.error_code) == ("failed", "speech_model_missing")
    assert "app.speech_model download" in job.error_message

    transcriber.error = None  # the model has been installed
    with session_factory() as session:
        job_queue.retry_job(session, job_id, clock(), data_dir)
    worker.process_next_job()

    job = get(session_factory, job_id)
    assert job.status == "succeeded"
    assert job.error_code is None
    assert len(analyses(session_factory)) == 1
    assert upload_files(data_dir) == []


def test_cancelling_during_transcription_really_stops_the_job(
    session_factory, data_dir, clock, add_job, make_worker, transcriber
):
    job_id = add_job()

    def user_presses_cancel() -> None:
        with session_factory() as session:
            job_queue.request_cancel(session, job_id, clock(), data_dir)

    transcriber.during = user_presses_cancel
    make_worker().process_next_job()

    job = get(session_factory, job_id)
    assert job.status == "cancelled"
    assert not job.cancel_requested
    assert job.audio_path is None
    assert upload_files(data_dir) == []
    assert analyses(session_factory) == []


def test_a_cancelled_job_does_not_block_the_next_one(
    session_factory, data_dir, clock, add_job, make_worker, transcriber
):
    first, second = add_job(), add_job()

    def cancel_first_only() -> None:
        with session_factory() as session:
            if session.get(Job, first).status == "running":
                job_queue.request_cancel(session, first, clock(), data_dir)

    transcriber.during = cancel_first_only
    worker = make_worker()
    worker.process_next_job()
    worker.process_next_job()
    assert get(session_factory, first).status == "cancelled"
    assert get(session_factory, second).status == "succeeded"


def test_a_stopping_worker_hands_its_job_back_to_the_queue(
    session_factory, data_dir, add_job, make_worker, transcriber
):
    job_id = add_job()
    worker = make_worker()
    transcriber.during = worker.stop_event.set  # Ctrl+C arrives mid-job

    worker.process_next_job()

    job = get(session_factory, job_id)
    assert job.status == "queued"
    assert job.attempt == 0
    assert uploads.audio_exists(job.audio_path, data_dir)
    assert analyses(session_factory) == []


def test_missing_audio_fails_the_job_cleanly(session_factory, data_dir, add_job, make_worker):
    job_id = add_job()
    uploads.delete_audio(get(session_factory, job_id).audio_path, data_dir)
    make_worker().process_next_job()
    job = get(session_factory, job_id)
    assert (job.status, job.error_code, job.error_retryable) == ("failed", "audio_missing", False)


def test_the_heartbeat_reports_the_worker_and_the_job_it_is_on(
    session_factory, clock, add_job, make_worker, transcriber
):
    job_id = add_job()
    worker = make_worker(speech_model_ready=lambda: False)

    def later_heartbeat() -> None:
        clock.advance(seconds=20)
        worker.beat()

    transcriber.during = later_heartbeat
    worker.process_next_job()

    with session_factory() as session:
        state = session.get(WorkerState, 1)
        assert state.pid == os.getpid()
        assert state.speech_model == "fake-model"
        assert state.speech_model_ready is False
        assert job_queue.worker_alive(session, clock())
    # The job's own heartbeat moved with the worker's, so it was not mistaken for dead.
    assert get(session_factory, job_id).heartbeat_at >= clock()


def test_jobs_left_running_by_a_crash_are_requeued_when_the_worker_starts(
    session_factory, clock, add_job, make_worker
):
    job_id = add_job()
    with session_factory() as session:
        job_queue.claim_next_job(session, clock())  # a worker took it, then died

    worker = make_worker()
    worker.recover(stale_after_seconds=0)

    assert get(session_factory, job_id).status == "queued"
    worker.process_next_job()
    job = get(session_factory, job_id)
    assert (job.status, job.attempt) == ("succeeded", 2)


def test_clean_up_removes_only_old_files_that_no_job_refers_to(
    session_factory, data_dir, add_job, make_worker
):
    kept = get(session_factory, add_job()).audio_path
    folder = data_dir / uploads.UPLOADS_DIR
    old_stray = folder / "abandoned.wav"
    new_stray = folder / "arriving.wav"
    for path in (old_stray, new_stray):
        path.write_bytes(b"x")
    two_hours_ago = time.time() - 7200
    os.utime(old_stray, (two_hours_ago, two_hours_ago))
    os.utime(uploads.absolute(kept, data_dir), (two_hours_ago, two_hours_ago))

    make_worker().clean_up_files()

    assert not old_stray.exists()
    assert new_stray.exists()  # may belong to a job that is being created right now
    assert uploads.audio_exists(kept, data_dir)  # old, but a queued job still needs it


def test_a_second_worker_notices_the_first(session_factory, clock, make_worker):
    worker = make_worker()
    assert not worker.another_worker_is_running()

    with session_factory() as session:
        job_queue.report_worker(
            session, pid=os.getppid(), now=clock(), speech_model="small", speech_model_ready=True
        )
    assert worker.another_worker_is_running()

    clock.advance(seconds=60)  # the other one stopped reporting
    assert not worker.another_worker_is_running()


# --- Coaching ----------------------------------------------------------------------------


def coaching_job(session_factory, clock) -> str:
    """Queues a coaching job for the one stored analysis and returns the job's ID."""
    with session_factory() as session:
        analysis = session.execute(select(Analysis)).scalar_one()
        job, _ = job_queue.create_coaching_job(session, analysis, clock())
        return job.id


def test_the_language_model_words_the_coaching_as_the_last_stage(
    session_factory, add_job, make_worker
):
    job_id = add_job(profile="thomas_shelby")
    llm = FakeChat(answer_within)
    seen: list[tuple[str, str | None]] = []
    llm.during = lambda: seen.append(
        (get(session_factory, job_id).status, get(session_factory, job_id).stage)
    )

    make_worker(llm).process_next_job()

    assert seen == [("running", "generating_feedback")]
    (analysis,) = analyses(session_factory)
    assert (analysis.coaching["source"], analysis.coaching["model"]) == ("ai", "fake-llm")
    # Coaching is stored beside the measurements, not inside them.
    assert "coaching" not in analysis.result


def test_a_model_that_cannot_answer_does_not_fail_the_analysis(
    session_factory, add_job, make_worker
):
    job_id = add_job(profile="thomas_shelby")
    make_worker(FakeChat(model_status="not_running")).process_next_job()

    assert get(session_factory, job_id).status == "succeeded"
    (analysis,) = analyses(session_factory)
    assert analysis.coaching["source"] == "rules"
    assert analysis.coaching["notice"]["code"] == "not_running"
    assert analysis.coaching["corrections"]


def test_a_crash_in_the_coaching_step_still_saves_the_measurements(
    session_factory, add_job, make_worker
):
    class BrokenCoach(Coach):
        def generate(self, body, **kwargs):
            raise RuntimeError("a bug nobody planned for")

    job_id = add_job()
    make_worker(coach=BrokenCoach(None)).process_next_job()

    assert get(session_factory, job_id).status == "succeeded"
    (analysis,) = analyses(session_factory)
    assert analysis.coaching is None
    assert analysis.result["metrics"]["speechActiveWpm"]["value"] == 180.0


def test_cancelling_while_the_model_is_writing_stores_nothing(
    session_factory, data_dir, clock, add_job, make_worker
):
    job_id = add_job(profile="thomas_shelby")
    llm = FakeChat(answer_within)

    def cancel() -> None:
        with session_factory() as session:
            job_queue.request_cancel(session, job_id, clock(), data_dir)

    llm.during = cancel
    make_worker(llm).process_next_job()

    assert get(session_factory, job_id).status == "cancelled"
    assert analyses(session_factory) == []
    assert upload_files(data_dir) == []


def test_a_coaching_job_replaces_the_coaching_and_nothing_else(
    session_factory, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    (before,) = analyses(session_factory)
    assert before.coaching["source"] == "rules"
    job_id = coaching_job(session_factory, clock)

    make_worker(FakeChat(answer_within)).process_next_job()

    job = get(session_factory, job_id)
    assert (job.kind, job.status, job.stage, job.analysis_id) == (
        "coaching",
        "succeeded",
        None,
        before.id,
    )
    (after,) = analyses(session_factory)
    assert after.coaching["source"] == "ai"
    assert after.result == before.result


def test_a_coaching_job_that_cannot_reach_the_model_fails_and_changes_nothing(
    session_factory, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    (before,) = analyses(session_factory)
    job_id = coaching_job(session_factory, clock)

    make_worker(FakeChat(model_status="model_missing")).process_next_job()

    job = get(session_factory, job_id)
    assert (job.status, job.error_code, job.error_retryable) == ("failed", "model_missing", False)
    assert analyses(session_factory)[0].coaching == before.coaching


def test_a_coaching_job_fails_when_templates_are_all_that_is_on_offer(
    session_factory, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    job_id = coaching_job(session_factory, clock)

    make_worker().process_next_job()  # no language model at all

    job = get(session_factory, job_id)
    assert (job.status, job.error_code) == ("failed", "ai_off")
    assert job.error_message == "AI coaching is switched off in the settings."


def test_a_cancelled_coaching_job_leaves_the_old_coaching_in_place(
    session_factory, data_dir, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    (before,) = analyses(session_factory)
    job_id = coaching_job(session_factory, clock)
    llm = FakeChat(answer_within)

    def cancel() -> None:
        with session_factory() as session:
            job_queue.request_cancel(session, job_id, clock(), data_dir)

    llm.during = cancel
    make_worker(llm).process_next_job()

    assert get(session_factory, job_id).status == "cancelled"
    assert analyses(session_factory)[0].coaching == before.coaching


def test_a_stopping_worker_hands_a_coaching_job_back_to_the_queue(
    session_factory, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    job_id = coaching_job(session_factory, clock)
    llm = FakeChat(answer_within)
    worker = make_worker(llm)
    llm.during = worker.stop_event.set

    worker.process_next_job()

    job = get(session_factory, job_id)
    assert (job.status, job.attempt) == ("queued", 0)


def test_a_coaching_job_left_running_by_a_crash_is_requeued_without_any_audio(
    session_factory, clock, add_job, make_worker
):
    add_job(profile="thomas_shelby")
    make_worker().process_next_job()
    job_id = coaching_job(session_factory, clock)
    with session_factory() as session:
        job_queue.claim_next_job(session, clock())  # a worker took it, then died

    worker = make_worker(FakeChat(answer_within))
    worker.recover(stale_after_seconds=0)
    assert get(session_factory, job_id).status == "queued"

    worker.process_next_job()
    assert get(session_factory, job_id).status == "succeeded"


def test_the_heartbeat_reports_whether_the_language_model_is_available(
    session_factory, make_worker
):
    make_worker(FakeChat(model_status="model_missing")).beat()
    with session_factory() as session:
        state = session.get(WorkerState, 1)
        assert (state.coach_model, state.coach_status) == ("fake-llm", "model_missing")


# --- Reference recordings and waveforms ---------------------------------------------------


def test_a_reference_is_measured_like_a_take_but_gets_no_coaching(
    session_factory, add_job, make_worker
):
    job_id = add_job(role="reference", title="The original", profile="thomas_shelby")
    llm = FakeChat(answer_within)
    seen: list[str | None] = []
    worker = make_worker(llm)
    original_set_stage = job_queue.set_stage

    def record_stage(session, job, stage, now):
        seen.append(stage)
        original_set_stage(session, job, stage, now)

    job_queue.set_stage = record_stage
    try:
        worker.process_next_job()
    finally:
        job_queue.set_stage = original_set_stage

    assert get(session_factory, job_id).status == "succeeded"
    (analysis,) = analyses(session_factory)
    assert (analysis.role, analysis.title) == ("reference", "The original")
    assert (analysis.result["role"], analysis.result["title"]) == ("reference", "The original")
    # The same measurements as any take.
    assert analysis.result["metrics"]["speechActiveWpm"]["value"] == 180.0
    # No coaching stage, no call to the language model, nothing stored.
    assert "generating_feedback" not in seen and seen[-1] == "measuring_audio"
    assert llm.calls == [] and analysis.coaching is None


def test_a_take_is_stored_as_a_take(session_factory, add_job, make_worker):
    add_job()
    make_worker().process_next_job()
    (analysis,) = analyses(session_factory)
    assert (analysis.role, analysis.title, analysis.result["role"]) == ("take", None, "take")


def test_the_waveform_outline_is_stored_beside_the_measurements_not_in_them(
    session_factory, add_job, make_worker
):
    add_job()  # nine seconds of a steady tone at 0.3 of full scale
    make_worker().process_next_job()
    (analysis,) = analyses(session_factory)

    outline = analysis.waveform
    assert outline["durationSeconds"] == 9.0
    assert len(outline["minimum"]) == len(outline["maximum"]) == 1800  # 5 ms each
    assert max(outline["maximum"]) == 0.3 and min(outline["minimum"]) == -0.3
    assert "waveform" not in analysis.result


def test_the_measurements_are_the_same_whether_or_not_a_waveform_is_drawn(
    session_factory, add_job, make_worker, monkeypatch
):
    from app import worker as worker_module

    add_job()
    make_worker().process_next_job()
    monkeypatch.setattr(worker_module, "waveform_outline", lambda samples: None)
    add_job()
    make_worker().process_next_job()

    with_picture, without_picture = analyses(session_factory)
    assert with_picture.waveform is not None and without_picture.waveform is None
    ignored = {"analysisId", "jobId", "createdAt"}
    assert {k: v for k, v in with_picture.result.items() if k not in ignored} == {
        k: v for k, v in without_picture.result.items() if k not in ignored
    }
