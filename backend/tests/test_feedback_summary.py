"""What the feedback adds up to: the facts code counts, and the notes the AI model picks out."""

import json

import pytest
from sqlalchemy import select

from app import feedback_summary, job_queue
from app.calibration.registry import DEFAULT_VALUES
from app.feedback_summary import Digest, SummaryUnavailable, build_digest, build_prompt
from app.llm import LlmError
from app.models import Job, StoredSummary
from tests.conftest import FakeChat
from tests.test_feedback import recording
from tests.test_feedback_api import SILENCES, give, values

ABOUT = feedback_summary.NOTE_ABOUT


def facts(session) -> list[str]:
    return [fact.text for fact in build_digest(session).facts]


def fact_about(session, start: str) -> str:
    return next(text for text in facts(session) if text.startswith(start))


def first_allowed(schema: dict) -> dict:
    """A well-behaved model answer: the first notes it is allowed to name."""
    allowed = schema["properties"]["notes"]
    return {"notes": allowed["items"]["enum"][: allowed["maxItems"]]}


def digest_of(*notes: str, about: str = ABOUT["pause_missed"]) -> Digest:
    """A digest with just these notes, for tests that are only about picking."""
    return Digest(len(notes), (), tuple((about, note) for note in notes), len(notes))


SIX_NOTES = (
    "music is loud under this part",
    "he stops for a beat here in the film",
    "I can hear the gap when I play it back",
    "there is a clear breath here",
    "short stop before the door line",
    "lost my place at this point",
)


@pytest.fixture
def some_feedback(client, clock, store_result):
    """Two takes and a reference, with a little of every kind of feedback, each with a note."""
    first = store_result(recording(silences=SILENCES))
    second = store_result(recording(silences=SILENCES))
    reference = store_result(recording(silences=SILENCES), role="reference", title="Clip")
    given = (
        (first, "pause_intentional", "pause-2", {"note": "I held this one on purpose"}),
        (first, "pause_false", "pause-1", {"note": "still speaking through this one"}),
        (first, "pause_missed", "seg-1", {"atSeconds": 0.7, "note": "a clear breath here"}),
        (second, "pause_missed", "seg-1", {"atSeconds": 0.7, "note": "I always stop here"}),
        (second, "pause_missed", "seg-2", {"note": "ok"}),
        (second, "wpm_too_high", None, {"note": "feels slower than this number"}),
        (reference, "split_wrong", "pause-1", {"note": "one line in the film"}),
    )
    for analysis_id, category, target, extra in given:
        give(client, analysis_id, category, target, **extra)
        # Notes are listed in the order they were written.
        clock.advance(seconds=1)
    return first, second, reference


# --- The facts ---------------------------------------------------------------------------


def test_with_no_feedback_there_is_nothing_to_say(session):
    digest = build_digest(session)

    assert (digest.feedback_count, digest.facts, digest.notes, digest.note_count) == (0, (), (), 0)


def test_the_facts_count_what_is_stored(session, some_feedback):
    digest = build_digest(session)

    assert digest.feedback_count == 7
    assert facts(session) == [
        (
            "7 pieces of feedback in all, on 3 recordings: 6 on your own takes and 1 on "
            "reference recordings."
        ),
        (
            "What it is about, largest group first: missed pauses (3), pauses that were not "
            "real (2), WPM figures (1), pauses you labelled (1)."
        ),
        (
            "Pauses you labelled intentional: 1. It lasted 1.2 s. A label changes how the "
            "coaching reads a pause, not its length."
        ),
        (
            "Detected pauses you reported as not real pauses: 2 (1 where speech carried on, 1 "
            "too short to split the phrase). They lasted 600 ms."
        ),
        (
            "Missed pauses you reported: 3. At 2 of them the detector had heard a silence "
            "lasting 400 ms, which was shorter than the minimum pause at the time and so was "
            "not counted as a pause. 1 could not be checked against what the detector heard."
        ),
        "WPM figures you said looked wrong: 1 too high and 0 too low. Saying so changes no figure.",
        "No setting has moved: each one is still at its default. The minimum pause is 500 ms.",
        "4 reports are waiting to count towards a setting.",
        (
            "1 report was saved but can count towards no setting, because what was measured "
            "there does not support a change."
        ),
        (
            "You wrote 7 notes with your feedback, on: missed pauses (3), pauses that were not "
            "real (2), WPM figures (1), pauses you labelled (1)."
        ),
    ]
    assert [fact.id for fact in digest.facts] == [f"f{n}" for n in range(1, 11)]


def test_each_label_has_a_fact_of_its_own_so_the_two_cannot_be_mixed_up(
    client, session, store_result
):
    analysis_id = store_result(recording(pauses=(0.6, 1.2, 0.75)))
    give(client, analysis_id, "pause_intentional", "pause-2")
    give(client, analysis_id, "pause_accidental", "pause-1")
    give(client, analysis_id, "pause_accidental", "pause-3")

    assert fact_about(session, "Pauses you labelled intentional").startswith(
        "Pauses you labelled intentional: 1. It lasted 1.2 s."
    )
    assert fact_about(session, "Pauses you labelled accidental").startswith(
        "Pauses you labelled accidental: 2. They lasted between 0.6 and 0.8 s."
    )


def test_a_setting_that_feedback_moved_is_stated_with_its_default(client, session, store_result):
    ids = [store_result(recording(silences=SILENCES)) for _ in range(2)]
    for analysis_id, at in ((ids[0], 0.7), (ids[1], 0.7), (ids[0], 1.7)):
        give(client, analysis_id, "pause_missed", "seg-1", atSeconds=at)

    assert (
        "Minimum pause is now 400 ms; the default is 500 ms. Your reports moved it, and it "
        "applies to recordings analysed from now on." in facts(session)
    )
    assert not any(text.startswith("No setting has moved") for text in facts(session))


def test_ratings_and_what_they_were_about_are_one_fact_not_two(client, session, store_result):
    ids = [store_result(recording(pauses=(0.2,) * 2, profile="thomas_shelby")) for _ in range(2)]
    for analysis_id in ids:
        coaching = client.get(f"/api/analyses/{analysis_id}").json()["coaching"]
        give(client, analysis_id, "coaching_not_useful", coaching["corrections"][0]["findingId"])

    rated = [text for text in facts(session) if "orrections" in text and "rated" in text]

    assert len(rated) == 1
    assert rated[0].startswith("Coaching corrections you rated: 0 useful and 2 not useful.")
    assert "The ones rated not useful were about: " in rated[0] and "(2)." in rated[0]


def test_notes_are_kept_word_for_word_with_what_they_were_about(session, some_feedback):
    digest = build_digest(session)

    assert digest.note_count == 7
    assert digest.notes[0] == (ABOUT["pause_intentional"], "I held this one on purpose")
    assert digest.notes[-1] == (ABOUT["split_wrong"], "one line in the film")


def test_only_the_most_recent_notes_are_listed_but_all_are_counted(client, session, store_result):
    for number in range(18):
        analysis_id = store_result(recording())
        give(client, analysis_id, "pause_false", "pause-1", note=f"note number {number}")

    digest = build_digest(session)

    assert (digest.note_count, len(digest.notes)) == (18, feedback_summary.MAX_NOTES)
    assert digest.notes[-1][1] == "note number 17"
    assert fact_about(session, "You wrote").startswith("You wrote 18 notes")


def test_the_fingerprint_follows_the_notes_and_nothing_else(client, session, some_feedback):
    before = build_digest(session).notes_fingerprint

    give(client, some_feedback[0], "wpm_too_low", "seg-1")
    unchanged = build_digest(session).notes_fingerprint
    give(client, some_feedback[0], "wpm_too_low", "seg-1", note="this line was rushed")

    assert unchanged == before
    assert build_digest(session).notes_fingerprint != before


# --- What the model is asked, and what is made of its answer ------------------------------


def test_the_model_is_shown_the_notes_and_nothing_else(session, some_feedback):
    llm = FakeChat(first_allowed)

    feedback_summary.pick(llm, build_digest(session))

    [(messages, schema)] = llm.calls
    shown = messages[1].content
    assert f'n1 (on {ABOUT["pause_intentional"]}): "I held this one on purpose"' in shown
    # No counts, no setting, no transcript, no file name, no recording ID.
    assert "pieces of feedback" not in shown and "500 ms" not in shown
    assert "phrase number" not in shown and some_feedback[0] not in shown
    # It may name only notes it was offered, and exactly three of them.
    names = schema["properties"]["notes"]
    assert (names["minItems"], names["maxItems"]) == (3, 3)
    assert names["items"]["enum"] == ["n1", "n2", "n3", "n4", "n5", "n6"]


def test_a_note_that_says_nothing_is_never_offered(session, some_feedback):
    digest = build_digest(session)
    prompt = build_prompt(digest)

    assert [note for _, note in digest.notes].count("ok") == 1
    assert '"ok"' not in prompt.messages[1].content
    assert len(prompt.names) == len(digest.notes) - 1
    assert all(digest.notes[position][1] != "ok" for position in prompt.names.values())


def test_the_task_names_the_subject_most_notes_are_on_so_the_model_need_not_count():
    notes = (
        (ABOUT["wpm_too_high"], "feels slower than this"),
        (ABOUT["pause_missed"], "a clear breath here"),
        (ABOUT["pause_missed"], "I always stop here"),
        (ABOUT["pause_missed"], "he stops for a beat"),
        (ABOUT["pause_accidental"], "lost my place here"),
    )
    task = build_prompt(Digest(5, (), notes, 5)).messages[1].content

    assert f"Most of the notes are on {ABOUT['pause_missed']}. Choose at least one" in task


def test_the_picked_notes_are_given_back_as_positions_most_telling_first():
    llm = FakeChat({"notes": ["n4", "n1", "n6"]})

    picked = feedback_summary.pick(llm, digest_of(*SIX_NOTES))

    assert picked.positions == (3, 0, 5)
    assert (picked.model, picked.seconds) == ("fake-llm", 1.5)


@pytest.mark.parametrize(
    ("answer", "positions"),
    [
        # Named twice counts once; two different notes are still a pick.
        ({"notes": ["n2", "n2", "n5"]}, (1, 4)),
        # A name that is not a note is passed over.
        ({"notes": ["n9", "n1", "n3"]}, (0, 2)),
        # More than asked for: only the first three are kept.
        ({"notes": ["n1", "n2", "n3", "n4"]}, (0, 1, 2)),
    ],
)
def test_an_untidy_answer_is_used_as_far_as_it_goes(answer, positions):
    digest = digest_of(*SIX_NOTES)

    assert feedback_summary.read_answer(json.dumps(answer), build_prompt(digest)) == positions


@pytest.mark.parametrize(
    "text",
    [
        "this is not JSON",
        '["n1", "n2"]',
        '{"notes": "n1"}',
        '{"notes": ["n1"]}',
        '{"notes": ["n1", "n1", "n1"]}',
        '{"notes": [1, 2, 3]}',
        '{"summary": "Your notes are mostly about pauses."}',
    ],
)
def test_an_answer_that_names_fewer_than_two_notes_is_no_pick(text):
    assert feedback_summary.read_answer(text, build_prompt(digest_of(*SIX_NOTES))) is None


def test_an_unreadable_answer_gets_one_more_try():
    llm = FakeChat("this is not JSON", {"notes": ["n1", "n2", "n3"]})

    picked = feedback_summary.pick(llm, digest_of(*SIX_NOTES))

    assert len(llm.calls) == 2
    assert picked.positions == (0, 1, 2)


@pytest.mark.parametrize(
    ("llm", "code"),
    [
        (None, "ai_off"),
        (FakeChat(model_status="not_running"), "not_running"),
        (FakeChat(LlmError("timeout", "Too slow.")), "timeout"),
        (FakeChat("this is not JSON"), "bad_answer"),
    ],
)
def test_no_pick_without_a_model_that_answers(llm, code):
    with pytest.raises(SummaryUnavailable) as raised:
        feedback_summary.pick(llm, digest_of(*SIX_NOTES))

    assert raised.value.code == code


def test_with_too_few_notes_the_model_is_not_asked():
    llm = FakeChat(first_allowed)

    with pytest.raises(SummaryUnavailable) as raised:
        # Six notes, but only four say enough to be offered.
        feedback_summary.pick(llm, digest_of(*SIX_NOTES[:4], "ok", "wrong"))

    assert raised.value.code == "too_few_notes"
    assert llm.calls == []


# --- Through the API and the worker ------------------------------------------------------


def test_the_facts_and_the_notes_are_there_without_asking_anyone(client, some_feedback):
    summary = client.get("/api/feedback-summary").json()

    assert (summary["feedbackCount"], summary["noteCount"], summary["minNotes"]) == (7, 7, 5)
    assert summary["pickableNotes"] == 6
    assert summary["facts"][0]["text"].startswith("7 pieces of feedback in all")
    assert summary["notes"][0] == {
        "about": ABOUT["pause_intentional"],
        "text": "I held this one on purpose",
    }
    assert (summary["picked"], summary["job"]) == (None, None)


def test_asking_queues_a_job_and_asking_again_returns_the_same_one(client, some_feedback):
    first = client.post("/api/feedback-summary")
    second = client.post("/api/feedback-summary")

    assert (first.status_code, second.status_code) == (202, 200)
    job = first.json()["job"]
    assert (job["kind"], job["status"], job["analysisId"]) == ("summary", "queued", None)
    assert second.json()["job"]["jobId"] == job["jobId"]


def test_with_too_few_notes_there_is_nothing_to_ask(client, store_result):
    analysis_id = store_result(recording())
    give(client, analysis_id, "pause_false", "pause-1", note="still speaking here")
    give(client, analysis_id, "pause_intentional", "pause-2", note="held on purpose")

    refused = client.post("/api/feedback-summary")

    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "too_few_notes")


def test_the_worker_stores_the_picked_notes_word_for_word_and_no_setting_moves(
    client, make_worker, some_feedback
):
    before = client.get("/api/calibration").json()
    client.post("/api/feedback-summary")

    assert make_worker(FakeChat({"notes": ["n3", "n6", "n1"]})).process_next_job() is True

    summary = client.get("/api/feedback-summary").json()
    picked = summary["picked"]
    assert summary["job"] is None
    assert [note["text"] for note in picked["notes"]] == [
        "a clear breath here",
        # "ok" was never offered, so n6 is the seventh note, not the sixth.
        "one line in the film",
        "I held this one on purpose",
    ]
    assert picked["notes"][0]["about"] == ABOUT["pause_missed"]
    assert (picked["model"], picked["noteCount"], picked["stale"]) == ("fake-llm", 7, False)
    after = client.get("/api/calibration").json()
    assert (after["version"], values(after)) == (before["version"], DEFAULT_VALUES)
    assert after == before


def test_a_pick_goes_out_of_date_when_the_notes_change_but_not_when_only_counts_do(
    client, make_worker, some_feedback
):
    client.post("/api/feedback-summary")
    make_worker(FakeChat(first_allowed)).process_next_job()

    give(client, some_feedback[0], "wpm_too_low", "seg-1")
    still_good = client.get("/api/feedback-summary").json()
    give(client, some_feedback[0], "wpm_too_low", "seg-1", note="this line was rushed")
    stale = client.get("/api/feedback-summary").json()

    assert (still_good["feedbackCount"], still_good["picked"]["stale"]) == (8, False)
    assert (stale["noteCount"], stale["picked"]["stale"]) == (8, True)
    # What was picked is shown as it read when it was picked.
    assert stale["picked"]["notes"] == still_good["picked"]["notes"]


def test_a_new_pick_replaces_the_one_before(client, session, make_worker, some_feedback):
    for names in (["n1", "n2", "n3"], ["n4", "n5", "n6"]):
        client.post("/api/feedback-summary")
        make_worker(FakeChat({"notes": names})).process_next_job()

    picked = client.get("/api/feedback-summary").json()["picked"]
    assert picked["notes"][0]["text"] == "I always stop here"
    assert len(session.execute(select(StoredSummary)).scalars().all()) == 1


def test_without_the_model_the_job_fails_and_says_why(client, make_worker, some_feedback):
    client.post("/api/feedback-summary")

    make_worker(FakeChat(model_status="not_running")).process_next_job()

    summary = client.get("/api/feedback-summary").json()
    assert summary["picked"] is None
    assert (summary["job"]["status"], summary["job"]["error"]["code"]) == ("failed", "not_running")
    assert summary["job"]["canRetry"] is False
    # The facts and the notes never depended on the model.
    assert len(summary["facts"]) > 3 and len(summary["notes"]) == 7


def test_a_failure_is_no_longer_shown_once_a_later_pick_exists(
    client, clock, make_worker, some_feedback
):
    client.post("/api/feedback-summary")
    make_worker(FakeChat(model_status="not_running")).process_next_job()
    clock.advance(seconds=5)
    client.post("/api/feedback-summary")
    clock.advance(seconds=5)

    make_worker(FakeChat(first_allowed)).process_next_job()

    summary = client.get("/api/feedback-summary").json()
    assert summary["job"] is None
    assert len(summary["picked"]["notes"]) == 3


def test_a_summary_job_can_be_cancelled_before_it_starts(client, make_worker, some_feedback):
    job = client.post("/api/feedback-summary").json()["job"]

    cancelled = client.post(f"/api/jobs/{job['jobId']}/cancel").json()

    assert cancelled["status"] == "cancelled"
    assert make_worker(FakeChat(first_allowed)).process_next_job() is False
    summary = client.get("/api/feedback-summary").json()
    assert (summary["picked"], summary["job"]) == (None, None)


def test_a_summary_cancelled_while_the_model_answers_stores_nothing(
    client, session_factory, clock, make_worker, some_feedback
):
    job_id = client.post("/api/feedback-summary").json()["job"]["jobId"]
    llm = FakeChat(first_allowed)

    def cancel_now() -> None:
        with session_factory() as session:
            job_queue.request_cancel(session, job_id, clock())

    llm.during = cancel_now
    make_worker(llm).process_next_job()

    with session_factory() as session:
        assert session.get(Job, job_id).status == "cancelled"
        assert session.get(StoredSummary, 1) is None


def test_a_summary_job_left_running_by_a_dead_worker_is_queued_again(
    client, session_factory, clock, some_feedback
):
    job_id = client.post("/api/feedback-summary").json()["job"]["jobId"]
    with session_factory() as session:
        job_queue.claim_next_job(session, clock())
        clock.advance(minutes=5)

        requeued, ended = job_queue.recover_orphaned_jobs(
            session, clock(), stale_after_seconds=30, max_attempts=2
        )

        assert (requeued, ended) == (1, 0)
        assert session.get(Job, job_id).status == "queued"


def test_deleting_the_recordings_takes_what_was_said_about_them_off_the_screen(
    client, make_worker, some_feedback
):
    client.post("/api/feedback-summary")
    make_worker(FakeChat(first_allowed)).process_next_job()

    client.delete("/api/analyses")
    client.delete("/api/analyses?role=reference")

    summary = client.get("/api/feedback-summary").json()
    assert (summary["feedbackCount"], summary["facts"], summary["notes"]) == (0, [], [])
    assert summary["picked"] is None
