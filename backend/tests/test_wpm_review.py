"""The review shown when the user says a WPM figure looks wrong."""

from app import schemas
from app.wpm_review import review
from tests.conftest import make_recording, make_silence
from tests.test_feedback import recording


def checks(result: schemas.WpmReview) -> dict[str, schemas.WpmCheck]:
    return {check.label: check for check in result.checks}


def test_the_review_shows_the_arithmetic_behind_a_phrase():
    result = review(recording(), "seg-1", "high")

    assert (result.target, result.words, result.speaking_seconds, result.wpm) == (
        "Segment 1",
        6,
        4.0,
        90.0,
    )
    assert result.formula == "6 words ÷ 4.00 s of speaking × 60 = 90.0 WPM."


def test_too_high_points_at_extra_words_and_at_speech_lost_inside_a_pause():
    found = checks(review(recording(), "seg-2", "high"))

    assert "one word heard as two, makes the WPM too high" in found["The words"].text
    assert found["The words"].action == "correct_transcript"
    time = found["The speaking time"]
    assert "a pause of 0.60 s before it and a pause of 1.20 s after it" in time.text
    assert time.action == "report_false_pause"


def test_too_low_points_at_dropped_words_and_at_silences_counted_as_speaking():
    found = checks(review(recording(), "seg-1", "low"))

    assert "two words heard as one, makes the WPM too low" in found["The words"].text
    time = found["The speaking time"]
    assert "2 silences too short to count as a pause, 0.50 s in all" in time.text
    assert time.action == "report_missed_pause"


def test_a_phrase_with_nothing_to_report_offers_no_action():
    low = checks(review(recording(), "seg-2", "low"))["The speaking time"]
    high = checks(review(recording(pauses=()), "seg-1", "high"))["The speaking time"]

    assert (low.action, "No silence was detected inside it" in low.text) == (None, True)
    assert (high.action, high.text.endswith("No pause borders it.")) == (None, True)


def test_words_the_recogniser_was_unsure_of_are_quoted():
    body = recording()
    for word in body.words[:2]:
        word.confidence = 0.3

    words = checks(review(body, "seg-1", "high"))["The words"]

    assert "was unsure of 2 of them: “phrase”, “number”." in words.text


def test_a_short_or_flagged_phrase_is_explained():
    body = recording()
    body.segments[0].flags = ["few_words", "wpm_outlier"]

    found = checks(review(body, "seg-1", "high"))

    assert (
        "one word more or less moves the WPM a long way"
        in found["How much there is to measure"].text
    )
    assert "above 180 WPM" in found["Flagged for review"].text
    assert "was not changed" in found["Flagged for review"].text


def test_the_whole_recording_is_reviewed_when_no_phrase_is_named():
    body = make_recording(
        [(0.0, 4.0, "one two three four five six"), (5.0, 9.0, "seven eight nine ten")],
        total_word_count=10,
        speech_active_seconds=8.0,
        speech_active_wpm=75.0,
        whole_clip_wpm=63.2,
        short_silences=[make_silence(1.0, 1.3, "seg-1")],
    )

    result = review(body, None, "low")

    assert (result.target, result.words, result.wpm) == ("The whole recording", 10, 75.0)
    assert result.formula == "10 words ÷ 8.00 s of speaking × 60 = 75.0 WPM."
    found = checks(result)
    assert found["The speaking time"].text.startswith(
        "8.00 s of the recording counted as speaking; 1 pause, 1.00 s in all, were left out"
    )
    assert found["The speaking time"].action == "report_missed_pause"
    assert "comes to 63.2 WPM" in found["Which WPM this is"].text


def test_a_result_from_before_silences_were_kept_says_so():
    time = checks(review(recording(silences=None), "seg-1", "low"))["The speaking time"]

    assert "were not recorded for this result" in time.text
    assert time.action is None


def test_reviewing_changes_nothing():
    body = recording()
    before = body.model_dump()

    review(body, "seg-1", "high")
    review(body, None, "low")

    assert body.model_dump() == before


def test_word_timing_is_always_part_of_the_review():
    found = checks(review(recording(), "seg-1", "high"))

    assert found["Word timing"].text == "Every word's timing falls inside this phrase."


def test_a_word_timed_outside_its_phrase_is_pointed_out():
    """The recogniser put "words" 0.4 s after the phrase ended, inside the pause."""
    body = recording()
    stray = [w for w in body.words if w.segment_id == "seg-1"][-1]
    stray.start_seconds, stray.end_seconds = 4.3, 4.5

    timing = checks(review(body, "seg-1", "low"))["Word timing"]
    whole = checks(review(body, None, "low"))["Word timing"]

    assert timing.text.startswith(
        "1 of the 6 words was timed by the recogniser outside this phrase and counted in the "
        "nearest one: “words”."
    )
    assert whole.text.startswith("1 of the 18 words was timed by the recogniser outside a phrase")


def test_a_recording_wide_doubt_about_timing_is_added_to_it():
    timing = schemas.AnalysisWarning(code="word_timing_uncertain", message="Timings off.")

    text = checks(review(recording(warnings=[timing]), "seg-1", "high"))["Word timing"].text

    assert "many word timings did not line up" in text
