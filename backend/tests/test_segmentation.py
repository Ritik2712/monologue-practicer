import pytest

from app.pipeline.segmentation import (
    SpeechRegion,
    Word,
    assign_words,
    build_segments,
    count_words,
    is_countable_word,
)
from app.pipeline.settings import DEFAULT_SETTINGS, AnalysisSettings


def regions(*spans: tuple[float, float]) -> list[SpeechRegion]:
    return [SpeechRegion(start, end) for start, end in spans]


def spans(segments) -> list[tuple[float, float]]:
    return [(segment.start, segment.end) for segment in segments]


def test_gaps_shorter_than_the_minimum_pause_stay_inside_one_segment():
    # Gaps of 0.2 s and 0.3 s are ordinary gaps between words, not pauses.
    segments, pauses = build_segments(regions((1.0, 2.0), (2.2, 3.0), (3.3, 4.0)), DEFAULT_SETTINGS)
    assert spans(segments) == [(1.0, 4.0)]
    assert pauses == []


def test_a_gap_of_exactly_the_minimum_is_a_pause_and_one_millisecond_less_is_not():
    at_threshold, pauses = build_segments(regions((0.0, 1.0), (1.5, 2.0)), DEFAULT_SETTINGS)
    assert spans(at_threshold) == [(0.0, 1.0), (1.5, 2.0)]
    assert [round(pause.duration, 3) for pause in pauses] == [0.5]

    just_under, pauses = build_segments(regions((0.0, 1.0), (1.499, 2.0)), DEFAULT_SETTINGS)
    assert spans(just_under) == [(0.0, 2.0)]
    assert pauses == []


def test_float_rounding_does_not_turn_a_half_second_gap_into_a_non_pause():
    # 0.1 + 0.2 style arithmetic: 2.3 - 1.8 is 0.49999999999999978 in floating point.
    segments, pauses = build_segments(regions((0.0, 1.8), (2.3, 3.0)), DEFAULT_SETTINGS)
    assert len(segments) == 2
    assert len(pauses) == 1


def test_pauses_are_classified_and_only_long_silences_start_a_new_section():
    segments, pauses = build_segments(
        regions((0.0, 2.0), (2.6, 4.0), (5.5, 7.0), (12.0, 14.0), (20.5, 22.0)), DEFAULT_SETTINGS
    )
    assert [pause.significance for pause in pauses] == ["short", "medium", "long", "long"]
    assert [round(pause.duration, 1) for pause in pauses] == [0.6, 1.5, 5.0, 6.5]
    assert [segment.section_index for segment in segments] == [0, 0, 0, 1, 2]


def test_a_long_silence_is_still_an_ordinary_measured_pause():
    # The 5 s boundary only adds a label; it does not replace the 0.5 s pause detector.
    _, pauses = build_segments(regions((0.0, 1.0), (1.7, 2.0), (8.0, 9.0)), DEFAULT_SETTINGS)
    assert [(pause.significance, round(pause.duration, 1)) for pause in pauses] == [
        ("short", 0.7),
        ("long", 6.0),
    ]


def test_silence_before_and_after_the_speech_is_not_a_pause():
    segments, pauses = build_segments(regions((3.0, 5.0)), DEFAULT_SETTINGS)
    assert spans(segments) == [(3.0, 5.0)]
    assert pauses == []


def test_no_regions_means_no_segments_and_no_pauses():
    assert build_segments([], DEFAULT_SETTINGS) == ([], [])


def test_unsorted_overlapping_and_empty_regions_are_tolerated():
    segments, pauses = build_segments(
        regions((5.0, 6.0), (1.0, 3.0), (2.5, 3.5), (4.0, 4.0)), DEFAULT_SETTINGS
    )
    assert spans(segments) == [(1.0, 3.5), (5.0, 6.0)]
    assert len(pauses) == 1


def test_thresholds_are_configurable():
    strict = AnalysisSettings(min_pause_ms=300, medium_pause_ms=600, long_silence_ms=2000)
    segments, pauses = build_segments(regions((0.0, 1.0), (1.3, 2.0), (4.5, 5.0)), strict)
    assert len(segments) == 3
    assert [pause.significance for pause in pauses] == ["short", "long"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_pause_ms": 0},
        {"min_pause_ms": 2000, "medium_pause_ms": 1000},
        {"medium_pause_ms": 6000},
        {"vad_min_silence_ms": 500},
        {"min_segment_words": 0},
        {"wpm_outlier": 0},
    ],
)
def test_inconsistent_thresholds_are_rejected(overrides):
    with pytest.raises(ValueError):
        AnalysisSettings(**overrides)


def test_words_go_to_the_segment_containing_their_midpoint():
    segments, _ = build_segments(regions((0.0, 2.0), (3.0, 5.0)), DEFAULT_SETTINGS)
    words = [Word("one", 0.2, 0.6), Word("two", 1.5, 1.9), Word("three", 3.1, 3.4)]
    moved = assign_words(segments, words)
    assert [[word.text for word in segment.words] for segment in segments] == [
        ["one", "two"],
        ["three"],
    ]
    assert moved == 0


def test_a_word_timed_inside_a_pause_goes_to_the_nearest_segment_and_is_counted_as_moved():
    segments, _ = build_segments(regions((0.0, 2.0), (3.0, 5.0)), DEFAULT_SETTINGS)
    words = [Word("late", 2.0, 2.3), Word("early", 2.6, 2.9), Word("after", 5.2, 5.6)]
    moved = assign_words(segments, words)
    assert [[word.text for word in segment.words] for segment in segments] == [
        ["late"],
        ["early", "after"],
    ]
    assert moved == 3


def test_assigning_words_twice_does_not_duplicate_them():
    segments, _ = build_segments(regions((0.0, 2.0)), DEFAULT_SETTINGS)
    words = [Word("one", 0.2, 0.6)]
    assign_words(segments, words)
    assign_words(segments, words)
    assert len(segments[0].words) == 1


def test_words_without_any_segment_are_simply_not_assigned():
    assert assign_words([], [Word("ghost", 0.0, 0.5)]) == 0


def test_punctuation_is_not_counted_as_a_word_but_hindi_words_are():
    assert is_countable_word("danger,")
    assert is_countable_word("खतरा")
    assert is_countable_word("हूँ।")
    assert is_countable_word("3")
    assert not is_countable_word("...")
    assert not is_countable_word("—")
    assert not is_countable_word("।")
    assert count_words([Word("मैं", 0, 1), Word("—", 1, 2), Word("खतरा", 2, 3)]) == 2
