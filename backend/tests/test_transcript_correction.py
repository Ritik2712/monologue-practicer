"""A corrected transcript: what is worked out again, and what stays exactly as it was."""

import pytest

from app import schemas
from app.transcript_correction import correct_transcript, retime
from tests.conftest import make_recording, metric

# Three phrases of 4 seconds each. 12, 8 and 10 words: 180, 120 and 150 WPM.
PHRASES = [
    (0.0, 4.0, "you clearly do not know who you are talking to right now"),
    (5.0, 9.0, "so let me clue you in on this"),
    (10.0, 14.0, "I am not in danger Skyler I am the danger"),
]
MEASURED = {
    "total_word_count": metric(30.0, "words"),
    "speech_active_seconds": metric(12.0, "seconds"),
    "speech_active_wpm": metric(150.0, "words/minute"),
    "whole_clip_wpm": metric(124.1, "words/minute"),
    "typical_segment_wpm": metric(150.0, "words/minute"),
    "duration_seconds": 14.5,
}


def take(**overrides) -> schemas.AnalysisBody:
    return make_recording(PHRASES, **{**MEASURED, **overrides})


def segment(body: schemas.AnalysisBody, segment_id: str) -> schemas.SpeechSegment:
    return next(s for s in body.segments if s.id == segment_id)


# --- WPM comes from the words and the time, never from a factor ---------------------------


def test_segment_wpm_is_the_corrected_word_count_over_the_phrases_own_length():
    """The recogniser heard 12 words in 4 s (180 WPM). Really there were 8: 120 WPM."""
    body = take()
    said = "you clearly don't know who you're talking to"  # 8 words

    corrected, changed = correct_transcript(body, {"seg-1": said})

    first = segment(corrected, "seg-1")
    assert changed == ["seg-1"]
    assert (first.word_count, first.segment_wpm) == (8, 120.0)
    assert first.segment_wpm == pytest.approx(8 / (4.0 / 60))
    assert first.transcript == said
    # The length of the phrase was measured from the sound and has not moved.
    assert (first.start_seconds, first.end_seconds, first.speech_active_seconds) == (0.0, 4.0, 4.0)


def test_the_whole_recording_rates_are_recounted_from_the_new_total():
    corrected, _ = correct_transcript(take(), {"seg-1": "you clearly do not know who"})  # 6

    metrics = corrected.metrics
    assert metrics.total_word_count.value == 24
    assert metrics.speech_active_wpm.value == pytest.approx(24 / (12.0 / 60))  # 120.0
    assert metrics.whole_clip_wpm.value == pytest.approx(24 / (14.5 / 60), abs=0.05)  # 99.3
    assert metrics.speech_active_seconds.value == 12.0


def test_no_correction_factor_is_involved():
    """Scaling the old figures by one ratio would give every phrase the same change. Here
    only the corrected phrase changes, and by exactly its own words over its own time."""
    body = take()

    corrected, _ = correct_transcript(body, {"seg-1": "you clearly do not know who"})

    wpm = {s.id: s.segment_wpm for s in corrected.segments}
    assert wpm == {"seg-1": 90.0, "seg-2": 120.0, "seg-3": 150.0}
    ratio = corrected.metrics.speech_active_wpm.value / body.metrics.speech_active_wpm.value
    assert wpm["seg-1"] / 180.0 != pytest.approx(ratio)


def test_phrases_that_were_not_corrected_keep_every_figure_they_had():
    body = take()

    corrected, _ = correct_transcript(body, {"seg-1": "you clearly do not know"})

    for segment_id in ("seg-2", "seg-3"):
        before, after = segment(body, segment_id), segment(corrected, segment_id)
        assert after.model_dump(exclude={"pace_vs_typical"}) == before.model_dump(
            exclude={"pace_vs_typical"}
        )
    untouched_words = [w for w in corrected.words if w.segment_id != "seg-1"]
    assert untouched_words == [w for w in body.words if w.segment_id != "seg-1"]


def test_everything_measured_from_the_sound_stays_exactly_as_it_was():
    body = take()

    corrected, _ = correct_transcript(body, {"seg-2": "so let me clue you in"})

    assert corrected.pauses == body.pauses
    assert corrected.energy_timeline == body.energy_timeline
    assert corrected.settings == body.settings
    assert corrected.duration_seconds == body.duration_seconds
    acoustic = (
        "speech_active_seconds",
        "pause_count",
        "total_pause_seconds",
        "median_pause_seconds",
        "longest_pause_seconds",
        "pause_ratio",
        "energy_variation",
        "pitch_median_hz",
        "pitch_variation_semitones",
        "signal_to_noise",
    )
    for name in acoustic:
        assert getattr(corrected.metrics, name) == getattr(body.metrics, name), name
    for before, after in zip(body.segments, corrected.segments, strict=True):
        assert (after.mean_energy_db, after.median_pitch_hz) == (
            before.mean_energy_db,
            before.median_pitch_hz,
        )


def test_the_typical_pace_and_each_phrases_standing_against_it_are_worked_out_again():
    """Halving the words of the fast phrase changes which phrases count as off the pace."""
    corrected, _ = correct_transcript(take(), {"seg-1": "you clearly do not know who"})

    assert corrected.metrics.typical_segment_wpm.value == 120.0  # median of 90, 120, 150
    assert [s.pace_vs_typical for s in corrected.segments] == ["slower", "typical", "faster"]
    assert corrected.metrics.pace_min_wpm.value == 90.0
    assert corrected.metrics.pace_max_wpm.value == 150.0


def test_the_stored_result_that_was_corrected_is_not_modified():
    body = take()
    before = body.model_dump()

    correct_transcript(body, {"seg-1": "something else entirely"})

    assert body.model_dump() == before


# --- What counts as a change -------------------------------------------------------------


def test_the_same_words_with_different_spacing_are_not_a_correction():
    body = take()

    corrected, changed = correct_transcript(body, {"seg-2": "  so let me  clue you in on this "})

    assert changed == []
    assert corrected is body


def test_a_phrase_can_be_corrected_to_nothing_at_all():
    """The recogniser sometimes invents words over a noise. Nothing was really said."""
    corrected, changed = correct_transcript(take(), {"seg-2": ""})

    second = segment(corrected, "seg-2")
    assert changed == ["seg-2"]
    assert (second.word_count, second.segment_wpm, second.reliable) == (0, None, False)
    assert second.flags == ["no_words"]
    assert corrected.metrics.total_word_count.value == 22


def test_a_short_correction_is_marked_as_too_few_words_to_trust():
    corrected, _ = correct_transcript(take(), {"seg-2": "so there"})

    second = segment(corrected, "seg-2")
    assert (second.word_count, second.segment_wpm) == (2, 30.0)
    assert (second.reliable, second.flags, second.quality) == (False, ["few_words"], "estimated")


# --- Word times --------------------------------------------------------------------------


def old_words(*timed: tuple[str, float, float]) -> list[schemas.WordTiming]:
    return [
        schemas.WordTiming(
            text=text, start_seconds=start, end_seconds=end, confidence=0.8, segment_id="seg-1"
        )
        for text, start, end in timed
    ]


def test_words_that_did_not_change_keep_the_recognisers_times_and_confidence():
    heard = old_words(("I", 0.0, 0.5), ("am", 0.5, 1.0), ("the", 1.0, 1.5), ("danger", 1.5, 2.0))

    words = retime(heard, ["I", "am", "the", "danger"], 0.0, 2.0)

    assert [(w.text, w.start, w.end, w.probability) for w in words] == [
        ("I", 0.0, 0.5, 0.8),
        ("am", 0.5, 1.0, 0.8),
        ("the", 1.0, 1.5, 0.8),
        ("danger", 1.5, 2.0, 0.8),
    ]


def test_new_words_are_spread_across_the_gap_they_sit_in_and_carry_no_confidence():
    """ "the one" was heard as a single word "theon" between 1.0 and 2.0 s."""
    heard = old_words(("I", 0.0, 0.5), ("am", 0.5, 1.0), ("theon", 1.0, 2.0), ("who", 2.0, 2.5))

    words = retime(heard, ["I", "am", "the", "one", "who"], 0.0, 2.5)

    assert [(w.text, w.start, w.end, w.probability) for w in words] == [
        ("I", 0.0, 0.5, 0.8),
        ("am", 0.5, 1.0, 0.8),
        ("the", 1.0, 1.5, None),
        ("one", 1.5, 2.0, None),
        ("who", 2.0, 2.5, 0.8),
    ]


def test_spelling_and_punctuation_fixes_keep_the_time_but_take_the_users_spelling():
    heard = old_words(("skylar", 1.0, 1.6), ("मैं", 1.6, 2.0))

    words = retime(heard, ["Skylar,", "में"], 1.0, 2.0)

    assert [(w.text, w.start, w.end) for w in words] == [("Skylar,", 1.0, 1.6), ("में", 1.6, 2.0)]


def test_words_added_at_either_end_are_fitted_inside_the_phrase():
    heard = old_words(("know", 1.0, 1.5))

    words = retime(heard, ["you", "know", "who"], 0.4, 2.3)

    assert [(w.text, w.start, w.end) for w in words] == [
        ("you", 0.4, 1.0),
        ("know", 1.0, 1.5),
        ("who", 1.5, 2.3),
    ]


def test_a_phrase_with_no_recognised_words_gets_evenly_spaced_ones():
    words = retime([], ["one", "two", "three", "four"], 2.0, 4.0)

    assert [(w.start, w.end) for w in words] == [(2.0, 2.5), (2.5, 3.0), (3.0, 3.5), (3.5, 4.0)]
    assert all(w.probability is None for w in words)


# --- Things that rest on the words -------------------------------------------------------


def test_hesitation_sounds_are_counted_again_from_the_corrected_words():
    corrected, _ = correct_transcript(take(), {"seg-2": "so um let me uh clue you in"})

    assert [h.text for h in corrected.hesitations] == ["um", "uh"]
    assert corrected.metrics.filler_word_count.value == 2
    assert all(5.0 <= h.start_seconds <= 9.0 for h in corrected.hesitations)


def test_an_emphasis_candidate_survives_only_if_its_word_is_still_there():
    body = take()
    danger = next(w for w in body.words if w.text == "danger")
    clue = next(w for w in body.words if w.text == "clue")
    candidates = [
        schemas.EmphasisCandidate(
            text=word.text,
            start_seconds=word.start_seconds,
            end_seconds=word.end_seconds,
            segment_id=word.segment_id,
            reasons=["louder"],
            energy_delta_db=6.0,
            pitch_delta_semitones=None,
        )
        for word in (clue, danger)
    ]
    body = take(emphasis_candidates=candidates)

    corrected, _ = correct_transcript(body, {"seg-2": "so let me tell you about this"})

    assert [c.text for c in corrected.emphasis_candidates] == ["danger"]


def test_the_result_says_it_was_corrected_and_drops_doubts_the_correction_removed():
    doubt = schemas.AnalysisWarning(code="uncertain_transcription", message="Unsure.")
    noise = schemas.AnalysisWarning(code="noisy", message="Noisy.")
    body = take(warnings=[doubt, noise])

    corrected, _ = correct_transcript(body, {"seg-1": "you clearly do not know"})

    assert [w.code for w in corrected.warnings] == ["noisy", "transcript_corrected"]
    assert "worked out again" in corrected.warnings[-1].message


def test_a_doubt_about_word_timing_outlives_a_correction():
    """How well the recogniser's times lined up is a fact about the original run."""
    timing = schemas.AnalysisWarning(code="word_timing_uncertain", message="Timings off.")

    corrected, _ = correct_transcript(take(warnings=[timing]), {"seg-1": "you clearly do not"})

    assert [w.code for w in corrected.warnings] == ["word_timing_uncertain", "transcript_corrected"]
    assert corrected.metrics.speech_active_wpm.quality == "estimated"


def test_the_settings_the_result_was_made_with_decide_what_is_reliable():
    """This result was made when a phrase needed 5 words for a trusted WPM, not today's 3."""
    body = take(settings={"min_segment_words": 5})

    corrected, _ = correct_transcript(body, {"seg-2": "so let me clue"})

    assert segment(corrected, "seg-2").flags == ["few_words"]
