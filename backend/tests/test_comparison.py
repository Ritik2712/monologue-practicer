"""Setting a take against a reference recording of the same passage."""

import copy

import pytest

from app import schemas
from app.comparison.compare import compare
from app.comparison.settings import DEFAULT_COMPARISON_SETTINGS, ComparisonSettings
from tests.conftest import make_recording, metric

# The reference: four phrases, with pauses of 2.0 s, 0.8 s and 1.2 s between them.
REFERENCE = [
    (0.0, 4.0, "I am not in danger Skylar I am the danger"),  # 10 words, 150 WPM
    (6.0, 10.0, "a guy opens his door and gets shot"),  # 8 words, 120 WPM
    (10.8, 12.8, "and you think that of me"),  # 6 words, 180 WPM
    (14.0, 16.0, "I am the one who knocks"),  # 6 words, 180 WPM
]
# The take says the same words but breaks the first line in two, runs lines two and three
# together twice as fast, and barely pauses where the reference holds two seconds.
TAKE = [
    (0.0, 2.0, "I am not in danger Skylar"),
    (3.5, 5.0, "I am the danger"),
    (5.6, 9.1, "a guy opens his door and gets shot and you think that of me"),
    (10.4, 12.4, "I am the one who knocks"),
]


def comparing(take=None, reference=None, settings=DEFAULT_COMPARISON_SETTINGS, **kwargs):
    return compare(
        take or make_recording(TAKE),
        reference or make_recording(REFERENCE),
        settings,
        take_id="take-1",
        reference_id="ref-1",
        reference_title=kwargs.get("title", "The original"),
    )


def test_the_same_passage_is_recognised_as_such():
    result = comparing()
    assert (result.take_id, result.reference_id, result.reference_title) == (
        "take-1",
        "ref-1",
        "The original",
    )
    alignment = result.alignment
    assert (alignment.status, alignment.matched_words, alignment.coverage) == ("matched", 30, 1.0)
    assert alignment.note.startswith("100% of the reference's words were found in your take")
    assert result.settings["version"] == 1


# --- Pauses ------------------------------------------------------------------------------


def test_every_pause_is_set_beside_the_same_spot_in_the_other_recording():
    pauses = comparing().pauses
    assert [(p.status, p.after_words) for p in pauses] == [
        ("take_only", "I am not in danger Skylar"),
        ("both", "…danger Skylar I am the danger"),
        ("reference_only", "…opens his door and gets shot"),
        ("both", "and you think that of me"),
    ]


def test_a_pause_both_recordings_make_shows_the_difference_in_length():
    held = comparing().pauses[1]
    assert (held.reference.pause_id, held.reference.duration_seconds) == ("pause-1", 2.0)
    assert (held.take.pause_id, held.take.duration_seconds) == ("pause-2", 0.6)
    assert held.difference_seconds == -1.4
    # Each can be heard with a second and a half either side.
    assert (held.reference_play.start_seconds, held.reference_play.end_seconds) == (2.5, 7.5)
    assert (held.take_play.start_seconds, held.take_play.end_seconds) == (3.5, 7.1)


def test_a_pause_only_the_reference_makes_points_at_where_it_would_go_in_the_take():
    missing = comparing().pauses[2]
    assert missing.take is None and missing.difference_seconds is None
    assert missing.reference.duration_seconds == 0.8
    # "…gets shot | and you think…": the take runs straight on at 7.6 s.
    assert (missing.take_play.start_seconds, missing.take_play.end_seconds) == (6.1, 9.1)


def test_a_pause_only_the_take_makes_points_at_the_same_spot_in_the_reference():
    extra = comparing().pauses[0]
    assert extra.reference is None
    assert (extra.take.pause_id, extra.take.duration_seconds) == ("pause-1", 1.5)
    # After "Skylar", which the reference reaches at 2.4 s.
    assert (extra.reference_play.start_seconds, extra.reference_play.end_seconds) == (0.9, 3.9)
    assert (extra.take_play.start_seconds, extra.take_play.end_seconds) == (0.5, 5.0)


def test_a_reference_pause_in_a_part_the_take_never_reached_is_not_called_missing():
    only_the_start = make_recording(TAKE[:2])
    result = comparing(take=only_the_start)
    assert result.alignment.status == "partial"
    assert [(p.status, p.reference and p.reference.pause_id) for p in result.pauses] == [
        ("take_only", None),
        ("unplaced", "pause-1"),
        ("unplaced", "pause-2"),
        ("unplaced", "pause-3"),
    ]
    assert not any(d.kind == "pause_missing" for d in result.differences)


def test_when_the_take_makes_two_pauses_in_one_spot_the_longer_one_counts():
    take = make_recording(
        [
            (0.0, 4.0, "I am not in danger Skylar I am the danger"),
            (4.6, 5.0, "um"),  # an extra sound in the middle of the reference's pause
            (6.4, 10.4, "a guy opens his door and gets shot"),
        ]
    )
    reference = make_recording(REFERENCE[:2])
    (pause,) = comparing(take=take, reference=reference).pauses
    assert pause.status == "both"
    assert (pause.take.pause_id, pause.take.duration_seconds) == ("pause-2", 1.4)


def with_stray_word_times(recording: schemas.AnalysisBody, early: float) -> schemas.AnalysisBody:
    """The same recording as the speech recogniser really reports it.

    The first word after each pause is given a start time inside the pause, and the last
    word before it an end time inside the pause too.
    """
    strayed = copy.deepcopy(recording)
    first_words = {s.id: None for s in strayed.segments}
    for word in strayed.words:
        if first_words[word.segment_id] is None:
            first_words[word.segment_id] = word
            word.start_seconds = round(max(0.0, word.start_seconds - early), 3)
    for segment in strayed.segments:
        last = [word for word in strayed.words if word.segment_id == segment.id][-1]
        last.end_seconds = round(last.end_seconds + early / 2, 3)
    return strayed


def test_a_recording_compared_with_a_copy_of_itself_shows_no_difference_at_all():
    """Found by running the real pipeline: word times stray into pauses by a few tenths."""
    recording = with_stray_word_times(make_recording(REFERENCE), early=0.45)
    result = comparing(take=copy.deepcopy(recording), reference=recording)

    assert [p.status for p in result.pauses] == ["both", "both", "both"]
    assert [p.difference_seconds for p in result.pauses] == [0.0, 0.0, 0.0]
    assert all(p.difference_ratio == 0.0 for p in result.phrases if p.comparable)
    assert all(row.difference in (0, None) for row in result.metrics)
    assert result.differences == []


def test_pauses_are_matched_by_phrase_even_when_word_times_stray_into_them():
    take = with_stray_word_times(make_recording(TAKE), early=0.5)
    reference = with_stray_word_times(make_recording(REFERENCE), early=0.3)
    assert [
        (p.status, p.difference_seconds) for p in comparing(take=take, reference=reference).pauses
    ] == [
        ("take_only", None),
        ("both", -1.4),
        ("reference_only", None),
        ("both", 0.1),
    ]


# --- Phrases -----------------------------------------------------------------------------


def test_each_phrase_of_the_reference_is_paced_against_the_same_words_in_the_take():
    phrases = comparing().phrases
    assert [p.reference_segment_id for p in phrases] == ["seg-1", "seg-2", "seg-3", "seg-4"]
    assert all(p.comparable and p.coverage == 1.0 for p in phrases)
    assert [(p.reference_wpm, p.take_wpm) for p in phrases] == [
        (150.0, 171.4),  # the take's 1.5 s pause inside this line is left out
        (120.0, 240.0),
        (180.0, 240.0),
        (180.0, 180.0),
    ]
    assert [p.difference_ratio for p in phrases] == [0.143, 1.0, 0.333, 0.0]
    assert phrases[1].difference_wpm == 120.0
    assert phrases[1].text == "a guy opens his door and gets shot"


def test_a_phrase_can_be_played_in_both_recordings():
    line = comparing().phrases[1]
    assert (line.reference_play.start_seconds, line.reference_play.end_seconds) == (6.0, 10.0)
    assert (line.take_play.start_seconds, line.take_play.end_seconds) == (5.6, 7.6)


def test_a_phrase_too_short_or_too_poorly_matched_is_listed_but_not_paced():
    reference = make_recording(
        [(0.0, 3.0, "I am the one who knocks"), (4.0, 4.6, "No"), (6.0, 9.0, "so let me be clear")]
    )
    take = make_recording(
        [
            (0.0, 3.0, "I am the one who knocks"),
            (4.0, 4.6, "No"),
            (6.0, 9.0, "so allow us to be honest"),
        ]
    )
    knocks, no, clear = comparing(take=take, reference=reference).phrases
    assert knocks.comparable
    # One word is too little to measure a pace over, but it can still be found and played.
    assert not no.comparable and no.take_play is not None and no.take_wpm is None
    # Two of five words matched: too few to call it the same phrase.
    assert (clear.coverage, clear.comparable) == (0.4, False)


# --- Whole recordings --------------------------------------------------------------------


def test_whole_recording_figures_are_set_side_by_side():
    take = make_recording(TAKE, speech_active_wpm=239.64, pause_ratio=0.316)
    reference = make_recording(REFERENCE, speech_active_wpm=223.06, pause_ratio=0.503)
    rows = {row.metric: row for row in comparing(take=take, reference=reference).metrics}

    assert (rows["speechActiveWpm"].take, rows["speechActiveWpm"].reference) == (239.6, 223.1)
    assert rows["speechActiveWpm"].difference == 16.5
    # Shown as percentages, and subtracted as shown: 32 - 50, not -18.7.
    assert (rows["pauseRatio"].take, rows["pauseRatio"].reference) == (32.0, 50.0)
    assert rows["pauseRatio"].difference == -18.0
    assert (rows["durationSeconds"].take, rows["durationSeconds"].reference) == (12.9, 16.5)
    assert rows["energyVariation"].note.startswith("Also depends on how each recording was made")


def test_level_and_voice_height_are_never_compared():
    result = comparing()
    names = {row.metric for row in result.metrics}
    assert not names & {"pitchMedianHz", "pitchRangeHz", "signalToNoise", "clippingRatio"}
    assert any(caveat.startswith("Loudness itself is not compared") for caveat in result.caveats)
    assert any(caveat.startswith("How high each voice is") for caveat in result.caveats)


def test_a_figure_missing_on_one_side_has_no_difference():
    take = make_recording(TAKE, pitch_variation_semitones=None)
    rows = {row.metric: row for row in comparing(take=take).metrics}
    pitch = rows["pitchVariationSemitones"]
    assert (pitch.take, pitch.reference, pitch.difference) == (None, 3.0, None)


def test_a_difference_built_on_an_estimate_is_marked_as_one():
    take = make_recording(TAKE, speech_active_wpm=metric(200.0, "words/minute", "estimated"))
    rows = {row.metric: row for row in comparing(take=take).metrics}
    assert rows["speechActiveWpm"].estimated and not rows["pauseCount"].estimated


# --- The biggest differences --------------------------------------------------------------


def test_the_biggest_differences_are_listed_largest_first_in_plain_words():
    differences = comparing().differences
    assert [d.kind for d in differences] == [
        "phrase_faster",
        "pause_shorter",
        "pause_extra",
        "phrase_faster",
    ]
    assert [d.statement for d in differences[:3]] == [
        (
            "You said “a guy opens his door and…” at 240 WPM. The reference says it at "
            "120 WPM, so you were 100% faster."
        ),
        (
            "The reference holds 2 seconds after “…danger Skylar I am the danger”; you held "
            "0.6 seconds."
        ),
        (
            "You paused for 1.5 seconds after “I am not in danger Skylar”. The reference does "
            "not pause there."
        ),
    ]
    # Each one can be heard in both recordings.
    assert all(d.reference_play and d.take_play for d in differences)


def test_small_differences_are_not_listed():
    kinds = [d.kind for d in comparing().differences]
    # The reference's 0.8 s pause is under a second, and the first line is only 14% faster.
    assert "pause_missing" not in kinds
    assert kinds.count("phrase_faster") == 2


def test_a_missing_long_pause_tops_the_list():
    reference = make_recording(
        [(0.0, 3.0, "I am the one who knocks"), (9.0, 12.0, "so let me be clear")]
    )
    take = make_recording([(0.0, 6.0, "I am the one who knocks so let me be clear")])
    first = comparing(take=take, reference=reference).differences[0]
    assert first.kind == "pause_missing"
    assert first.statement == (
        "The reference pauses for 6 seconds after “I am the one who knocks”. You did not "
        "pause there."
    )


def test_a_clearly_different_overall_pace_is_listed_without_a_place_to_play():
    take = make_recording(REFERENCE, speech_active_wpm=230.0)
    reference = make_recording(REFERENCE, speech_active_wpm=180.0)
    (difference,) = comparing(take=take, reference=reference).differences
    assert difference.kind == "overall_faster"
    assert difference.statement == (
        "Overall you spoke at 230 WPM while speaking; the reference speaks at 180 WPM. "
        "That is 28% faster."
    )
    assert difference.reference_play is None and difference.take_play is None


def test_no_more_than_five_differences_are_listed():
    reference = make_recording(
        [(i * 10.0, i * 10.0 + 3.0, f"line number {i} of this") for i in range(9)]
    )
    take = make_recording([(0.0, 40.0, " ".join(f"line number {i} of this" for i in range(9)))])
    result = comparing(take=take, reference=reference)
    assert len([p for p in result.pauses if p.status == "reference_only"]) == 8
    assert len(result.differences) == 5


# --- When the two do not line up ----------------------------------------------------------


def test_different_words_are_compared_only_as_whole_recordings():
    take = make_recording([(0.0, 4.0, "to be or not to be that is the question")])
    result = comparing(take=take)
    assert result.alignment.status == "unmatched"
    assert "do not appear to be the same passage" in result.alignment.note
    assert result.pauses == [] and result.phrases == []
    assert len(result.metrics) == 14
    assert not any("Phrases are lined up" in caveat for caveat in result.caveats)


def test_a_recording_with_no_recognised_words_cannot_be_lined_up():
    silent = make_recording([], total_word_count=None)
    result = comparing(take=silent)
    assert result.alignment.status == "no_words"
    assert result.alignment.note.startswith("No words were recognised in your take")
    assert result.pauses == [] and result.phrases == [] and result.differences == []


def test_warnings_about_either_recording_are_passed_on():
    noisy = make_recording(
        REFERENCE,
        warnings=[schemas.AnalysisWarning(code="noisy", message="The background is loud.")],
    )
    caveats = comparing(reference=noisy).caveats
    assert "About the reference: The background is loud." in caveats
    assert any("music, other voices or effects" in caveat for caveat in caveats)


def test_comparing_changes_neither_recording():
    take, reference = make_recording(TAKE), make_recording(REFERENCE)
    before = copy.deepcopy((take, reference))
    comparing(take=take, reference=reference)
    assert (take, reference) == before


def test_thresholds_that_contradict_each_other_are_refused():
    with pytest.raises(ValueError):
        ComparisonSettings(matched_coverage=0.2, partial_coverage=0.5)
    with pytest.raises(ValueError):
        ComparisonSettings(max_differences=0)
