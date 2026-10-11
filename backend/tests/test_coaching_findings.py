"""Findings: the plain statements of fact that all coaching is built on."""

import pytest

from app import schemas
from app.coaching.findings import band, build_findings, profile_wants, timecode
from app.coaching.grounding import find_figures
from app.coaching.settings import DEFAULT_COACHING_SETTINGS, CoachingSettings
from tests.conftest import make_body, make_pause, make_segment, metric

SETTINGS = DEFAULT_COACHING_SETTINGS


def find(body: schemas.AnalysisBody, kind: str) -> schemas.Finding | None:
    return next((f for f in build_findings(body, SETTINGS).findings if f.kind == kind), None)


def find_all(body: schemas.AnalysisBody, kind: str) -> list[schemas.Finding]:
    return [f for f in build_findings(body, SETTINGS).findings if f.kind == kind]


def test_a_value_falls_into_the_low_moderate_or_high_band():
    assert band(1.9, 2.0, 4.0) == "low"
    assert band(2.0, 2.0, 4.0) == "moderate"
    assert band(3.99, 2.0, 4.0) == "moderate"
    assert band(4.0, 2.0, 4.0) == "high"
    # With one threshold there is no middle band.
    assert band(0.99, 1.0, 1.0) == "low"
    assert band(1.0, 1.0, 1.0) == "high"


def test_positions_are_written_the_way_the_screen_writes_them():
    assert timecode(0) == "0:00.0"
    assert timecode(4.706) == "0:04.7"
    assert timecode(59.96) == "1:00.0"
    assert timecode(723.04) == "12:03.0"


def test_each_profile_states_which_way_it_leans():
    assert profile_wants("walter_white") == {
        "pace_variation": "low",
        "pause_length": "high",
        "loudness_variation": "low",
    }
    assert profile_wants("joker") == {
        "pace_variation": "high",
        "pitch_variation": "high",
        "loudness_variation": "high",
    }
    assert profile_wants("thomas_shelby") == {
        "pace": "low",
        "held_silence": "high",
        "loudness_variation": "low",
    }
    assert profile_wants("custom") == {}


# --- Pace --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("wpm", "level", "phrase"),
    [
        (120.0, "low", "unhurried: under 140 WPM"),
        (160.0, "moderate", "between 140 and 200 WPM"),
        (223.1, "high", "fast: over 200 WPM"),
    ],
)
def test_the_overall_pace_is_described_with_its_band(wpm, level, phrase):
    finding = find(make_body(speech_active_wpm=wpm), "pace")
    assert finding.level == level
    assert finding.statement.startswith(f"You spoke at {wpm:.0f} WPM while speaking")
    assert phrase in finding.statement
    assert finding.evidence[0].id == "speechActiveWpm"


def test_a_fast_pace_is_an_issue_for_anyone_and_an_unhurried_one_suits_shelby():
    assert find(make_body("custom", speech_active_wpm=230), "pace").role == "issue"
    assert find(make_body("custom", speech_active_wpm=160), "pace").role == "context"
    assert find(make_body("thomas_shelby", speech_active_wpm=120), "pace").role == "strength"
    assert find(make_body("thomas_shelby", speech_active_wpm=160), "pace").role == "issue"


def test_a_pace_built_on_uncertain_words_is_called_an_estimate():
    body = make_body(speech_active_wpm=metric(160.0, "words/minute", "estimated"))
    assert "treat it as an estimate" in find(body, "pace").statement
    assert "estimate" not in find(make_body(), "pace").statement


def test_no_pace_finding_without_a_measured_pace():
    assert find(make_body(speech_active_wpm=None), "pace") is None


# --- Pace variation ----------------------------------------------------------------------


def test_pace_variation_is_given_as_a_share_of_the_typical_pace():
    finding = find(make_body(pace_variation=24.0, typical_segment_wpm=150.0), "pace_variation")
    assert finding.level == "moderate"
    assert "varied by 24 WPM around your typical 150 WPM, which is 16%" in finding.statement
    assert "Slowest: segment 4 at 120 WPM. Fastest: segment 3 at 340 WPM." in finding.statement
    assert [e.id for e in finding.evidence] == ["paceVariation", "seg-4", "seg-3"]


def test_the_same_variation_is_a_strength_or_an_issue_depending_on_the_profile():
    even = {"pace_variation": 9.0, "typical_segment_wpm": 150.0}  # 6%
    wide = {"pace_variation": 60.0, "typical_segment_wpm": 150.0}  # 40%
    assert find(make_body("walter_white", **even), "pace_variation").role == "strength"
    assert find(make_body("walter_white", **wide), "pace_variation").role == "issue"
    assert find(make_body("joker", **even), "pace_variation").role == "issue"
    assert find(make_body("joker", **wide), "pace_variation").role == "strength"
    assert find(make_body("custom", **wide), "pace_variation").role == "context"


def test_pace_variation_is_not_judged_without_a_typical_pace():
    result = build_findings(make_body(typical_segment_wpm=None), SETTINGS)
    assert all(f.kind != "pace_variation" for f in result.findings)
    assert any("how even your pace is was not assessed" in caveat for caveat in result.caveats)


# --- Pauses ------------------------------------------------------------------------------


def test_short_pauses_are_an_issue_only_for_a_profile_built_on_pauses():
    short = {"median_pause_seconds": 0.7}
    finding = find(make_body("walter_white", **short), "pause_length")
    assert (finding.level, finding.role) == ("low", "issue")
    assert "3 pauses of 0.5 seconds or more, with a median of 0.7 seconds" in finding.statement
    assert "short: under 1 second" in finding.statement
    assert "Pauses make up 10% of the recording" in finding.statement
    assert find(make_body("custom", **short), "pause_length").role == "context"


def test_pauses_long_enough_to_register_suit_walter_white():
    finding = find(make_body("walter_white", median_pause_seconds=1.6), "pause_length")
    assert (finding.level, finding.role) == ("high", "strength")
    assert "long enough to register: 1 second or more" in finding.statement


def test_no_pause_at_all_is_remarked_on_only_in_a_longer_stretch_of_speech():
    one_phrase = [make_segment(0, 0.0, 20.0, "word " * 40)]
    finding = find(make_body(segments=one_phrase, pauses=[]), "no_pauses")
    assert finding.role == "issue"
    assert (
        finding.statement == "No pause of 0.5 seconds or more was detected in 20 seconds of speech."
    )

    short_phrase = [make_segment(0, 0.0, 6.0, "word " * 12)]
    result = build_findings(make_body(segments=short_phrase, pauses=[]), SETTINGS)
    assert not any(f.kind in ("no_pauses", "pause_length") for f in result.findings)


def test_the_longest_pause_is_located_and_judged_as_a_held_silence():
    segments = [
        make_segment(0, 0.0, 4.0, "one two three four five"),
        make_segment(1, 7.2, 11.0, "six seven eight nine ten"),
    ]
    held = make_body("thomas_shelby", segments=segments, pauses=[make_pause(0, 4.0, 7.2)])
    finding = find(held, "held_silence")
    assert (finding.level, finding.role) == ("high", "strength")
    assert finding.statement == (
        "The longest pause is 3.2 seconds, at 0:04.0, between segments 1 and 2. "
        "That is a held silence: 2 seconds or more."
    )
    assert finding.evidence[0].model_dump() == {
        "kind": "pause",
        "id": "pause-1",
        "label": "Pause at 0:04.0",
        "start_seconds": 4.0,
        "end_seconds": 7.2,
    }


def test_a_missing_held_silence_matters_for_shelby_and_nobody_else():
    assert find(make_body("thomas_shelby"), "held_silence").role == "issue"
    assert find(make_body("walter_white"), "held_silence").role == "context"
    assert find(make_body("custom"), "held_silence").role == "context"


# --- Voice -------------------------------------------------------------------------------


def test_loudness_variation_is_judged_against_the_profile():
    assert find(make_body("walter_white", energy_variation=2.0), "loudness_variation").role == (
        "strength"
    )
    moderate = find(make_body("walter_white", energy_variation=4.5), "loudness_variation")
    assert (moderate.level, moderate.role) == ("moderate", "issue")
    assert moderate.statement == (
        "Loudness varied by 4.5 dB across your speech. That is moderate: between 3 and 6 dB."
    )
    assert find(make_body("joker", energy_variation=7.0), "loudness_variation").role == "strength"
    assert find(make_body("custom", energy_variation=7.0), "loudness_variation").role == "context"


def test_a_narrow_pitch_is_an_issue_for_anyone_and_a_wide_one_a_strength():
    narrow = find(make_body("custom", pitch_variation_semitones=1.4), "pitch_variation")
    assert (narrow.level, narrow.role) == ("low", "issue")
    assert "narrow range: under 2 semitones" in narrow.statement
    assert find(make_body("custom", pitch_variation_semitones=5.0), "pitch_variation").role == (
        "strength"
    )
    assert find(make_body("custom", pitch_variation_semitones=3.0), "pitch_variation").role == (
        "context"
    )


def test_unmeasured_pitch_produces_no_finding():
    assert find(make_body(pitch_variation_semitones=None), "pitch_variation") is None


# --- Single phrases ----------------------------------------------------------------------


def test_a_rushed_phrase_is_reported_with_its_place_and_its_distance_from_typical():
    finding = find(make_body("custom"), "fast_segment")
    assert finding.role == "issue"
    assert finding.statement == (
        "Segment 3 (0:09.3 to 0:12.3) ran at 340 WPM, 127% faster than your typical 150 WPM."
    )
    assert [(e.kind, e.id, e.start_seconds, e.end_seconds) for e in finding.evidence] == [
        ("segment", "seg-3", 9.3, 12.3)
    ]


def test_a_change_of_pace_is_a_strength_for_a_profile_built_on_contrast():
    assert find(make_body("joker"), "fast_segment").role == "strength"
    assert find(make_body("walter_white"), "fast_segment").role == "issue"


def test_a_slow_phrase_matters_only_when_the_profile_wants_an_even_pace():
    def body(profile: str) -> schemas.AnalysisBody:
        segments = make_body().segments
        segments[2].pace_vs_typical = None
        segments[3].pace_vs_typical = "slower"
        segments[3].segment_wpm = 90.0
        return make_body(profile, segments=segments)

    assert find(body("walter_white"), "slow_segment").role == "issue"
    assert find(body("custom"), "slow_segment").role == "context"
    assert "40% slower than your typical 150 WPM" in find(body("custom"), "slow_segment").statement


def test_only_the_two_phrases_furthest_from_typical_are_reported():
    segments = [
        make_segment(i, i * 5.0, i * 5.0 + 4.0, "word " * 10, pace_vs_typical="faster")
        for i in range(4)
    ]
    for segment, wpm in zip(segments, (200.0, 260.0, 230.0, 300.0), strict=True):
        segment.segment_wpm = wpm
    found = find_all(make_body(segments=segments), "fast_segment")
    assert [f.evidence[0].id for f in found] == ["seg-4", "seg-2"]


def test_hesitation_sounds_are_listed_with_where_they_were():
    body = make_body(
        hesitations=[
            schemas.Hesitation(text="um", start_seconds=5.2),
            schemas.Hesitation(text="uh", start_seconds=10.0),
        ]
    )
    finding = find(body, "hesitations")
    assert finding.role == "issue"
    assert finding.statement.startswith(
        '2 hesitation sounds recognised: "um" at 0:05.2, "uh" at 0:10.0.'
    )
    assert [e.id for e in finding.evidence] == ["seg-2", "seg-3"]


def emphasised(text: str, start: float) -> schemas.EmphasisCandidate:
    return schemas.EmphasisCandidate(
        text=text,
        start_seconds=start,
        end_seconds=start + 0.4,
        segment_id=None,
        reasons=["louder"],
        energy_delta_db=4.0,
        pitch_delta_semitones=None,
    )


def test_words_that_stood_out_are_a_strength_unless_the_profile_is_restrained():
    candidates = [emphasised("danger", 10.0)]
    finding = find(make_body("custom", emphasis_candidates=candidates), "emphasis")
    assert finding.role == "strength"
    assert "1 word stood out" in finding.statement and '"danger" at 0:10.0' in finding.statement
    assert "candidates for emphasis, not proof" in finding.statement
    assert find(make_body("walter_white", emphasis_candidates=candidates), "emphasis").role == (
        "context"
    )


def test_a_long_list_of_examples_is_cut_to_three():
    candidates = [emphasised(f"w{i}", float(i)) for i in range(5)]
    statement = find(make_body(emphasis_candidates=candidates), "emphasis").statement
    assert '"w0" at 0:00.0, "w1" at 0:01.0, "w2" at 0:02.0, and 2 more' in statement


def test_no_word_standing_out_matters_only_for_an_expressive_profile():
    assert find(make_body("joker"), "no_emphasis").role == "issue"
    assert find(make_body("custom"), "no_emphasis").role == "context"
    # Too few words to say anything about emphasis.
    few = make_body("joker", segments=[make_segment(0, 0.0, 4.0, "only five words spoken here")])
    assert find(few, "no_emphasis") is None


# --- The set as a whole ------------------------------------------------------------------


def test_issues_come_out_most_important_first_and_ids_are_stable():
    body = make_body(
        "walter_white",
        speech_active_wpm=230.0,  # fast: an issue for anyone (0.8)
        pace_variation=60.0,  # widely varied, against the profile (1.0)
        energy_variation=4.5,  # partway (0.5)
        median_pause_seconds=1.5,
    )
    result = build_findings(body, SETTINGS)
    assert [f.id for f in result.findings] == [f"f{i}" for i in range(1, len(result.findings) + 1)]
    assert [f.kind for f in result.issues] == [
        "pace_variation",
        "pace",
        "fast_segment",
        "loudness_variation",
    ]
    assert [f.kind for f in result.strengths] == ["pause_length"]


def test_the_summary_always_has_four_lines_even_when_little_was_measured():
    full = build_findings(make_body(), SETTINGS).summary
    assert [line.label for line in full] == ["Pace", "Pauses", "Voice", "Clarity"]
    assert "average confidence in your words was 90%" in full[3].text

    empty = make_body(
        segments=[],
        pauses=[],
        words=[],
        speech_active_wpm=None,
        pace_variation=None,
        typical_segment_wpm=None,
        pause_count=None,
        energy_variation=None,
        pitch_variation_semitones=None,
    )
    result = build_findings(empty, SETTINGS)
    assert result.findings == []
    assert [line.text for line in result.summary] == [
        "Pace could not be measured.",
        "No pauses were detected.",
        "Loudness and pitch could not be measured.",
        "Clarity is not measured, and no words were recognised to judge it by.",
    ]


def test_what_is_uncertain_or_unmeasured_is_always_spelled_out():
    body = make_body(
        "walter_white",
        warnings=[schemas.AnalysisWarning(code="noisy", message="The background is loud.")],
    )
    caveats = build_findings(body, SETTINGS).caveats
    assert caveats[0] == "The background is loud."
    assert "Part of this profile that the app cannot measure: clarity of consonants." in caveats
    assert caveats[-1].startswith("Breaths are not detected")


def test_every_figure_in_a_statement_is_a_measurement_or_a_band():
    """Statements may only contain numbers that code put there from known values."""
    body = make_body("walter_white", speech_active_wpm=223.1, energy_variation=5.3)
    known = {223.0, 5.3, 24.0, 150.0, 16.0, 120.0, 340.0, 0.5, 0.7, 10.0, 0.8, 3.0, 127.0, 90.0}
    known |= {140.0, 200.0, 25.0, 1.0, 2.0, 6.0, 4.0}  # the bands
    for finding in build_findings(body, SETTINGS).findings:
        for figure in find_figures(finding.statement):
            assert figure.value in known, (finding.statement, figure)


def test_bands_must_be_in_order():
    with pytest.raises(ValueError):
        CoachingSettings(slow_wpm=200, fast_wpm=140)
    with pytest.raises(ValueError):
        CoachingSettings(held_silence_seconds=0)
    assert CoachingSettings().to_dict()["version"] == 1
