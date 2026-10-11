"""What is sent to the language model, and the shape its answer is held to."""

from app.coaching.findings import build_findings, profile_wants
from app.coaching.prompt import SYSTEM, build_prompt, estimate_tokens
from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from tests.conftest import make_body, make_pause, make_segment

SETTINGS = DEFAULT_COACHING_SETTINGS


def prompt_for(body, context_tokens: int = 8192):
    found = build_findings(body, SETTINGS)
    return build_prompt(
        body, found, profile_wants(body.profile), SETTINGS, context_tokens=context_tokens
    ), found


def test_the_model_is_shown_the_profile_the_transcript_and_the_findings():
    prompt, _ = prompt_for(make_body("walter_white", speech_active_wpm=230.0))
    system, user = prompt.messages
    assert (system.role, user.role) == ("system", "user")
    assert system.content == SYSTEM
    text = user.content

    assert "DELIVERY PROFILE: Walter White. Controlled and deliberate." in text
    assert "Not measured by this app, so do not comment on it: clarity of consonants." in text
    assert "RECORDING: 17.3 seconds long. Language: English." in text
    # One line per phrase, with the pause that follows it.
    assert 'seg-1 [0:00.0-0:04.0] 150 WPM: "You clearly do not know who you are talking to"' in text
    assert "(pause-1: 0.6 seconds of silence)" in text
    assert "BANDS" in text and "fast over 200 WPM" in text
    # Issues carry the direction and method, so the model cannot coach the wrong way round.
    assert "f1: You spoke at 230 WPM while speaking" in text
    assert "    Aim: Slow your overall pace. Technique: half speed with stretched vowels" in text
    assert (
        text.index("Issues, most important first")
        < text.index("Strengths (")
        < text.index("Context (for your information")
    )
    assert text.rstrip().endswith("Answer in JSON.")


def test_the_instructions_forbid_what_was_not_measured():
    for phrase in (
        "You did not hear the recording",
        "Never state a number, a time or a measurement that is not written in them",
        "Do not mention breathing, emotion, pronunciation, accent",
        "Never say or imply that the recording was compared with the character's real voice",
    ):
        assert " ".join(phrase.split()) in " ".join(SYSTEM.split())


def test_cautions_about_the_measurements_are_passed_on():
    from app import schemas

    body = make_body(
        warnings=[schemas.AnalysisWarning(code="noisy", message="The background is loud.")]
    )
    prompt, _ = prompt_for(body)
    assert (
        "Cautions about the measurements:\n- The background is loud." in prompt.messages[1].content
    )


def test_with_no_profile_the_model_is_told_to_coach_in_general():
    prompt, _ = prompt_for(make_body("custom", speech_active_wpm=230.0))
    assert "DELIVERY PROFILE: none chosen." in prompt.messages[1].content


def test_the_answer_may_only_name_findings_and_segments_that_exist():
    body = make_body("walter_white", speech_active_wpm=230.0, median_pause_seconds=1.6)
    prompt, found = prompt_for(body)
    corrections = prompt.schema["properties"]["corrections"]
    working = prompt.schema["properties"]["working"]

    issue_ids = [f.id for f in found.issues]
    assert corrections["items"]["properties"]["finding"]["enum"] == issue_ids == prompt.issue_ids
    assert corrections["items"]["properties"]["segment"]["enum"] == [
        "seg-1",
        "seg-2",
        "seg-3",
        "seg-4",
    ]
    assert corrections["minItems"] == corrections["maxItems"] == 3
    assert working["items"]["properties"]["finding"]["enum"] == [f.id for f in found.strengths]
    assert (working["minItems"], working["maxItems"]) == (1, 1)
    # The model is not asked for next-take targets: those are written by template.
    assert set(prompt.schema["properties"]) == {"corrections", "working"}


def test_fewer_issues_means_fewer_corrections_and_no_strengths_means_none_to_name():
    body = make_body("custom")  # one rushed phrase, nothing else
    prompt, found = prompt_for(body)
    assert len(found.issues) == 1 and found.strengths == []
    corrections = prompt.schema["properties"]["corrections"]
    assert corrections["minItems"] == corrections["maxItems"] == 1
    assert prompt.schema["properties"]["working"] == {"type": "array", "maxItems": 0}
    assert "there is 1 issue; write the correction for it." in prompt.messages[1].content
    assert "leave this list empty" in prompt.messages[1].content


def test_hindi_is_counted_as_more_tokens_per_character_than_english():
    english = "I am not in danger Skylar I am the danger"
    hindi = "मैं खतरे में नहीं हूँ स्काइलर मैं ही खतरा हूँ"
    assert estimate_tokens(english) == 12
    assert estimate_tokens(hindi) > 2 * estimate_tokens(english)


def test_digits_and_punctuation_are_counted_as_a_token_each():
    # Timings and figures cost the model far more than letters do; a transcript listing is
    # full of them, so guessing from letters alone would let a long one overflow.
    assert estimate_tokens("0:15.7") == 6
    assert estimate_tokens("[0:15.7-0:17.8] 209 WPM") == 20
    assert estimate_tokens("about two seconds in") == 6


def test_the_size_guess_stays_above_what_the_model_really_counted():
    """Real token counts from llama3.1:8b for three pieces of text, measured once by hand."""
    listing = (
        'seg-1 [0:00.0-0:04.1] 236 WPM: "You clearly do not know who you are talking to, so '
        'let me clue you in."\n(pause-1: 1.3 seconds of silence)'
    )
    measured = {
        listing: 54,
        "I am not in danger Skylar I am the danger " * 12: 134,
        "मैं खतरे में नहीं हूँ स्काइलर मैं ही खतरा हूँ " * 8: 178,
    }
    for text, real_count in measured.items():
        assert real_count <= estimate_tokens(text) <= real_count * 1.25


def long_recording(phrases: int, words_each: int):
    segments = [
        make_segment(i, i * 6.0, i * 6.0 + 5.0, " ".join(f"word{n}" for n in range(words_each)))
        for i in range(phrases)
    ]
    pauses = [make_pause(i, i * 6.0 + 5.0, (i + 1) * 6.0) for i in range(phrases - 1)]
    return make_body("walter_white", segments=segments, pauses=pauses)


def test_a_long_recording_gives_up_its_timings_before_any_of_its_words():
    """Timings cost the model more than words do, so they are trimmed first."""
    phrases = [
        make_segment(i, i * 6.0, i * 6.0 + 5.0, "these are the words of one whole phrase")
        for i in range(40)
    ]
    # Every other pause is too short to register.
    pauses = [make_pause(i, i * 6.0 + 5.0, i * 6.0 + (5.6 if i % 2 else 6.0)) for i in range(39)]
    body = make_body("walter_white", segments=phrases, pauses=pauses)

    roomy, _ = prompt_for(body, context_tokens=8192)
    assert 'seg-2 [0:06.0-0:11.0] 96 WPM: "these are the words of one whole phrase"' in (
        roomy.messages[1].content
    )
    assert "(pause-1: 1 second of silence)" in roomy.messages[1].content

    tight, _ = prompt_for(body, context_tokens=4000)
    text = tight.messages[1].content
    # Start time only, no WPM, and every word still there.
    assert 'seg-2 [0:06.0]: "these are the words of one whole phrase"' in text
    assert "WPM:" not in text.split("BANDS")[0].split("TRANSCRIPT")[1]
    # Pauses long enough to register are kept; shorter ones are dropped.
    assert "(pause, 1 second)" in text and "0.6 seconds" not in text
    # No words were cut, so nothing is flagged and every phrase can still be chosen.
    assert not tight.shortened and "…" not in text
    assert len(tight.segment_ids) == 40


def test_a_long_transcript_is_cut_phrase_by_phrase_to_fit_the_model():
    body = long_recording(phrases=60, words_each=40)
    full, _ = prompt_for(body, context_tokens=32_000)
    assert not full.shortened and "word39" in full.messages[1].content

    cut, _ = prompt_for(body, context_tokens=6000)
    text = cut.messages[1].content
    assert cut.shortened
    assert "Long phrases are cut short with “…”." in text
    assert "word39" not in text and "word0 word1 word2" in text
    assert estimate_tokens(text) < 6000
    # Every phrase is still listed, so every one can still be chosen.
    assert len(cut.segment_ids) == 60


def test_with_too_many_phrases_only_those_the_findings_point_at_are_listed():
    body = long_recording(phrases=400, words_each=6)
    body.segments[7].pace_vs_typical = "faster"
    body.segments[7].segment_wpm = 300.0
    prompt, _ = prompt_for(body, context_tokens=3300)
    listed = [line for line in prompt.messages[1].content.splitlines() if line.startswith("seg-")]
    assert prompt.shortened
    assert 1 <= len(listed) <= 6
    assert any(line.startswith("seg-8 ") for line in listed)
    # The answer can only choose among the phrases it was shown.
    assert prompt.schema["properties"]["corrections"]["items"]["properties"]["segment"]["enum"] == [
        line.split()[0] for line in listed
    ]
