"""Job status changes, straight against the queue functions (no HTTP, no pipeline)."""

import pytest

from app import job_queue, uploads
from app.models import Job


def get(session_factory, job_id: str) -> Job:
    with session_factory() as session:
        return session.get(Job, job_id)


def claim(session_factory, clock) -> Job | None:
    with session_factory() as session:
        return job_queue.claim_next_job(session, clock())


def status(session_factory, data_dir, clock, job_id: str):
    with session_factory() as session:
        return job_queue.to_status(session, session.get(Job, job_id), clock(), data_dir)


def fail(session_factory, data_dir, clock, job_id: str, *, retryable: bool) -> None:
    with session_factory() as session:
        job_queue.fail_job(
            session, job_id, code="boom", message="It broke.", retryable=retryable,
            now=clock(), data_dir=data_dir,
        )  # fmt: skip


# --- Queueing and claiming ---------------------------------------------------------------


def test_a_new_job_is_queued_and_nothing_has_run_yet(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    job = get(session_factory, job_id)
    assert job.status == "queued"
    assert job.attempt == 0
    assert job.started_at is None
    assert uploads.audio_exists(job.audio_path, data_dir)

    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "queued"
    assert state.stage is None
    assert state.queue_position == 0
    assert state.can_cancel
    assert not state.can_retry
    assert not state.worker_alive


def test_jobs_are_claimed_oldest_first_and_one_at_a_time(session_factory, clock, add_job):
    first, second, third = add_job(), add_job(), add_job()

    assert claim(session_factory, clock).id == first
    assert claim(session_factory, clock).id == second
    assert claim(session_factory, clock).id == third
    assert claim(session_factory, clock) is None


def test_claiming_marks_the_job_running_and_counts_the_attempt(session_factory, clock, add_job):
    add_job()
    claimed = claim(session_factory, clock)
    assert claimed.status == "running"
    assert claimed.attempt == 1
    assert claimed.started_at == clock()
    assert claimed.heartbeat_at == clock()


def test_queue_position_counts_only_jobs_waiting_ahead(session_factory, data_dir, clock, add_job):
    first, second, third = add_job(), add_job(), add_job()
    positions = [status(session_factory, data_dir, clock, j).queue_position for j in (first, second, third)]  # fmt: skip
    assert positions == [0, 1, 2]

    claim(session_factory, clock)  # the first one starts running
    assert status(session_factory, data_dir, clock, first).queue_position is None
    assert status(session_factory, data_dir, clock, third).queue_position == 1


def test_the_same_idempotency_key_cannot_create_a_second_job(session_factory, clock, add_job):
    original = add_job(idempotency_key="click-1")
    with pytest.raises(job_queue.DuplicateJob) as raised:
        add_job(idempotency_key="click-1")
    assert raised.value.existing.id == original

    with session_factory() as session:
        assert job_queue.find_by_idempotency_key(session, "click-1").id == original
        assert job_queue.find_by_idempotency_key(session, "other") is None
        assert job_queue.find_by_idempotency_key(session, None) is None


def test_jobs_without_a_key_never_count_as_duplicates(add_job):
    assert add_job() != add_job()


# --- Stages and status -------------------------------------------------------------------


def test_the_stage_is_reported_only_while_running(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    claim(session_factory, clock)
    with session_factory() as session:
        job_queue.set_stage(session, job_id, "transcribing", clock())

    assert status(session_factory, data_dir, clock, job_id).stage == "transcribing"

    fail(session_factory, data_dir, clock, job_id, retryable=False)
    assert status(session_factory, data_dir, clock, job_id).stage is None


# --- Cancelling --------------------------------------------------------------------------


def test_cancelling_a_queued_job_is_immediate_and_removes_its_audio(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    audio_path = get(session_factory, job_id).audio_path

    with session_factory() as session:
        job = job_queue.request_cancel(session, job_id, clock(), data_dir)

    assert job.status == "cancelled"
    assert job.finished_at == clock()
    assert job.audio_path is None
    assert not uploads.audio_exists(audio_path, data_dir)
    assert claim(session_factory, clock) is None


def test_cancelling_a_running_job_is_only_a_request_until_the_worker_stops(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    audio_path = get(session_factory, job_id).audio_path

    with session_factory() as session:
        job_queue.request_cancel(session, job_id, clock(), data_dir)

    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "running"  # not claimed to be cancelled yet
    assert state.cancel_requested
    assert not state.can_cancel
    assert uploads.audio_exists(audio_path, data_dir)
    with session_factory() as session:
        assert job_queue.is_cancel_requested(session, job_id)

    with session_factory() as session:
        job_queue.finish_cancelled(session, job_id, clock(), data_dir)

    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "cancelled"
    assert not state.cancel_requested
    assert not uploads.audio_exists(audio_path, data_dir)


def test_cancelling_twice_is_harmless(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    with session_factory() as session:
        job_queue.request_cancel(session, job_id, clock(), data_dir)
        assert job_queue.request_cancel(session, job_id, clock(), data_dir).status == "cancelled"


def test_a_finished_job_cannot_be_cancelled(session_factory, data_dir, clock, add_job, make_worker):
    job_id = add_job()
    make_worker().process_next_job()
    with session_factory() as session, pytest.raises(job_queue.JobConflict) as raised:
        job_queue.request_cancel(session, job_id, clock(), data_dir)
    assert raised.value.code == "already_finished"


def test_cancelling_an_unknown_job_is_a_lookup_error(session, data_dir, clock):
    with pytest.raises(LookupError):
        job_queue.request_cancel(session, "nope", clock(), data_dir)


# --- Failing and retrying ----------------------------------------------------------------


def test_a_retryable_failure_keeps_the_audio_so_retry_can_work(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    fail(session_factory, data_dir, clock, job_id, retryable=True)

    job = get(session_factory, job_id)
    assert job.status == "failed"
    assert uploads.audio_exists(job.audio_path, data_dir)
    state = status(session_factory, data_dir, clock, job_id)
    assert state.error.code == "boom"
    assert state.error.message == "It broke."
    assert state.error.retryable
    assert state.can_retry

    with session_factory() as session:
        job_queue.retry_job(session, job_id, clock(), data_dir)

    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "queued"
    assert state.error is None
    assert state.attempt == 0
    assert claim(session_factory, clock).id == job_id


def test_a_failure_that_would_repeat_deletes_the_audio_and_cannot_be_retried(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    audio_path = get(session_factory, job_id).audio_path
    fail(session_factory, data_dir, clock, job_id, retryable=False)

    assert not uploads.audio_exists(audio_path, data_dir)
    assert get(session_factory, job_id).audio_path is None
    state = status(session_factory, data_dir, clock, job_id)
    assert not state.can_retry
    assert not state.error.retryable

    with session_factory() as session, pytest.raises(job_queue.JobConflict) as raised:
        job_queue.retry_job(session, job_id, clock(), data_dir)
    assert raised.value.code == "not_retryable"


def test_retry_is_refused_once_the_kept_audio_is_gone(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    claim(session_factory, clock)
    fail(session_factory, data_dir, clock, job_id, retryable=True)
    uploads.delete_audio(get(session_factory, job_id).audio_path, data_dir)

    assert not status(session_factory, data_dir, clock, job_id).can_retry
    with session_factory() as session, pytest.raises(job_queue.JobConflict) as raised:
        job_queue.retry_job(session, job_id, clock(), data_dir)
    assert raised.value.code == "audio_gone"


def test_only_failed_jobs_can_be_retried(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    with session_factory() as session, pytest.raises(job_queue.JobConflict) as raised:
        job_queue.retry_job(session, job_id, clock(), data_dir)
    assert raised.value.code == "not_failed"


def test_discarding_a_failed_job_removes_the_audio_kept_for_retry(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    fail(session_factory, data_dir, clock, job_id, retryable=True)
    audio_path = get(session_factory, job_id).audio_path

    with session_factory() as session:
        job = job_queue.request_cancel(session, job_id, clock(), data_dir)

    assert job.status == "failed"
    assert not uploads.audio_exists(audio_path, data_dir)
    assert not status(session_factory, data_dir, clock, job_id).can_retry


def test_audio_kept_for_a_retry_expires(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    claim(session_factory, clock)
    fail(session_factory, data_dir, clock, job_id, retryable=True)
    audio_path = get(session_factory, job_id).audio_path

    clock.advance(hours=23)
    with session_factory() as session:
        assert job_queue.expire_failed_audio(session, clock(), 24, data_dir) == 0
    assert uploads.audio_exists(audio_path, data_dir)

    clock.advance(hours=2)
    with session_factory() as session:
        assert job_queue.expire_failed_audio(session, clock(), 24, data_dir) == 1
    assert not uploads.audio_exists(audio_path, data_dir)
    assert not status(session_factory, data_dir, clock, job_id).can_retry


# --- Recovering from a dead worker -------------------------------------------------------


def recover(session_factory, data_dir, clock, *, stale_after=30, max_attempts=2):
    with session_factory() as session:
        return job_queue.recover_orphaned_jobs(
            session, clock(), stale_after_seconds=stale_after, max_attempts=max_attempts,
            data_dir=data_dir,
        )  # fmt: skip


def test_a_job_whose_worker_died_goes_back_in_the_queue(session_factory, data_dir, clock, add_job):
    job_id = add_job()
    claim(session_factory, clock)

    clock.advance(seconds=10)
    assert recover(session_factory, data_dir, clock) == (0, 0)  # heartbeat still fresh

    clock.advance(seconds=30)
    assert recover(session_factory, data_dir, clock) == (1, 0)
    job = get(session_factory, job_id)
    assert job.status == "queued"
    assert job.stage is None
    assert uploads.audio_exists(job.audio_path, data_dir)


def test_a_heartbeat_keeps_a_long_job_from_being_treated_as_dead(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    for _ in range(10):
        clock.advance(seconds=20)
        with session_factory() as session:
            job_queue.touch_job(session, job_id, clock())
        assert recover(session_factory, data_dir, clock) == (0, 0)
    assert get(session_factory, job_id).status == "running"


def test_a_job_that_keeps_killing_the_worker_fails_instead_of_looping_forever(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    for expected in [(1, 0), (0, 1)]:
        claim(session_factory, clock)
        clock.advance(seconds=60)
        assert recover(session_factory, data_dir, clock) == expected

    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "failed"
    assert state.error.code == "worker_stopped"
    assert state.attempt == 2
    # The audio is still there, so the user can choose to try once more.
    assert state.can_retry


def test_a_cancel_requested_before_the_worker_died_is_honoured_on_recovery(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    audio_path = get(session_factory, job_id).audio_path
    with session_factory() as session:
        job_queue.request_cancel(session, job_id, clock(), data_dir)

    clock.advance(seconds=60)
    assert recover(session_factory, data_dir, clock) == (0, 1)
    assert get(session_factory, job_id).status == "cancelled"
    assert not uploads.audio_exists(audio_path, data_dir)


def test_an_orphan_without_audio_fails_and_cannot_be_retried(
    session_factory, data_dir, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    uploads.delete_audio(get(session_factory, job_id).audio_path, data_dir)

    clock.advance(seconds=60)
    assert recover(session_factory, data_dir, clock) == (0, 1)
    state = status(session_factory, data_dir, clock, job_id)
    assert state.status == "failed"
    assert not state.can_retry


def test_a_released_job_returns_to_the_queue_without_using_up_an_attempt(
    session_factory, clock, add_job
):
    job_id = add_job()
    claim(session_factory, clock)
    with session_factory() as session:
        job_queue.release_job(session, job_id, clock())

    job = get(session_factory, job_id)
    assert (job.status, job.attempt, job.started_at) == ("queued", 0, None)
    assert claim(session_factory, clock).attempt == 1


# --- Worker liveness ---------------------------------------------------------------------


def test_the_worker_counts_as_alive_only_while_it_keeps_reporting(session_factory, clock):
    def alive() -> bool:
        with session_factory() as session:
            return job_queue.worker_alive(session, clock())

    assert not alive()
    with session_factory() as session:
        job_queue.report_worker(
            session, pid=123, now=clock(), speech_model="small", speech_model_ready=True
        )
    assert alive()
    clock.advance(seconds=14)
    assert alive()
    clock.advance(seconds=2)
    assert not alive()
