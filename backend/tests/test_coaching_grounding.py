"""Checking the language model's wording against what was measured."""

import pytest

from app.coaching.grounding import collect_facts, find_figures, find_timecodes, problems_in

SHOWN_TO_MODEL = """seg-1 [0:00.0-0:04.1] 236 WPM: "You clearly do not know who you are talking to"
(pause-1: 1.3 seconds of silence)
seg-2 [0:05.4-0:08.6]: "I am the danger."
BANDS: pace is fast over 200 WPM. A held silence is 2 seconds or more.
f1: You spoke at 240 WPM. Pauses make up 32% of the recording. Loudness varied by 5.2 dB.
f2: Pitch varied by 2.3 semitones. Median pitch 181 Hz. The longest pause is at 0:08.6."""

TRANSCRIPT = (
    "You clearly do not know who you are talking to, so let me clue you in. "
    "I am the one who knocks. मैं खतरे में नहीं हूँ स्काइलर"
)


@pytest.fixture
def facts():
    return collect_facts(SHOWN_TO_MODEL, segment_count=6, pause_count=5, transcript=TRANSCRIPT)


def test_the_allowed_figures_are_read_from_what_the_model_was_shown(facts):
    assert facts.figures == {
        "wpm": [236.0, 200.0, 240.0],
        "seconds": [1.3, 2.0],
        "db": [5.2],
        "semitones": [2.3],
        "hz": [181.0],
        "percent": [32.0],
    }
    assert facts.timecodes == [0.0, 4.1, 5.4, 8.6, 8.6]


@pytest.mark.parametrize(
    "text",
    [
        "Slow down from 240 WPM.",
        "You were near 240 words per minute.",
        "About 235 wpm is still fast.",  # within 3% of a measured figure
        "Hold the pause for 2 seconds.",
        "Hold a two-second pause.",
        "That pause of 1.3s works.",
        "Loudness moved by 5.2 dB and pitch by 2.3 semitones around 181 Hz.",
        "Pauses were 32% of it. Give the next take 100%.",
        "Repeat 3 times, then count to 5.",  # counts in a drill are not measurements
        "Take 2 steps back and say it 4 times.",
    ],
)
def test_figures_copied_from_the_measurements_pass(facts, text):
    assert problems_in(text, facts) == []


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Aim for 150 WPM.", "“150 WPM” is not one of the measured figures"),
        (
            "You hit 180 words per minute.",
            "“180 words per minute” is not one of the measured figures",
        ),
        ("Hold for 3 seconds.", "“3 seconds” is not one of the measured figures"),
        ("Hold a five-second pause.", "“five-second” is not one of the measured figures"),
        ("Leave a 500 ms gap.", "“500 ms” is not one of the measured figures"),
        ("Lift it by 6 dB.", "“6 dB” is not one of the measured figures"),
        ("Your pitch sat at 120 Hz.", "“120 Hz” is not one of the measured figures"),
        ("Move it 4 semitones.", "“4 semitones” is not one of the measured figures"),
        ("Pauses were 50% of it.", "“50%” is not one of the measured figures"),
    ],
)
def test_invented_figures_are_caught(facts, text, problem):
    assert problems_in(text, facts) == [problem]


def test_a_figure_only_matches_its_own_unit(facts):
    # 2.3 was measured in semitones, not in seconds.
    assert problems_in("Wait 2.3 semitones.", facts) == []
    assert problems_in("Hold it for 5.2 seconds.", facts) == [
        "“5.2 seconds” is not one of the measured figures"
    ]


def test_times_must_be_ones_that_appear_in_the_measurements(facts):
    assert problems_in("At 0:08 you paused, and again at 0:05.4.", facts) == []
    assert problems_in("At 1:15 you rushed.", facts) == [
        "“1:15” is not a time that appears in the measurements"
    ]
    assert find_timecodes("from 0:04.7 to 12:03.0") == [(4.7, "0:04.7"), (723.0, "12:03.0")]


def test_segments_and_pauses_must_exist(facts):
    assert problems_in("Segment 4 and seg-2 are fine, as is pause 5.", facts) == []
    assert problems_in("Segment 9 was rushed after pause 7.", facts) == [
        "there is no segment 9",
        "there is no pause 7",
    ]


@pytest.mark.parametrize(
    "text",
    [
        'Say "You clearly do not know who" slowly.',
        "Say 'I am the one who knocks' twice.",
        "Say “You clearly do not know…” at half speed.",
        "Shelby's pace isn't the actor's own; say 'मैं खतरे में नहीं हूँ' twice.",
        "Count 'one thousand one, one thousand two' silently.",  # counting, not a quotation
        "Stress the word 'danger' and the words 'who knocks'.",  # too short to judge
    ],
)
def test_words_quoted_from_the_transcript_pass(facts, text):
    assert problems_in(text, facts) == []


def test_words_that_were_never_said_are_caught(facts):
    assert problems_in("Say 'I am the one one who knocks' slowly.", facts) == [
        "the quoted words “I am the one one who knocks” are not in the transcript"
    ]
    assert problems_in("Say “मैं बहुत खतरे में हूँ अभी” twice.", facts) == [
        "the quoted words “मैं बहुत खतरे में हूँ अभी” are not in the transcript"
    ]


def test_any_long_quotation_fails_when_there_is_no_transcript():
    facts = collect_facts("f1: 240 WPM", segment_count=1, pause_count=0, transcript=None)
    assert problems_in("Say 'this line was never heard at all' again.", facts)


def test_units_are_recognised_in_their_common_spellings():
    found = {
        (f.unit, f.value) for f in find_figures("3 secs, 1.5s, 40 percent, 12 decibels, 200ms")
    }
    assert found == {
        ("seconds", 3.0),
        ("seconds", 1.5),
        ("percent", 40.0),
        ("db", 12.0),
        ("seconds", 0.2),
    }
    # Not units: "s" must not be read out of an ordinary word.
    assert find_figures("5 steps, 3 sentences, 2 sides") == []
