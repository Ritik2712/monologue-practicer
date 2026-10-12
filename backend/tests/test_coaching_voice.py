"""Where the voice sits, as findings and as coaching: judged only against a goal the speaker chose."""

import pytest

from app import schemas
from app.coaching import rules
from app.coaching.coach import Coach
from app.coaching.findings import VOICE_CAVEAT, build_findings, profile_wants
from app.coaching.grounding import find_figures
from app.coaching.prompt import SYSTEM, build_prompt
from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from app.pipeline.voice_range import DEFAULT_VOICE_RANGES, overall_marker, place
from tests.conftest import (
    TAKE_SEGMENTS,
    FakeChat,
    FakeClock,
    answer_within,
    make_body,
    make_segment,
)

SETTINGS = DEFAULT_COACHING_SETTINGS


def placement(hz: float | None, scale: str, quality: str = "measured"):
    if hz is None:
        return None
    placed = place(hz, scale, DEFAULT_VOICE_RANGES)
    return schemas.VoicePlacement(
        value_hz=hz, band=placed.band, percent=placed.percent, quality=quality
    )


def voiced(
    goal: str = "none",
    *,
    pitch: float | None = 118.0,
    resonance: float | None = 990.0,
    phrases: list[tuple[float | None, float | None]] | None = None,
    quality: str = "measured",
    note: str | None = None,
    **overrides,
) -> schemas.AnalysisBody:
    """A four-phrase take. `phrases` gives each phrase's (pitch, resonance) in Hz."""
    phrases = phrases or [(pitch, resonance)] * len(TAKE_SEGMENTS)
    segments = []
    for index, ((start, end, text), (phrase_pitch, phrase_resonance)) in enumerate(
        zip(TAKE_SEGMENTS, phrases, strict=True)
    ):
        in_pitch = placement(phrase_pitch, "pitch")
        in_resonance = placement(phrase_resonance, "resonance", quality)
        segments.append(
            make_segment(
                index,
                start,
                end,
                text,
                voice=schemas.SegmentVoice(
                    pitch=in_pitch,
                    resonance=in_resonance,
                    marker=overall_marker(
                        in_pitch.band if in_pitch else None,
                        in_resonance.band if in_resonance else None,
                    ),
                ),
            )
        )
    whole_pitch, whole_resonance = (
        placement(pitch, "pitch"),
        placement(resonance, "resonance", quality),
    )
    return make_body(
        segments=segments,
        voice_range=schemas.VoiceRange(
            goal=goal,
            pitch=whole_pitch,
            resonance=whole_resonance,
            marker=overall_marker(
                whole_pitch.band if whole_pitch else None,
                whole_resonance.band if whole_resonance else None,
            ),
            bands=DEFAULT_VOICE_RANGES.to_dict(),
            resonance_note=note,
        ),
        **overrides,
    )


def find(body: schemas.AnalysisBody, kind: str) -> schemas.Finding | None:
    return next((f for f in build_findings(body, SETTINGS).findings if f.kind == kind), None)


# --- Without a goal: stated, never judged ------------------------------------------------


def test_without_a_goal_the_voice_is_described_and_nothing_is_judged():
    body = voiced("none")
    pitch, resonance = find(body, "voice_pitch"), find(body, "voice_resonance")

    assert (pitch.role, resonance.role) == ("context", "context")
    # 118 Hz is (145 - 118) / (145 - 85) = 45% of the way into the lower range.
    assert pitch.statement == (
        "Your pitch sat at a median of 118 Hz. That is in the lower range (under 145 Hz), "
        "45% of the way into it. A voice in that range is typically heard as masculine."
    )
    # 990 Hz is (1040 - 990) / (1040 - 940) = 50% of the way into the lower range.
    assert resonance.statement == (
        "The resonance of your voice measured 990 Hz: the average spacing of its formants, "
        "where lower is deeper and higher is brighter. That is in the lower range (under "
        "1040 Hz), 50% of the way into it. A voice in that range is typically heard as "
        "masculine."
    )
    assert "goal" not in pitch.statement

    finding_set = build_findings(body, SETTINGS)
    assert [line.label for line in finding_set.summary] == ["Pace", "Pauses", "Voice", "Clarity"]
    assert VOICE_CAVEAT not in finding_set.caveats
    assert not any(f.kind.startswith("voice_") for f in finding_set.issues)


@pytest.mark.parametrize(
    ("hz", "phrase"),
    [
        (160.0, "That is in the neutral range (145 to 175 Hz). A voice in that range could be"),
        (215.0, "That is in the higher range (over 175 Hz), 50% of the way into it. A voice in"),
    ],
)
def test_each_range_is_named_with_its_edges(hz, phrase):
    assert phrase in find(voiced(pitch=hz), "voice_pitch").statement


def test_the_wording_is_about_the_sound_and_never_about_the_speaker():
    for goal in ("none", "lower", "higher"):
        for kind in ("voice_pitch", "voice_resonance"):
            statement = find(voiced(goal, pitch=200.0, resonance=1200.0), kind).statement.lower()
            assert "you are" not in statement and "you sound like" not in statement
            for word in (" man", " woman", " male", " female", " boy", " girl"):
                assert word not in statement


def test_there_is_no_voice_finding_for_a_result_that_did_not_measure_it():
    body = make_body()
    assert find(body, "voice_pitch") is None and find(body, "voice_resonance") is None


def test_only_what_was_measured_is_stated():
    body = voiced(resonance=None)
    assert find(body, "voice_pitch") is not None
    assert find(body, "voice_resonance") is None


def test_an_estimated_resonance_says_why():
    noisy = "The background is loud enough to make the resonance read brighter."
    statement = find(voiced(quality="estimated", note=noisy), "voice_resonance").statement
    assert statement.endswith(noisy)
    short = find(voiced(quality="estimated"), "voice_resonance").statement
    assert short.endswith("so treat it as an estimate.")


# --- With a goal -------------------------------------------------------------------------


def test_a_voice_that_stayed_in_the_chosen_range_is_a_strength():
    body = voiced("lower")
    pitch = find(body, "voice_pitch")

    assert pitch.role == "strength"
    assert pitch.statement.endswith(
        "Your goal is to keep your voice in the lower range: 4 of 4 phrases stayed in it for pitch."
    )
    assert find(body, "voice_resonance").role == "strength"


def test_phrases_that_left_the_range_are_named_furthest_first_and_become_an_issue():
    body = voiced(
        "lower",
        phrases=[(118.0, 990.0), (150.0, 990.0), (190.0, 1150.0), (120.0, 1000.0)],
    )
    pitch = find(body, "voice_pitch")

    assert pitch.role == "issue"
    assert pitch.statement.endswith(
        "Your goal is to keep your voice in the lower range: 2 of 4 phrases stayed in it for "
        "pitch. Furthest from it: segment 3 at 190 Hz, segment 2 at 150 Hz."
    )
    # The phrases can be played, the furthest first.
    assert [e.id for e in pitch.evidence if e.kind == "segment"] == ["seg-3", "seg-2"]

    resonance = find(body, "voice_resonance")
    assert resonance.role == "issue"
    assert resonance.statement.endswith(
        "3 of 4 phrases stayed in it for resonance. Furthest from it: segment 3 at 1150 Hz."
    )


def test_the_same_voice_is_read_the_other_way_round_for_the_other_goal():
    lower, higher = voiced("lower"), voiced("higher")

    assert find(lower, "voice_pitch").role == "strength"
    pitch = find(higher, "voice_pitch")
    assert pitch.role == "issue"
    assert "0 of 4 phrases stayed in it for pitch" in pitch.statement
    # The measurement is stated identically; only the reading of it differs.
    assert pitch.statement.startswith(find(lower, "voice_pitch").statement.split(" Your goal")[0])


def test_a_whole_voice_outside_the_range_matters_more_than_a_few_stray_phrases():
    def weight(body, kind="voice_pitch"):
        finding_set = build_findings(body, SETTINGS)
        return next(d.weight for d in finding_set.details.values() if d.kind == kind)

    stray = voiced("lower", phrases=[(118.0, 990.0)] * 3 + [(150.0, 990.0)])
    neutral = voiced("lower", pitch=160.0)
    opposite = voiced("lower", pitch=200.0)

    assert 0 < weight(stray) < weight(neutral) < weight(opposite) == 1.0


def test_a_goal_adds_a_summary_line_and_a_word_of_caution():
    finding_set = build_findings(voiced("higher"), SETTINGS)

    labels = [line.label for line in finding_set.summary]
    assert labels == ["Pace", "Pauses", "Voice", "Voice range", "Clarity"]
    assert "Your pitch sat at a median of 118 Hz" in finding_set.summary[3].text
    assert VOICE_CAVEAT in finding_set.caveats
    assert "strained" in VOICE_CAVEAT and "not who is speaking" in VOICE_CAVEAT


def test_every_figure_in_a_voice_finding_is_a_measurement_or_a_range_edge():
    body = voiced(
        "lower", phrases=[(118.0, 990.0), (150.0, 990.0), (190.0, 1150.0), (120.0, 1000.0)]
    )
    known = {118.0, 145.0, 175.0, 190.0, 150.0, 45.0, 990.0, 1040.0, 1100.0, 1150.0, 50.0}
    for kind in ("voice_pitch", "voice_resonance"):
        for figure in find_figures(find(body, kind).statement):
            assert figure.value in known, figure


# --- The coaching ------------------------------------------------------------------------


def plan_for(body: schemas.AnalysisBody) -> rules.Plan:
    return rules.plan(body, build_findings(body, SETTINGS), profile_wants(body.profile), SETTINGS)


def test_the_correction_points_down_for_a_lower_goal_and_up_for_a_higher_one():
    down = plan_for(voiced("lower", pitch=200.0, resonance=1200.0))
    titles = [correction.title for correction in down.corrections]
    assert titles[:2] == ["Keep your pitch in the lower range", "Deepen your resonance"]
    assert down.next_take[:2] == [
        "Keep every phrase's pitch in the lower range.",
        "Keep every phrase's resonance in the lower range.",
    ]

    up = plan_for(voiced("higher"))
    titles = [correction.title for correction in up.corrections]
    assert titles[:2] == ["Keep your pitch in the higher range", "Brighten your resonance"]
    assert "stop if your throat feels strained" in up.corrections[0].drill


def test_the_drill_is_done_on_the_phrase_furthest_from_the_range():
    body = voiced(
        "lower",
        phrases=[(118.0, 990.0), (150.0, 990.0), (190.0, 990.0), (120.0, 990.0)],
    )
    correction = plan_for(body).corrections[0]

    assert correction.title == "Keep your pitch in the lower range"
    assert correction.practise.id == "seg-3"
    assert "“I am not in danger Skylar I am…”" in correction.drill


def test_a_voice_in_its_range_is_listed_as_working():
    notes = [item.note for item in plan_for(voiced("lower")).working]
    assert "Your pitch stayed in the range you set out to keep. Keep it." in notes


def test_without_a_goal_the_coaching_says_nothing_about_the_voice_range():
    plan = plan_for(voiced("none", pitch=200.0, resonance=1200.0))
    for correction in plan.corrections:
        assert (
            "range" not in correction.title.lower() and "resonance" not in correction.title.lower()
        )
    assert not any("range you set out" in item.note for item in plan.working)


def test_the_model_is_told_the_direction_the_phrase_and_to_speak_only_of_the_sound():
    body = voiced(
        "lower",
        phrases=[(118.0, 990.0), (150.0, 990.0), (190.0, 990.0), (120.0, 990.0)],
    )
    finding_set = build_findings(body, SETTINGS)
    prompt = build_prompt(
        body, finding_set, profile_wants(body.profile), SETTINGS, context_tokens=8192
    )
    data = prompt.messages[1].content

    assert "Aim: Keep your pitch in the lower range." in data
    assert "Practise it on seg-3, the phrase furthest from the range." in data
    assert "Never say or guess anything about the actor's sex or gender" in SYSTEM
    assert "never call a voice wrong" in SYSTEM


def test_template_coaching_for_a_voice_goal_passes_the_same_checks_as_any_other():
    body = voiced("higher")
    coaching = Coach(None).generate(body, now=FakeClock()(), settings=SETTINGS, use_model=False)

    assert coaching.source == "rules"
    kinds = {f.id: f.kind for f in coaching.findings}
    assert [kinds[c.finding_id] for c in coaching.corrections][:2] == [
        "voice_pitch",
        "voice_resonance",
    ]
    assert VOICE_CAVEAT in coaching.caveats


# --- What the model is shown, and what is done with what it writes -----------------------


def test_the_model_is_not_shown_how_a_range_is_typically_heard():
    body = voiced("lower", pitch=200.0, resonance=1200.0)
    finding_set = build_findings(body, SETTINGS)
    # The reader of the screen is told...
    assert "typically heard as feminine" in find(body, "voice_pitch").statement
    # ...and the model is not, because it repeats it as a remark about the speaker.
    prompt = build_prompt(
        body, finding_set, profile_wants(body.profile), SETTINGS, context_tokens=8192
    )
    data = prompt.messages[1].content.lower()
    assert "feminine" not in data and "masculine" not in data
    assert "your pitch sat at a median of 200 hz" in data
    assert "in the higher range (over 175 hz)" in data


def test_words_about_the_speaker_are_found_outside_quotations_only():
    from app.coaching.grounding import speaker_words

    assert speaker_words("Do this to avoid being perceived as feminine.") == ["feminine"]
    assert speaker_words("A Man would say it lower, like a male lead.") == ["Man", "male"]
    assert speaker_words("Keep the hum low and let the phrase fall.") == []
    # The speaker's own line may say such a word, and the drill may quote it.
    assert speaker_words("Say “I am the man who knocks” on a low hum.") == []
    # Words that merely contain one are not it.
    assert speaker_words("Manage the command of each human sound.") == []


def said_about_the_speaker(schema: dict) -> dict:
    answer = answer_within(schema)
    answer["corrections"][0]["why"] = "A lower note keeps you from being perceived as feminine."
    return answer


def coached(body: schemas.AnalysisBody, *replies):
    llm = FakeChat(*replies)
    coaching = Coach(llm).generate(body, now=FakeClock()(), settings=SETTINGS)
    return coaching, llm


def written(coaching: schemas.Coaching) -> str:
    parts = [f"{c.title} {c.why} {c.drill}" for c in coaching.corrections]
    return " ".join(parts + [item.note for item in coaching.working]).lower()


def test_a_remark_about_the_speaker_is_sent_back_to_the_model_once():
    body = voiced("lower", pitch=200.0)
    coaching, llm = coached(body, said_about_the_speaker, answer_within)

    assert len(llm.calls) == 2
    sent_back = llm.calls[1][0][-1].content
    assert "“feminine” says something about who is speaking" in sent_back
    assert coaching.source == "ai" and coaching.notice is None
    assert "feminine" not in written(coaching)


def test_a_remark_the_model_repeats_is_left_out_of_the_coaching():
    # Two things to work on: the pitch, and a fast pace.
    body = voiced("lower", pitch=200.0, speech_active_wpm=240.0)
    coaching, llm = coached(body, said_about_the_speaker)

    assert len(llm.calls) == 2
    assert "feminine" not in written(coaching)
    # The correction with the remark is gone, the other is kept, and the screen says so.
    assert coaching.source == "ai"
    assert coaching.notice is not None
    kinds = {f.id: f.kind for f in coaching.findings}
    assert [kinds[c.finding_id] for c in coaching.corrections] == ["pace"]


def test_if_nothing_else_is_left_the_fixed_rules_write_the_coaching():
    body = voiced("lower", pitch=200.0)
    coaching, _ = coached(body, said_about_the_speaker)

    assert coaching.source == "rules"
    assert coaching.corrections[0].title == "Keep your pitch in the lower range"
    assert "feminine" not in written(coaching)


def test_the_same_words_pass_when_no_voice_goal_was_chosen():
    # Without a goal the voice is not being coached, and a character may be "a man of few words".
    body = voiced("none", speech_active_wpm=240.0)
    coaching, llm = coached(body, said_about_the_speaker)

    assert len(llm.calls) == 1
    assert "feminine" in written(coaching)


def test_an_internal_phrase_label_in_the_models_wording_is_written_the_way_the_screen_writes_it():
    def labelled(schema: dict) -> dict:
        answer = answer_within(schema)
        answer["corrections"][0]["drill"] = "On seg-3, hum low and slide into the line, 3 times."
        return answer

    body = voiced("lower", phrases=[(118.0, 990.0), (150.0, 990.0), (190.0, 990.0), (120.0, 990.0)])
    coaching, llm = coached(body, labelled)

    assert len(llm.calls) == 1
    assert coaching.corrections[0].drill.startswith("On segment 3, hum low")

    # And a phrase that does not exist is still caught, under either spelling.
    def wrong(schema: dict) -> dict:
        answer = answer_within(schema)
        answer["corrections"][0]["drill"] = "On seg-9, hum low and slide into the line, 3 times."
        return answer

    _, llm = coached(body, wrong, answer_within)
    assert "there is no segment 9" in llm.calls[1][0][-1].content
