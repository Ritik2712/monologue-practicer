"""What each kind of feedback is taken to mean: which setting it speaks for, if any."""

import pytest

from app import feedback, schemas
from app.calibration.registry import ADAPTIVE
from app.coaching.coach import Coach
from tests.conftest import make_recording, make_silence

NOW_ISH = None  # classify needs no clock


def recording(pauses=(0.6, 1.2), silences=((1.0, 1.4), (2.0, 2.1)), **overrides):
    """Three 4-second phrases with the given pauses between them and silences in the first."""
    phrases, start = [], 0.0
    for index in range(len(pauses) + 1):
        phrases.append((start, start + 4.0, f"phrase number {index + 1} has six words"))
        start += 4.0 + (pauses[index] if index < len(pauses) else 0.0)
    if silences is not None:
        overrides.setdefault("short_silences", [make_silence(a, b, "seg-1") for a, b in silences])
    return make_recording(phrases, **overrides)


def classify(body, category, target=None, at=None, coaching=None) -> feedback.Classified:
    request = schemas.FeedbackRequest(category=category, target_id=target, at_seconds=at)
    return feedback.classify(request, body, coaching)


def vote(found: feedback.Classified) -> tuple[str | None, int, float | None]:
    return found.setting, found.direction, found.evidence


# --- Labels: what a pause meant ----------------------------------------------------------


@pytest.mark.parametrize("category", ["pause_intentional", "pause_accidental"])
def test_calling_a_pause_intentional_or_accidental_speaks_for_no_setting(category):
    found = classify(recording(), category, "pause-2")

    assert vote(found) == (None, 0, None)
    assert (found.target_kind, found.slot) == ("pause", "pause:pause-2")
    assert found.features["pause_ms"] == 1200


# --- False pauses ------------------------------------------------------------------------


def test_a_short_false_pause_speaks_for_raising_the_minimum_pause():
    found = classify(recording(), "pause_false", "pause-1")

    assert vote(found) == ("min_pause_ms", 1, 600.0)
    # What was measured, and the settings it was measured with, travel with the report.
    assert found.features == {"pause_ms": 600, "min_pause_ms": 500}


def test_a_long_false_pause_changes_no_setting():
    """No minimum pause would explain away 1.2 s of "silence": the detector missed speech,
    and no setting that feedback may move would have made it hear it."""
    found = classify(recording(), "pause_false", "pause-2")

    assert vote(found) == (None, 0, None)
    assert found.features["no_vote"] == "missed_speech"


def test_a_wrongly_split_phrase_speaks_for_raising_the_minimum_pause():
    found = classify(recording(), "split_wrong", "pause-1")

    assert vote(found) == ("min_pause_ms", 1, 600.0)


def test_a_wrong_split_at_a_long_silence_changes_no_setting():
    """A real silence of 1.2 s always ends a phrase here; no setting is at fault."""
    found = classify(recording(), "split_wrong", "pause-2")

    assert vote(found) == (None, 0, None)
    assert found.features["no_vote"] == "long_pause"


# --- Missed pauses -----------------------------------------------------------------------


def test_a_missed_pause_where_a_short_silence_was_heard_speaks_for_lowering_the_minimum():
    found = classify(recording(), "pause_missed", "seg-1", at=1.2)

    assert vote(found) == ("min_pause_ms", -1, 400.0)
    assert found.features["silence_ms"] == 400
    assert found.features["silence_start_seconds"] == 1.0


def test_the_silence_nearest_the_marked_time_is_the_one_meant():
    body = recording(silences=((1.0, 1.3), (3.0, 3.45)))

    assert classify(body, "pause_missed", "seg-1", at=3.1).evidence == 450.0
    assert classify(body, "pause_missed", "seg-1", at=0.8).evidence == 300.0


def test_a_missed_pause_where_no_silence_was_heard_changes_no_setting():
    found = classify(recording(), "pause_missed", "seg-1", at=3.4)

    assert vote(found) == (None, 0, None)
    assert (found.features["silence_ms"], found.features["no_vote"]) == (None, "no_silence")


def test_a_silence_shorter_than_any_pause_could_be_changes_no_setting():
    found = classify(recording(), "pause_missed", "seg-1", at=2.05)

    assert vote(found) == (None, 0, None)
    assert (found.features["no_vote"], found.features["silence_ms"]) == ("too_short", 100)


def test_a_missed_pause_without_a_position_changes_no_setting():
    found = classify(recording(), "pause_missed", "seg-1")

    assert vote(found) == (None, 0, None)
    assert found.features["no_vote"] == "no_position"
    assert found.slot == "missed:seg-1@?"


def test_a_result_from_before_silences_were_kept_cannot_back_a_report():
    found = classify(recording(silences=None), "pause_missed", "seg-1", at=1.2)

    assert vote(found) == (None, 0, None)
    assert found.features["no_vote"] == "not_recorded"


def test_one_silence_can_be_reported_only_once_however_the_time_is_marked():
    """The same silence marked at three slightly different times is still one report."""
    body = recording()

    slots = {classify(body, "pause_missed", "seg-1", at=at).slot for at in (1.05, 1.2, 1.38)}

    assert slots == {"missed:seg-1@1.00"}


def test_a_silence_in_another_phrase_is_not_mistaken_for_this_one():
    body = recording(short_silences=[make_silence(4.7, 5.1, "seg-2")])

    # 4.3 s is within half a second of that silence, but it belongs to the next phrase.
    found = classify(body, "pause_missed", "seg-1", at=4.3)
    assert (vote(found), found.features["no_vote"]) == ((None, 0, None), "no_silence")


def test_a_time_outside_the_phrase_is_refused():
    with pytest.raises(feedback.FeedbackError) as error:
        classify(recording(), "pause_missed", "seg-1", at=9.0)

    assert (error.value.status, error.value.code) == (422, "outside_target")


def test_two_missed_pauses_in_one_phrase_are_kept_apart():
    body = recording(silences=((1.0, 1.4), (3.0, 3.4)))

    first = classify(body, "pause_missed", "seg-1", at=1.2)
    second = classify(body, "pause_missed", "seg-1", at=3.2)

    assert first.slot != second.slot


# --- WPM and transcript ------------------------------------------------------------------


@pytest.mark.parametrize("category", ["wpm_too_high", "wpm_too_low"])
def test_a_wpm_report_speaks_for_no_setting(category):
    whole = classify(recording(), category)
    phrase = classify(recording(), category, "seg-2")

    assert vote(whole) == vote(phrase) == (None, 0, None)
    assert (whole.target_kind, whole.slot) == ("recording", "wpm:recording")
    assert phrase.features == {"words": 6, "seconds": 4.0, "wpm": 90.0}


def test_flagging_the_transcript_speaks_for_no_setting():
    found = classify(recording(), "transcript_wrong", "seg-3")

    assert vote(found) == (None, 0, None)
    assert found.slot == "transcript:seg-3"


# --- Ratings of corrections --------------------------------------------------------------


def rated(category: str) -> feedback.Classified:
    body = recording(speech_active_wpm=230.0)
    coaching = Coach(None).generate(body, now=body_time())
    pace = next(f for f in coaching.findings if f.kind == "pace")
    assert any(c.finding_id == pace.id for c in coaching.corrections)
    return classify(body, category, pace.id, coaching=coaching)


def body_time():
    from datetime import UTC, datetime

    return datetime(2026, 10, 11, tzinfo=UTC)


def test_not_useful_speaks_for_lowering_that_kind_of_correction_only():
    found = rated("coaching_not_useful")

    assert vote(found) == ("priority_pace", -1, None)
    assert found.features["finding_kind"] == "pace"
    assert found.features["source"] == "rules"


def test_useful_speaks_for_raising_it():
    assert vote(rated("coaching_useful")) == ("priority_pace", 1, None)


def test_a_rating_needs_a_correction_that_exists():
    body = recording()

    with pytest.raises(feedback.FeedbackError) as error:
        classify(
            body, "coaching_useful", "f99", coaching=Coach(None).generate(body, now=body_time())
        )

    assert error.value.code == "unknown_target"


# --- Across all of them ------------------------------------------------------------------


def test_no_feedback_ever_speaks_for_more_than_one_setting_or_an_unknown_one():
    body = recording(speech_active_wpm=230.0)
    coaching = Coach(None).generate(body, now=body_time())
    pace = next(f for f in coaching.findings if f.kind == "pace")
    cases = [
        ("pause_intentional", "pause-1", None),
        ("pause_accidental", "pause-1", None),
        ("pause_false", "pause-1", None),
        ("pause_false", "pause-2", None),
        ("split_wrong", "pause-1", None),
        ("split_wrong", "pause-2", None),
        ("pause_missed", "seg-1", 1.2),
        ("pause_missed", "seg-1", 3.4),
        ("pause_missed", "seg-1", None),
        ("wpm_too_high", None, None),
        ("wpm_too_low", "seg-1", None),
        ("transcript_wrong", "seg-1", None),
        ("coaching_useful", pace.id, None),
        ("coaching_not_useful", pace.id, None),
    ]
    for category, target, at in cases:
        found = classify(body, category, target, at, coaching)
        assert found.setting is None or found.setting in ADAPTIVE, category
        assert (found.setting is None) == (found.direction == 0), category


@pytest.mark.parametrize(
    "category, target",
    [("pause_false", "pause-9"), ("pause_missed", "seg-9"), ("wpm_too_low", "seg-9")],
)
def test_feedback_on_something_the_recording_does_not_have_is_refused(category, target):
    with pytest.raises(feedback.FeedbackError) as error:
        classify(recording(), category, target)

    assert (error.value.status, error.value.code) == (404, "unknown_target")
