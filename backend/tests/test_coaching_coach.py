"""The coach: asking the language model, checking its answer, and falling back to templates."""

from datetime import UTC, datetime

import pytest

from app import schemas
from app.coaching.coach import Coach, CoachingUnavailable
from app.llm import LlmError, Reply
from app.pipeline.errors import JobCancelled
from tests.conftest import FakeChat, make_body

NOW = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def walter_take() -> schemas.AnalysisBody:
    """Issues: f2 pace variation (wide), f1 pace (fast), f7 rushed phrase, f5 loudness.

    Strengths: f3 pauses that register.
    """
    return make_body(
        "walter_white",
        speech_active_wpm=230.0,
        pace_variation=60.0,
        energy_variation=4.5,
        median_pause_seconds=1.5,
    )


def correction(finding: str, segment: str = "seg-1", **text) -> dict:
    return {
        "finding": finding,
        "segment": segment,
        "title": text.get("title", "Even out your pace"),
        "why": text.get("why", "The opening sets the tone, and it runs away from you."),
        "drill": text.get("drill", "Say 'You clearly do not know who' on a slow beat, 3 times."),
    }


GOOD_ANSWER = {
    "corrections": [correction("f2", "seg-2"), correction("f1"), correction("f7", "seg-1")],
    "working": [{"finding": "f3", "note": "Your pauses land. Keep them."}],
}


def coach_with(*replies, **kwargs) -> tuple[Coach, FakeChat]:
    llm = FakeChat(*replies, **kwargs)
    return Coach(llm), llm


def test_a_clean_answer_from_the_model_becomes_the_coaching():
    coach, llm = coach_with(GOOD_ANSWER)
    coaching = coach.generate(walter_take(), now=NOW)

    assert (coaching.source, coaching.model, coaching.notice) == ("ai", "fake-llm", None)
    assert coaching.model_seconds == 1.5
    assert coaching.generated_at == NOW
    assert [c.finding_id for c in coaching.corrections] == ["f2", "f1", "f7"]
    assert coaching.corrections[0].title == "Even out your pace"
    assert coaching.corrections[0].practise.id == "seg-2"
    assert [w.note for w in coaching.working] == ["Your pauses land. Keep them."]
    assert coaching.settings["fast_wpm"] == 200.0
    assert [line.label for line in coaching.summary] == ["Pace", "Pauses", "Voice", "Clarity"]
    assert len(llm.calls) == 1


def test_next_take_targets_follow_the_models_order_but_are_written_by_template():
    coach, _ = coach_with(GOOD_ANSWER)
    assert coach.generate(walter_take(), now=NOW).next_take == [
        "Keep phrase speeds within 10% of your typical pace.",
        "Bring your speaking pace down towards 200 WPM or below.",
        "Bring the rushed phrase back to your typical pace.",
    ]


def test_a_finding_about_one_phrase_is_practised_there_whatever_the_model_chose():
    coach, _ = coach_with(GOOD_ANSWER)
    rushed = coach.generate(walter_take(), now=NOW).corrections[2]
    # The model said seg-1, but finding f7 is about segment 3.
    assert (rushed.finding_id, rushed.practise.id) == ("f7", "seg-3")


def test_the_model_only_ever_receives_text_about_the_measurements():
    coach, llm = coach_with(GOOD_ANSWER)
    coach.generate(walter_take(), now=NOW)
    messages, schema = llm.calls[0]
    assert [m.role for m in messages] == ["system", "user"]
    assert "You clearly do not know who you are talking to" in messages[1].content
    assert schema["properties"]["corrections"]["items"]["properties"]["finding"]["enum"] == [
        "f2",
        "f1",
        "f7",
        "f5",
    ]


def test_an_invented_figure_sends_the_answer_back_once_for_correction():
    bad = {**GOOD_ANSWER, "corrections": [correction("f2", drill="Aim for 95 WPM, 3 times.")]}
    coach, llm = coach_with(bad, GOOD_ANSWER)
    coaching = coach.generate(walter_take(), now=NOW)

    assert (coaching.source, coaching.notice) == ("ai", None)
    assert len(coaching.corrections) == 3
    assert coaching.model_seconds == 3.0  # both attempts are counted
    assert len(llm.calls) == 2
    retry = llm.calls[1][0]
    assert [m.role for m in retry] == ["system", "user", "assistant", "user"]
    assert "“95 WPM” is not one of the measured figures" in retry[3].content
    assert "Write the whole answer again" in retry[3].content


def test_what_still_fails_after_the_retry_is_left_out_and_the_user_is_told():
    bad = {
        "corrections": [
            correction("f2", "seg-2"),
            correction("f1", why="At 0:55 you raced through it."),
            correction("f7", drill="Say 'these words were never spoken at all' slowly."),
        ],
        "working": [{"finding": "f3", "note": "Keep the 9 dB swing."}],
    }
    coach, llm = coach_with(bad)
    coaching = coach.generate(walter_take(), now=NOW)

    assert len(llm.calls) == 2
    assert coaching.source == "ai"
    assert [c.finding_id for c in coaching.corrections] == ["f2"]
    assert coaching.notice.code == "items_removed"
    assert coaching.notice.message.startswith("3 of the AI model's suggestions were left out")
    # The model's praise was dropped, so the template's is used instead.
    assert [w.note for w in coaching.working] == [
        "Your pauses are long enough to register between thoughts. Keep them."
    ]
    assert coaching.next_take == ["Keep phrase speeds within 10% of your typical pace."]


def test_if_nothing_survives_the_checks_the_templates_take_over():
    bad = {"corrections": [correction("f2", why="You spoke at 500 WPM.")], "working": []}
    coach, llm = coach_with(bad)
    coaching = coach.generate(walter_take(), now=NOW)

    assert len(llm.calls) == 2
    assert (coaching.source, coaching.model, coaching.notice.code) == ("rules", None, "ungrounded")
    assert [c.title for c in coaching.corrections] == [
        "Even out your pace",
        "Slow your overall pace",
        "Slow down this phrase",
    ]


@pytest.mark.parametrize(
    "item",
    [
        correction("f3"),  # a strength, not an issue
        correction("f99"),  # no such finding
        correction("f2", title=""),  # left empty
        correction("f2", why="x" * 701),  # far too long
        correction("f2", drill="Go back to segment 12."),  # no such segment
    ],
)
def test_other_ways_an_answer_can_be_unusable(item):
    coach, _ = coach_with({"corrections": [item, correction("f1")], "working": []})
    coaching = coach.generate(walter_take(), now=NOW)
    assert [c.finding_id for c in coaching.corrections] == ["f1"]
    assert coaching.notice.code == "items_removed"


def test_two_corrections_about_the_same_finding_count_once():
    answer = {"corrections": [correction("f2"), correction("f2"), correction("f1")], "working": []}
    coach, _ = coach_with(answer)
    assert [c.finding_id for c in coach.generate(walter_take(), now=NOW).corrections] == [
        "f2",
        "f1",
    ]


def test_an_answer_that_is_not_json_is_asked_for_again_then_given_up_on():
    coach, llm = coach_with("{ not json", GOOD_ANSWER)
    assert coach.generate(walter_take(), now=NOW).source == "ai"
    # A broken answer is not shown back to the model: the same question is simply asked again.
    assert [m.role for m in llm.calls[1][0]] == ["system", "user"]

    coach, llm = coach_with("{ not json")
    coaching = coach.generate(walter_take(), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", "bad_answer")
    assert len(llm.calls) == 2


def test_an_answer_that_was_cut_off_is_not_trusted():
    class CutOff(FakeChat):
        def complete_json(self, messages, schema, *, max_tokens, check=lambda: None) -> Reply:
            self.calls.append((messages, schema))
            return Reply(text='{"corrections": [', truncated=True, seconds=2.0)

    coaching = Coach(CutOff()).generate(walter_take(), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", "bad_answer")


@pytest.mark.parametrize("status", ["not_running", "model_missing", "not_local"])
def test_an_unavailable_model_never_costs_the_user_their_coaching(status):
    coach, _ = coach_with(GOOD_ANSWER, model_status=status)
    coaching = coach.generate(walter_take(), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", status)
    assert len(coaching.corrections) == 3 and coaching.next_take


def test_a_model_that_times_out_is_replaced_by_the_templates():
    coach, _ = coach_with(LlmError("timeout", "The AI model did not finish within 180 seconds."))
    coaching = coach.generate(walter_take(), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", "timeout")
    assert coaching.notice.message == "The AI model did not finish within 180 seconds."


def test_with_ai_coaching_switched_off_the_templates_are_used():
    coaching = Coach(None).generate(walter_take(), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", "ai_off")
    assert Coach(None).status() == "off" and Coach(None).model_name is None


def test_the_model_is_not_asked_when_there_is_nothing_to_correct():
    segments = make_body().segments
    segments[2].pace_vs_typical = None
    coach, llm = coach_with(GOOD_ANSWER)
    coaching = coach.generate(make_body("custom", segments=segments), now=NOW)
    assert (coaching.source, coaching.notice.code) == ("rules", "nothing_to_correct")
    assert "Choose a delivery profile" in coaching.notice.message
    assert coaching.corrections == [] and llm.calls == []


@pytest.mark.parametrize(
    ("code", "body"),
    [
        (
            "no_speech",
            make_body(
                segments=[],
                pauses=[],
                words=[],
                speech_active_wpm=None,
                warnings=[schemas.AnalysisWarning(code="no_speech", message="No speech.")],
            ),
        ),
        (
            "very_short",
            make_body(warnings=[schemas.AnalysisWarning(code="very_short", message="Too short.")]),
        ),
    ],
)
def test_a_recording_with_too_little_in_it_gets_no_coaching_at_all(code, body):
    coach, llm = coach_with(GOOD_ANSWER)
    coaching = coach.generate(body, now=NOW)
    assert (coaching.source, coaching.notice.code) == ("none", code)
    assert coaching.corrections == [] and coaching.working == [] and coaching.next_take == []
    assert llm.calls == []
    # What was and was not measured is still said.
    assert coaching.caveats and len(coaching.summary) == 4


def test_cancelling_reaches_the_model_and_stops_the_coaching():
    def cancelled() -> None:
        raise JobCancelled

    coach, llm = coach_with(GOOD_ANSWER)
    with pytest.raises(JobCancelled):
        coach.generate(walter_take(), now=NOW, check=cancelled)
    assert len(llm.calls) == 1


def test_requiring_the_model_turns_every_fallback_into_an_error():
    coach, _ = coach_with(GOOD_ANSWER)
    assert coach.generate(walter_take(), now=NOW, require_model=True).source == "ai"

    coach, _ = coach_with(GOOD_ANSWER, model_status="not_running")
    with pytest.raises(CoachingUnavailable) as raised:
        coach.generate(walter_take(), now=NOW, require_model=True)
    assert raised.value.code == "not_running"

    with pytest.raises(CoachingUnavailable) as raised:
        Coach(None).generate(walter_take(), now=NOW, require_model=True)
    assert raised.value.code == "ai_off"


def test_a_long_recording_is_flagged_when_the_model_saw_only_part_of_it():
    class SmallContext(FakeChat):
        context_tokens = 2700

    long_text = " ".join(f"word{n}" for n in range(400))
    body = walter_take()
    body.segments[1].transcript = long_text
    coaching = Coach(SmallContext(GOOD_ANSWER)).generate(body, now=NOW)
    assert coaching.source == "ai"
    assert coaching.caveats[-1].startswith("The recording is long, so the AI model was shown only")
