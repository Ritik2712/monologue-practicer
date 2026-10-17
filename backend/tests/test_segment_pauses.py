"""Segments that hold pauses.

A pause of half a second or more is always a pause. Only one of a second or more ends a
segment. These tests follow one recording of that shape through everything that reads a
result: the pipeline's own output, a corrected transcript, the WPM review, the comparison
with a reference, and the coaching. They also check that a result stored before segments
could hold a pause still reads as it did.
"""

import pytest

from app import schemas, stretches, wpm_review
from app.coaching import rules
from app.coaching.findings import build_findings, profile_wants
from app.coaching.prompt import build_prompt
from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from app.comparison.compare import compare
from app.comparison.settings import DEFAULT_COMPARISON_SETTINGS
from app.feedback import FeedbackError, classify
from app.pipeline.settings import AnalysisSettings
from app.transcript_correction import correct_transcript
from tests.conftest import make_recording, measured

SETTINGS = DEFAULT_COACHING_SETTINGS

# Two lines. The first holds a 0.6 s pause; a 1.5 s pause separates it from the second.
#
#   0.0-2.0  "you clearly do not know"     5 words
#   (0.6 s)
#   2.6-5.0  "who you are talking to"      5 words     line 1: 10 words in 5.0 s, 4.4 s speaking
#   (1.5 s)
#   6.5-10.5 "so let me clue you in I am not in danger"   11 words in 4.0 s
LINES = [
    (0.0, 2.0, "you clearly do not know"),
    (2.6, 5.0, "who you are talking to"),
    (6.5, 10.5, "so let me clue you in I am not in danger"),
]


@pytest.fixture
def body(tmp_path):
    return measured(tmp_path, LINES)


# --- What the pipeline stores --------------------------------------------------------------


def test_a_short_pause_stays_inside_its_segment_and_a_long_one_ends_it(body):
    first, second = body.segments
    assert (first.id, first.start_seconds, first.end_seconds) == ("seg-1", 0.0, 5.0)
    assert (second.id, second.start_seconds, second.end_seconds) == ("seg-2", 6.5, 10.5)
    assert first.transcript == "you clearly do not know who you are talking to"

    inside, between = body.pauses
    assert (inside.id, inside.duration_seconds, inside.inside_segment) == ("pause-1", 0.6, True)
    assert (inside.after_segment_id, inside.before_segment_id) == ("seg-1", "seg-1")
    assert (between.id, between.duration_seconds, between.inside_segment) == ("pause-2", 1.5, False)
    assert (between.after_segment_id, between.before_segment_id) == ("seg-1", "seg-2")
    # Both are pauses, counted like any other.
    assert body.metrics.pause_count.value == 2
    assert body.metrics.total_pause_seconds.value == pytest.approx(2.1)


def test_a_segment_has_a_delivery_pace_and_a_speaking_speed(body):
    first, second = body.segments
    assert (first.pause_count, first.pause_seconds) == (1, 0.6)
    assert first.speech_active_seconds == 4.4
    assert first.delivery_wpm == 120.0  # 10 words / 5.0 s
    assert first.segment_wpm == 136.4  # 10 words / 4.4 s
    # No pause inside the second line: one pace.
    assert (second.pause_count, second.pause_seconds) == (0, 0.0)
    assert second.delivery_wpm == second.segment_wpm == 165.0  # 11 words / 4.0 s


def test_the_recording_has_three_paces_that_count_ever_more_silence(body):
    metrics = body.metrics
    assert metrics.speech_active_seconds.value == 8.4
    assert metrics.speech_active_wpm.value == 150.0  # 21 words / 8.4 s
    assert metrics.delivery_wpm.value == 140.0  # 21 words / 9.0 s: the 0.6 s counted
    assert metrics.whole_clip_wpm.value == pytest.approx(114.5, abs=0.1)  # 21 words / 11.0 s
    assert "inside a segment" in metrics.delivery_wpm.note


def test_the_stretches_are_stored_and_every_word_says_which_one_it_is_in(body):
    assert [(s.index, s.start_seconds, s.end_seconds, s.segment_id) for s in body.stretches] == [
        (0, 0.0, 2.0, "seg-1"),
        (1, 2.6, 5.0, "seg-1"),
        (2, 6.5, 10.5, "seg-2"),
    ]
    assert [word.stretch_index for word in body.words] == [0] * 5 + [1] * 5 + [2] * 11
    assert [word.segment_id for word in body.words] == ["seg-1"] * 10 + ["seg-2"] * 11
    # Pause n lies between stretch n and stretch n + 1.
    for pause in body.pauses:
        assert pause.start_seconds == body.stretches[pause.index].end_seconds
        assert pause.end_seconds == body.stretches[pause.index + 1].start_seconds


def test_a_segments_loudness_is_taken_from_its_speech_not_from_the_pause_inside_it(tmp_path):
    # Two recordings of one line, alike but for a 0.9 s silence in the middle of the second.
    plain = measured(tmp_path, [(0.0, 4.0, "one two three four five six seven eight")])
    paused = measured(
        tmp_path,
        [(0.0, 2.0, "one two three four"), (2.9, 4.9, "five six seven eight")],
        name="paused.wav",
    )
    assert len(paused.segments) == 1
    assert paused.segments[0].mean_energy_db == pytest.approx(
        plain.segments[0].mean_energy_db, abs=0.2
    )


def test_the_settings_record_the_segment_break(body):
    assert body.settings["version"] == 3
    assert body.settings["segment_break_ms"] == 1000


def test_with_the_break_at_the_minimum_pause_the_same_recording_is_cut_as_it_used_to_be(tmp_path):
    as_before = measured(tmp_path, LINES, settings=AnalysisSettings(segment_break_ms=500))
    today = measured(tmp_path, LINES, name="today.wav")

    assert [s.transcript for s in as_before.segments] == [text for _, _, text in LINES]
    assert not any(pause.inside_segment for pause in as_before.pauses)
    # What was measured from the sound and the words is the same either way.
    assert as_before.pauses[0].duration_seconds == today.pauses[0].duration_seconds
    for name in ("total_word_count", "speech_active_wpm", "whole_clip_wpm", "pause_count"):
        assert getattr(as_before.metrics, name).value == getattr(today.metrics, name).value
    # With no pause inside any segment, the delivery pace is the speech-active WPM.
    assert as_before.metrics.delivery_wpm.value == as_before.metrics.speech_active_wpm.value


# --- Reading a result stored before segments could hold a pause ----------------------------

OLD = [(0.0, 2.0, "you clearly do not know"), (2.6, 5.0, "who you are talking to")]


def test_an_older_result_reads_as_one_stretch_per_segment():
    old = make_recording(OLD)
    assert old.stretches is None and not stretches.has_delivery_pace(old)
    assert [(s.index, s.segment_id) for s in stretches.stretches_of(old)] == [
        (0, "seg-1"),
        (1, "seg-2"),
    ]
    assert [stretches.stretch_index_of(old, word) for word in old.words] == [0] * 5 + [1] * 5
    assert stretches.pauses_inside(old, "seg-1") == []
    # Its one pace per segment is its delivery pace: nothing was paused inside.
    assert stretches.delivery_wpm_of(old.segments[0]) == old.segments[0].segment_wpm
    assert stretches.recording_delivery_wpm(old) == old.metrics.speech_active_wpm


def test_a_newer_result_is_read_from_what_it_stores(body):
    assert stretches.has_delivery_pace(body)
    assert stretches.stretches_of(body) is body.stretches
    assert [pause.id for pause in stretches.pauses_inside(body, "seg-1")] == ["pause-1"]
    assert stretches.pauses_inside(body, "seg-2") == []
    assert stretches.delivery_wpm_of(body.segments[0]) == 120.0


# --- A corrected transcript ----------------------------------------------------------------


def test_correcting_a_segment_with_a_pause_inside_works_both_paces_out_again(body):
    # Two words were missed in the second half of the first line.
    corrected, changed = correct_transcript(
        body, {"seg-1": "you clearly do not know who it is you are talking to"}
    )
    assert changed == ["seg-1"]
    first, second = corrected.segments
    assert first.word_count == 12
    assert first.delivery_wpm == 144.0  # 12 words / 5.0 s
    assert first.segment_wpm == 163.6  # 12 words / 4.4 s
    # The length, the pause and the other line are exactly as measured.
    assert (first.pause_count, first.pause_seconds, first.speech_active_seconds) == (1, 0.6, 4.4)
    assert second == body.segments[1]
    assert corrected.pauses == body.pauses and corrected.stretches == body.stretches
    assert corrected.metrics.delivery_wpm.value == pytest.approx(23 / (9.0 / 60), abs=0.05)


def test_corrected_words_stay_on_their_side_of_the_pause(body):
    corrected, _ = correct_transcript(
        body, {"seg-1": "you clearly do not know who it is you are talking to"}
    )
    by_stretch: dict[int, list[str]] = {}
    for word in corrected.words:
        by_stretch.setdefault(word.stretch_index, []).append(word.text)
    assert by_stretch[0] == ["you", "clearly", "do", "not", "know"]
    assert by_stretch[1] == ["who", "it", "is", "you", "are", "talking", "to"]


def test_correcting_an_older_result_leaves_it_in_the_shape_it_was_stored_in():
    old = make_recording(OLD)
    corrected, _ = correct_transcript(old, {"seg-1": "you clearly do not"})
    assert corrected.stretches is None
    assert corrected.metrics.delivery_wpm is None
    assert all(segment.delivery_wpm is None for segment in corrected.segments)
    assert all(word.stretch_index is None for word in corrected.words)
    assert corrected.segments[0].segment_wpm == 120.0  # 4 words / 2.0 s, as before


# --- "The WPM looks wrong" -----------------------------------------------------------------


def test_the_review_of_a_segment_lays_out_its_delivery_pace_and_the_pause_it_counts(body):
    review = wpm_review.review(body, "seg-1", "low")
    assert review.wpm == 120.0
    assert review.formula == (
        "10 words ÷ 5.00 s × 60 = 120.0 WPM. The 5.00 s include 1 pause, 0.60 s in all, "
        "inside the phrase. With those left out, the speaking speed is 136.4 WPM."
    )
    labels = [check.label for check in review.checks]
    assert "The pauses inside the phrase" in labels


def test_the_review_of_a_segment_with_no_pause_inside_says_all_of_it_is_speaking(body):
    review = wpm_review.review(body, "seg-2", "high")
    assert review.formula == (
        "11 words ÷ 4.00 s × 60 = 165.0 WPM. There is no pause inside the phrase, so all "
        "of that time is speaking."
    )
    assert "The pauses inside the phrase" not in [check.label for check in review.checks]
    # The pause that borders it is the one that ended the line before, not the one inside.
    speaking = next(check for check in review.checks if check.label == "The speaking time")
    assert "a pause of 1.50 s before it" in speaking.text
    assert "0.60" not in speaking.text


def test_the_review_of_the_recording_names_all_three_paces(body):
    review = wpm_review.review(body, None, "high")
    assert review.wpm == 140.0
    assert review.formula.startswith("21 words ÷ 9.00 s × 60 = 140.0 WPM.")
    which = next(check for check in review.checks if check.label == "Which WPM this is")
    assert "150.0 WPM" in which.text and "114.5 WPM" in which.text


def test_the_review_of_an_older_result_is_worded_as_it_always_was():
    old = make_recording(OLD)
    review = wpm_review.review(old, "seg-1", "high")
    assert review.formula == "5 words ÷ 2.00 s of speaking × 60 = 150.0 WPM."


# --- The comparison ------------------------------------------------------------------------


def comparing(take, reference):
    return compare(
        take,
        reference,
        DEFAULT_COMPARISON_SETTINGS,
        take_id="take-1",
        reference_id="ref-1",
        reference_title="The original",
    )


def test_a_recording_against_itself_matches_every_pause_inside_a_segment_or_not(tmp_path):
    reference = measured(tmp_path, LINES)
    take = measured(tmp_path, LINES, name="take.wav")
    result = comparing(take, reference)

    assert [(pause.status, pause.difference_seconds) for pause in result.pauses] == [
        ("both", 0.0),
        ("both", 0.0),
    ]
    assert [pause.after_words for pause in result.pauses] == [
        "you clearly do not know",
        "who you are talking to",
    ]
    assert result.differences == [] and result.settings_note is None


def test_a_pause_the_take_left_out_inside_a_line_is_reported_where_it_fell(tmp_path):
    reference = measured(tmp_path, LINES)
    # The same words, with the first line run straight through.
    take = measured(
        tmp_path,
        [
            (0.0, 4.4, "you clearly do not know who you are talking to"),
            (5.9, 9.9, "so let me clue you in I am not in danger"),
        ],
        name="take.wav",
    )
    inside, between = comparing(take, reference).pauses
    assert (inside.status, inside.after_words) == ("reference_only", "you clearly do not know")
    assert inside.reference.duration_seconds == 0.6 and inside.take is None
    assert between.status == "both"


def test_a_pause_the_take_added_inside_a_line_is_reported_where_it_fell(tmp_path):
    reference = measured(tmp_path, LINES)
    take = measured(
        tmp_path,
        [
            (0.0, 2.0, "you clearly do not know"),
            (2.6, 5.0, "who you are talking to"),
            (6.5, 8.5, "so let me clue you in"),
            (9.3, 11.3, "I am not in danger"),
        ],
        name="take.wav",
    )
    rows = comparing(take, reference).pauses
    assert [row.status for row in rows] == ["both", "both", "take_only"]
    assert rows[-1].after_words == "so let me clue you in"
    assert rows[-1].take.duration_seconds == 0.8


def test_a_lines_pace_is_its_delivery_pace_in_both_recordings(tmp_path):
    reference = measured(tmp_path, LINES)
    # The take says the first line with a longer stop inside it: 0.9 s where the
    # reference has 0.6 s. Its words are no slower.
    take = measured(
        tmp_path,
        [
            (0.0, 2.0, "you clearly do not know"),
            (2.9, 5.3, "who you are talking to"),
            (6.8, 10.8, "so let me clue you in I am not in danger"),
        ],
        name="take.wav",
    )
    first, second = comparing(take, reference).phrases
    assert first.comparable and second.comparable
    assert first.reference_wpm == 120.0  # 10 words / 5.0 s
    assert first.take_wpm == pytest.approx(10 / (5.3 / 60), abs=0.1)  # the longer stop counts
    assert second.reference_wpm == second.take_wpm == 165.0


def test_a_pause_in_the_take_long_enough_to_end_a_line_is_left_out_of_that_lines_pace(tmp_path):
    reference = measured(tmp_path, LINES)
    # The take stops for 1.4 s where the reference stops for 0.6 s. That is listed with the
    # pauses; it is not also counted as the line having been said slowly.
    take = measured(
        tmp_path,
        [
            (0.0, 2.0, "you clearly do not know"),
            (3.4, 5.8, "who you are talking to"),
            (7.3, 11.3, "so let me clue you in I am not in danger"),
        ],
        name="take.wav",
    )
    result = comparing(take, reference)
    assert result.phrases[0].take_wpm == pytest.approx(10 / (4.4 / 60), abs=0.1)
    assert (result.pauses[0].status, result.pauses[0].difference_seconds) == ("both", 0.8)


def test_comparing_an_older_result_with_a_newer_one_says_the_phrases_are_not_like_for_like(
    tmp_path,
):
    reference = measured(tmp_path, LINES)
    old_take = make_recording(LINES)
    result = comparing(old_take, reference)

    # The pauses are found the same way in both, so they still match.
    assert [pause.status for pause in result.pauses] == ["both", "both"]
    assert "ended a phrase at every pause" in result.settings_note
    assert "only at a pause of 1 second or more" in result.settings_note
    # Each recording's delivery pace is its own: for the older one, its only pace.
    pace = next(row for row in result.metrics if row.metric == "deliveryWpm")
    assert pace.reference == 140.0
    assert pace.take == old_take.metrics.speech_active_wpm.value


# --- The coaching --------------------------------------------------------------------------


def find(body, kind):
    return next(f for f in build_findings(body, SETTINGS).findings if f.kind == kind)


def test_pace_is_judged_on_the_delivery_pace_and_the_speaking_speed_is_stated_beside_it(body):
    pace = find(body, "pace")
    assert pace.statement == (
        "Your delivery pace was 140 WPM: your words over the length of your phrases, "
        "counting the short pauses inside them. That is a moderate pace: between 125 and "
        "175 WPM. 1 pause inside your phrases took 0.6 seconds; with those left out, the "
        "words themselves were said at 150 WPM."
    )
    assert pace.evidence[0].id == "deliveryWpm"


def test_an_older_result_is_judged_on_its_speaking_pace_with_the_bands_for_that(body):
    old = make_recording(LINES, speech_active_wpm=180.0)
    pace = find(old, "pace")
    assert pace.statement.startswith("You spoke at 180 WPM while speaking (pauses left out).")
    assert "between 140 and 200 WPM" in pace.statement
    assert pace.evidence[0].id == "speechActiveWpm"


def test_the_pause_finding_says_how_many_fell_inside_a_phrase(body):
    assert find(body, "pause_length").statement.startswith(
        "2 pauses of 0.5 seconds or more, with a median of 1.1 seconds. 1 of them fell "
        "inside a phrase and 1 was long enough to end one."
    )


def test_the_longest_pause_is_placed_inside_or_between_segments(tmp_path, body):
    assert "between segments 1 and 2" in find(body, "held_silence").statement
    only_inside = measured(tmp_path, LINES[:2], name="one-line.wav")
    assert "inside segment 1" in find(only_inside, "held_silence").statement


FAST = [
    (0.0, 4.0, "one two three four five six seven eight nine ten eleven twelve thirteen"),
    (5.5, 9.5, "one two three four five six seven eight nine ten eleven twelve thirteen"),
    (11.0, 15.0, "one two three four five six seven eight nine ten eleven twelve thirteen"),
]


def test_a_fast_delivery_is_slowed_with_pauses_not_with_slower_words(tmp_path):
    fast = measured(tmp_path, FAST)  # 195 WPM, and no pause inside any line
    assert fast.metrics.delivery_wpm.value == 195.0
    finding_set = build_findings(fast, SETTINGS)
    plan = rules.plan(fast, finding_set, profile_wants(fast.profile), SETTINGS)
    first = plan.corrections[0]
    assert first.title == "Slow the delivery with pauses"
    assert "at your normal speaking speed" in first.drill
    assert "Do not stretch the words" in first.drill
    assert "half your normal speed" not in first.drill
    # The stop asked for is a short one: a second of silence would end the phrase, and a
    # pause that ends a phrase is not counted in its delivery pace.
    assert "one short beat" in first.drill and "one thousand one" not in first.drill
    assert plan.next_take[0] == (
        "Bring your delivery pace down towards 175 WPM or below, by pausing inside your phrases."
    )


def test_an_older_result_keeps_the_advice_that_fits_the_pace_it_has():
    old = make_recording(LINES, speech_active_wpm=230.0)
    finding_set = build_findings(old, SETTINGS)
    plan = rules.plan(old, finding_set, profile_wants(old.profile), SETTINGS)
    assert plan.corrections[0].title == "Slow your overall pace"
    assert plan.next_take[0] == "Bring your speaking pace down towards 200 WPM or below."


def test_a_phrase_slow_because_of_its_pauses_is_run_through_not_hurried(tmp_path):
    # Three lines at 150 WPM, and a fourth with the same words broken by two 0.9 s stops.
    line = "one two three four five six seven eight nine ten"
    slow = measured(
        tmp_path,
        [
            (0.0, 4.0, line),
            (5.5, 9.5, line),
            (11.0, 15.0, line),
            (16.5, 18.0, "one two three four"),
            (18.9, 20.0, "five six seven"),
            (20.9, 22.3, "eight nine ten"),
        ],
        profile="walter_white",
    )
    last = slow.segments[-1]
    assert (last.pause_count, last.pace_vs_typical) == (2, "slower")
    assert last.segment_wpm == 150.0  # the words themselves were no slower
    finding = find(slow, "slow_segment")
    assert finding.statement.endswith("It holds 2 pauses, 1.8 seconds in all.")
    finding_set = build_findings(slow, SETTINGS)
    plan = rules.plan(slow, finding_set, profile_wants(slow.profile), SETTINGS)
    titles = [correction.title for correction in plan.corrections]
    assert "Run this phrase through" in titles


def test_the_model_is_shown_the_pauses_inside_a_phrase_under_its_line(body):
    finding_set = build_findings(body, SETTINGS)
    prompt = build_prompt(
        body, finding_set, profile_wants(body.profile), SETTINGS, context_tokens=8192
    )
    shown = prompt.facts_text
    lines = (
        'seg-1 [0:00.0-0:05.0] 120 WPM: "you clearly do not know who you are talking to"',
        "  (inside seg-1, pause-1: 0.6 seconds of silence after “do not know”)",
        "(pause-2: 1.5 seconds of silence)",
        'seg-2 [0:06.5-0:10.5] 165 WPM: "so let me clue you in I am not in danger"',
    )
    assert "\n".join(lines) in shown
    assert "ended by a pause of 1 second or more" in shown
    assert "unhurried under 125 WPM and fast over 175 WPM" in shown


def test_the_models_bands_for_an_older_result_are_the_ones_it_is_judged_by():
    old = make_recording(LINES)
    prompt = build_prompt(
        old,
        build_findings(old, SETTINGS),
        profile_wants(old.profile),
        SETTINGS,
        context_tokens=8192,
    )
    assert "unhurried under 140 WPM and fast over 200 WPM" in prompt.facts_text


# --- Feedback on a pause -------------------------------------------------------------------


def report(body, category: str, pause_id: str):
    request = schemas.FeedbackRequest(category=category, target_id=pause_id)
    return classify(request, body, None)


def test_a_pause_inside_a_phrase_cannot_be_reported_as_having_split_it(body):
    with pytest.raises(FeedbackError) as refused:
        report(body, "split_wrong", "pause-1")
    assert (refused.value.status, refused.value.code) == (422, "not_a_split")


def test_a_pause_inside_a_phrase_can_still_be_labelled_or_reported_as_not_a_pause(body):
    assert report(body, "pause_accidental", "pause-1").setting is None
    false_pause = report(body, "pause_false", "pause-1")
    # 0.6 s is short enough that a higher minimum pause would no longer report it.
    assert (false_pause.setting, false_pause.direction) == ("min_pause_ms", 1)


def test_saying_a_pause_should_not_have_ended_the_phrase_is_kept_and_moves_no_setting(body):
    kept = report(body, "split_wrong", "pause-2")
    assert kept.setting is None
    assert kept.features["no_vote"] == "fixed_break"
    assert kept.features["segment_break_ms"] == 1000


def test_in_an_older_result_a_short_pause_can_still_be_reported_as_a_wrong_split():
    old = make_recording(LINES)
    wrong = report(old, "split_wrong", "pause-1")
    assert (wrong.setting, wrong.direction) == ("min_pause_ms", 1)


# --- Through the API -----------------------------------------------------------------------


def test_the_result_is_served_with_its_stretches_and_both_paces(client, store_result, body):
    analysis_id = store_result(body)
    result = client.get(f"/api/analyses/{analysis_id}").json()

    first = result["segments"][0]
    assert (first["deliveryWpm"], first["segmentWpm"]) == (120.0, 136.4)
    assert (first["pauseCount"], first["pauseSeconds"]) == (1, 0.6)
    assert [pause["insideSegment"] for pause in result["pauses"]] == [True, False]
    assert [stretch["segmentId"] for stretch in result["stretches"]] == ["seg-1", "seg-1", "seg-2"]
    assert result["words"][5]["stretchIndex"] == 1
    assert result["metrics"]["deliveryWpm"]["value"] == 140.0
    # The history row carries the delivery pace too, for comparing one attempt with another.
    (row,) = client.get("/api/analyses").json()["items"]
    assert row["metrics"]["deliveryWpm"]["value"] == 140.0


def test_an_older_result_is_served_without_them_and_still_lists(client, store_result):
    analysis_id = store_result(make_recording(LINES))
    result = client.get(f"/api/analyses/{analysis_id}").json()
    assert result["stretches"] is None
    assert result["metrics"]["deliveryWpm"] is None
    assert result["segments"][0]["deliveryWpm"] is None
    (row,) = client.get("/api/analyses").json()["items"]
    assert "deliveryWpm" not in row["metrics"]
