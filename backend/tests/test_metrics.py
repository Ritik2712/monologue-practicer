import pytest

from app.pipeline.metrics import (
    pace_vs_typical,
    segment_pace,
    summarize_pace,
    summarize_pauses,
    typical_wpm,
    words_per_minute,
)
from app.pipeline.segmentation import SpeechRegion, assign_words, build_segments
from app.pipeline.settings import DEFAULT_SETTINGS
from tests.conftest import make_words


def analyse(spans, words):
    segments, pauses = build_segments([SpeechRegion(a, b) for a, b in spans], DEFAULT_SETTINGS)
    assign_words(segments, words)
    paces = [segment_pace(segment, DEFAULT_SETTINGS, has_transcript=True) for segment in segments]
    return segments, pauses, paces


def test_twelve_words_in_four_seconds_is_180_wpm():
    assert words_per_minute(12, 4.0) == pytest.approx(180)
    _, _, paces = analyse([(10.0, 14.0)], make_words(10.0, 14.0, 12))
    assert paces[0].wpm == pytest.approx(180)
    assert paces[0].word_count == 12
    assert paces[0].reliable
    assert paces[0].quality == "measured"


def test_no_speaking_time_gives_no_number_instead_of_dividing_by_zero():
    assert words_per_minute(5, 0) is None
    assert words_per_minute(5, -1) is None
    assert words_per_minute(0, 3) == 0


def test_speech_active_wpm_excludes_pauses_and_whole_clip_wpm_includes_them():
    # Two 4-second segments of 12 words each, separated by a 12-second silence.
    segments, _, paces = analyse(
        [(0.0, 4.0), (16.0, 20.0)], make_words(0.0, 4.0, 12) + make_words(16.0, 20.0, 12)
    )
    pace = summarize_pace(segments, paces, 20.0, has_transcript=True, word_quality="measured")

    assert pace.total_words == 24
    assert pace.speech_active_seconds == pytest.approx(8.0)
    assert pace.speech_active_wpm.value == pytest.approx(180)  # 24 words / 8 s
    assert pace.whole_clip_wpm.value == pytest.approx(72)  # 24 words / 20 s
    assert "Every pause is excluded" in pace.speech_active_wpm.note
    assert "including pauses" in pace.whole_clip_wpm.note


def test_a_longer_pause_changes_whole_clip_wpm_but_not_speech_active_wpm():
    def rates(gap: float):
        second = 4.0 + gap
        segments, _, paces = analyse(
            [(0.0, 4.0), (second, second + 4.0)],
            make_words(0.0, 4.0, 10) + make_words(second, second + 4.0, 10),
        )
        pace = summarize_pace(
            segments, paces, second + 4.0, has_transcript=True, word_quality="measured"
        )
        return pace.speech_active_wpm.value, pace.whole_clip_wpm.value

    active_short, whole_short = rates(1.0)
    active_long, whole_long = rates(30.0)
    assert active_short == pytest.approx(active_long) == pytest.approx(150)
    assert whole_long < whole_short


def test_silence_before_and_after_speech_is_not_speaking_time():
    segments, _, paces = analyse([(5.0, 9.0)], make_words(5.0, 9.0, 12))
    pace = summarize_pace(segments, paces, 30.0, has_transcript=True, word_quality="measured")
    assert pace.speech_active_wpm.value == pytest.approx(180)
    assert pace.whole_clip_wpm.value == pytest.approx(24)


def test_short_segments_and_few_words_are_marked_unreliable_but_still_reported():
    _, _, paces = analyse(
        [(0.0, 1.5), (3.0, 6.0)], make_words(0.0, 1.5, 4) + make_words(3.0, 6.0, 2)
    )
    short, sparse = paces
    assert short.wpm == pytest.approx(160)
    assert not short.reliable
    assert short.quality == "estimated"
    assert short.flags == ("short_segment",)

    assert sparse.wpm == pytest.approx(40)
    assert not sparse.reliable
    assert sparse.flags == ("few_words",)


def test_exactly_two_seconds_and_three_words_is_reliable():
    _, _, paces = analyse([(0.0, 2.0)], make_words(0.0, 2.0, 3))
    assert paces[0].reliable
    assert paces[0].flags == ()


def test_a_fast_segment_is_flagged_for_review_and_never_capped():
    _, _, paces = analyse([(0.0, 3.0)], make_words(0.0, 3.0, 15))
    assert paces[0].wpm == pytest.approx(300)
    assert paces[0].flags == ("wpm_outlier",)
    # An outlier is a question, not an error: the measurement itself is still trusted.
    assert paces[0].reliable
    assert paces[0].quality == "measured"


def test_180_wpm_exactly_is_not_an_outlier():
    _, _, paces = analyse([(0.0, 4.0)], make_words(0.0, 4.0, 12))
    assert "wpm_outlier" not in paces[0].flags


def test_low_recogniser_confidence_makes_a_segment_an_estimate():
    _, _, paces = analyse([(0.0, 4.0)], make_words(0.0, 4.0, 10, probability=0.3))
    assert paces[0].confidence == pytest.approx(0.3)
    assert paces[0].flags == ("low_confidence",)
    assert paces[0].quality == "estimated"


def test_a_segment_with_no_words_has_no_wpm():
    _, _, paces = analyse([(0.0, 4.0), (6.0, 9.0)], make_words(0.0, 4.0, 10))
    assert paces[1].wpm is None
    assert paces[1].quality == "unavailable"
    assert paces[1].flags == ("no_words",)


def test_without_a_transcript_every_word_based_number_is_unavailable():
    segments, _ = build_segments([SpeechRegion(0.0, 4.0)], DEFAULT_SETTINGS)
    paces = [segment_pace(segment, DEFAULT_SETTINGS, has_transcript=False) for segment in segments]
    pace = summarize_pace(segments, paces, 5.0, has_transcript=False, word_quality="unavailable")

    assert paces[0].wpm is None
    assert pace.speech_active_wpm.value is None
    assert pace.speech_active_wpm.quality == "unavailable"
    assert pace.whole_clip_wpm.quality == "unavailable"
    # Speaking time comes from the audio alone, so it is still known.
    assert pace.speech_active_seconds == pytest.approx(4.0)


def test_no_speech_at_all_is_unavailable_not_zero():
    pace = summarize_pace([], [], 10.0, has_transcript=False, word_quality="unavailable")
    assert pace.speech_active_wpm.value is None
    assert pace.speech_active_wpm.note == "No speech was detected."
    assert pace.speech_active_seconds == 0


def test_pace_variation_uses_only_reliable_segments():
    segments, _, paces = analyse(
        [(0.0, 4.0), (5.0, 9.0), (10.0, 11.0)],
        make_words(0.0, 4.0, 8) + make_words(5.0, 9.0, 12) + make_words(10.0, 11.0, 6),
    )
    pace = summarize_pace(segments, paces, 11.0, has_transcript=True, word_quality="measured")
    # 120 and 180 WPM count; the one-second segment at 360 WPM is too short to trust.
    assert pace.pace_min_wpm.value == pytest.approx(120)
    assert pace.pace_max_wpm.value == pytest.approx(180)
    assert pace.pace_variation.value == pytest.approx(30)


def test_pace_variation_needs_at_least_two_reliable_segments():
    segments, _, paces = analyse([(0.0, 4.0)], make_words(0.0, 4.0, 8))
    pace = summarize_pace(segments, paces, 4.0, has_transcript=True, word_quality="measured")
    assert pace.pace_variation.quality == "unavailable"
    assert pace.speech_active_wpm.value == pytest.approx(120)


def test_word_quality_is_carried_onto_the_overall_rates():
    segments, _, paces = analyse([(0.0, 4.0)], make_words(0.0, 4.0, 8))
    pace = summarize_pace(segments, paces, 4.0, has_transcript=True, word_quality="estimated")
    assert pace.speech_active_wpm.quality == "estimated"
    assert pace.whole_clip_wpm.quality == "estimated"


def test_pause_statistics():
    _, pauses = build_segments(
        [SpeechRegion(0.0, 2.0), SpeechRegion(2.5, 4.0), SpeechRegion(5.5, 7.0), SpeechRegion(13.0, 15.0)],
        DEFAULT_SETTINGS,
    )  # fmt: skip
    summary = summarize_pauses(pauses, 20.0, speech_detected=True)

    assert summary.count.value == 3
    assert summary.total_seconds.value == pytest.approx(8.0)  # 0.5 + 1.5 + 6.0
    assert summary.average_seconds.value == pytest.approx(8.0 / 3)
    assert summary.median_seconds.value == pytest.approx(1.5)
    assert summary.longest_seconds.value == pytest.approx(6.0)
    assert summary.ratio.value == pytest.approx(0.4)  # 8 s of pause in a 20 s clip
    assert summary.ratio.quality == "measured"


def test_median_of_an_even_number_of_pauses_is_the_mean_of_the_middle_two():
    _, pauses = build_segments(
        [SpeechRegion(0.0, 1.0), SpeechRegion(2.0, 3.0), SpeechRegion(5.0, 6.0)], DEFAULT_SETTINGS
    )
    assert summarize_pauses(
        pauses, 6.0, speech_detected=True
    ).median_seconds.value == pytest.approx(1.5)


def test_speech_without_pauses_reports_zero_pauses_and_no_average():
    summary = summarize_pauses([], 10.0, speech_detected=True)
    assert summary.count.value == 0
    assert summary.total_seconds.value == 0
    assert summary.ratio.value == 0
    assert summary.average_seconds.value is None
    assert summary.average_seconds.quality == "unavailable"
    assert summary.longest_seconds.value is None


def test_no_speech_means_pause_numbers_are_unavailable_rather_than_zero():
    summary = summarize_pauses([], 10.0, speech_detected=False)
    for metric in (summary.count, summary.total_seconds, summary.average_seconds, summary.ratio):
        assert metric.value is None
        assert metric.quality == "unavailable"


def test_typical_pace_is_the_median_of_the_reliable_segments():
    # Reliable segments at 120, 150 and 300 WPM, plus a one-second burst that is ignored.
    _, _, paces = analyse(
        [(0.0, 4.0), (5.0, 9.0), (10.0, 14.0), (15.0, 16.0)],
        make_words(0.0, 4.0, 8)
        + make_words(5.0, 9.0, 10)
        + make_words(10.0, 14.0, 20)
        + make_words(15.0, 16.0, 9),
    )
    typical = typical_wpm(paces, DEFAULT_SETTINGS)

    # The median: one very fast phrase does not drag "typical" upwards.
    assert typical == pytest.approx(150)
    assert [pace_vs_typical(pace, typical, DEFAULT_SETTINGS) for pace in paces] == [
        "typical",  # 120 is 20% below 150
        "typical",
        "faster",  # 300 is double
        None,  # too short to judge
    ]


def test_faster_and_slower_start_exactly_25_percent_from_typical():
    def label(words: int) -> str | None:
        _, _, paces = analyse([(0.0, 6.0)], make_words(0.0, 6.0, words))
        return pace_vs_typical(paces[0], 160.0, DEFAULT_SETTINGS)

    assert label(20) == "faster"  # 200 WPM = 160 x 1.25
    assert label(19) == "typical"  # 190 WPM
    assert label(12) == "slower"  # 120 WPM = 160 x 0.75
    assert label(13) == "typical"  # 130 WPM


def test_no_typical_pace_with_fewer_than_three_reliable_segments():
    _, _, paces = analyse(
        [(0.0, 4.0), (5.0, 9.0)], make_words(0.0, 4.0, 8) + make_words(5.0, 9.0, 16)
    )
    assert typical_wpm(paces, DEFAULT_SETTINGS) is None
    assert [pace_vs_typical(pace, None, DEFAULT_SETTINGS) for pace in paces] == [None, None]


# --- Delivery pace: a segment with pauses inside it ---------------------------------------


def test_a_segment_with_a_pause_inside_has_a_delivery_pace_and_a_speaking_speed():
    # One line of 11 words: 2 s of speaking, a 0.6 s pause, 2.4 s of speaking.
    segments, _, paces = analyse(
        [(0.0, 2.0), (2.6, 5.0)], make_words(0.0, 2.0, 5) + make_words(2.6, 5.0, 6)
    )
    assert len(segments) == 1
    (pace,) = paces
    assert pace.wpm == pytest.approx(132)  # 11 words / 5.0 s, the pause counted
    assert pace.speaking_wpm == pytest.approx(150)  # 11 words / 4.4 s of speaking
    assert pace.reliable


def test_a_segment_with_no_pause_inside_has_one_pace():
    _, _, (pace,) = analyse([(0.0, 4.0)], make_words(0.0, 4.0, 12))
    assert pace.wpm == pace.speaking_wpm == pytest.approx(180)


def test_the_recordings_delivery_pace_counts_pauses_inside_segments_and_not_those_between():
    # A line with a 0.6 s pause in it, a 3 s pause, then a second line.
    segments, _, paces = analyse(
        [(0.0, 2.0), (2.6, 5.0), (8.0, 12.0)],
        make_words(0.0, 2.0, 5) + make_words(2.6, 5.0, 6) + make_words(8.0, 12.0, 12),
    )
    pace = summarize_pace(segments, paces, 12.0, has_transcript=True, word_quality="measured")

    assert len(segments) == 2
    assert pace.delivery_wpm.value == pytest.approx(23 / (9.0 / 60))  # 5.0 s + 4.0 s
    assert pace.speech_active_wpm.value == pytest.approx(23 / (8.4 / 60))  # speaking only
    assert pace.whole_clip_wpm.value == pytest.approx(23 / (12.0 / 60))
    assert pace.speech_active_seconds == pytest.approx(8.4)
    assert pace.whole_clip_wpm.value < pace.delivery_wpm.value < pace.speech_active_wpm.value


def test_without_a_pause_inside_any_segment_delivery_pace_is_the_speech_active_wpm():
    segments, _, paces = analyse(
        [(0.0, 4.0), (16.0, 20.0)], make_words(0.0, 4.0, 12) + make_words(16.0, 20.0, 12)
    )
    pace = summarize_pace(segments, paces, 20.0, has_transcript=True, word_quality="measured")
    assert pace.delivery_wpm.value == pytest.approx(pace.speech_active_wpm.value)


def test_whether_a_segment_is_long_enough_is_judged_on_its_speaking_time():
    # 2.6 s from first sound to last, of which only 1.8 s is speaking.
    _, _, (pace,) = analyse(
        [(0.0, 1.0), (1.8, 2.6)], make_words(0.0, 1.0, 3) + make_words(1.8, 2.6, 2)
    )
    assert "short_segment" in pace.flags
    assert not pace.reliable


def test_a_segment_is_flagged_for_review_on_its_speaking_speed_whatever_pauses_it_holds():
    # 13 words in 4 s of speaking is 195 WPM; with the 0.9 s pause counted it is 159.
    _, _, (pace,) = analyse(
        [(0.0, 2.0), (2.9, 4.9)], make_words(0.0, 2.0, 7) + make_words(2.9, 4.9, 6)
    )
    assert pace.speaking_wpm == pytest.approx(195)
    assert pace.wpm == pytest.approx(13 / (4.9 / 60))
    assert "wpm_outlier" in pace.flags
    assert pace.reliable


def test_typical_pace_and_variation_are_taken_from_delivery_pace():
    # Three lines of 12 words in 4 s of speaking. The second also holds a 0.8 s pause.
    spans = [(0.0, 4.0), (6.0, 8.0), (8.8, 10.8), (13.0, 17.0)]
    words = (
        make_words(0.0, 4.0, 12)
        + make_words(6.0, 8.0, 6)
        + make_words(8.8, 10.8, 6)
        + make_words(13.0, 17.0, 12)
    )
    segments, _, paces = analyse(spans, words)
    assert [pace.speaking_wpm for pace in paces] == pytest.approx([180, 180, 180])
    assert [pace.wpm for pace in paces] == pytest.approx([180, 150, 180])
    assert typical_wpm(paces, DEFAULT_SETTINGS) == pytest.approx(180)
    pace = summarize_pace(segments, paces, 17.0, has_transcript=True, word_quality="measured")
    assert pace.pace_min_wpm.value == pytest.approx(150)
    assert pace.pace_variation.value > 0
