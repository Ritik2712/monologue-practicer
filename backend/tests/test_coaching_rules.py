"""Coaching from fixed templates: what the user gets when no language model is available."""

import pytest

from app import profiles
from app.coaching import rules
from app.coaching.findings import Found, build_findings, profile_wants
from app.coaching.grounding import collect_facts, problems_in
from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from tests.conftest import make_body, make_segment

SETTINGS = DEFAULT_COACHING_SETTINGS


def plan_for(body):
    return rules.plan(
        body, build_findings(body, SETTINGS), profile_wants(body.profile), SETTINGS
    ), build_findings(body, SETTINGS)


def test_the_three_most_important_issues_become_corrections_in_order():
    body = make_body(
        "walter_white",
        speech_active_wpm=230.0,
        pace_variation=60.0,
        energy_variation=4.5,
        median_pause_seconds=1.5,
    )
    plan, found = plan_for(body)
    kinds = [found.details[c.finding_id].kind for c in plan.corrections]
    assert kinds == ["pace_variation", "pace", "fast_segment"]
    assert [c.title for c in plan.corrections] == [
        "Even out your pace",
        "Slow your overall pace",
        "Slow down this phrase",
    ]
    assert plan.next_take == [
        "Keep phrase speeds within 10% of your typical pace.",
        "Bring your speaking pace down towards 200 WPM or below.",
        "Bring the rushed phrase back to your typical pace.",
    ]


def test_a_correction_explains_itself_names_a_drill_and_points_at_a_phrase():
    plan, _ = plan_for(make_body("walter_white", pace_variation=60.0))
    first = plan.corrections[0]
    assert first.why == (
        "Your phrases move at noticeably different speeds, which sounds less controlled. "
        "The Walter White profile calls for a similar speed from phrase to phrase."
    )
    # The fastest phrase is the one to practise an even pace on, quoted from the transcript.
    assert first.practise.id == "seg-3"
    assert first.drill.startswith(
        "Tap a slow, steady beat on the table and say “I am not in danger Skylar I am…” with"
    )


def test_the_profile_sentence_is_left_out_when_the_profile_has_no_view():
    plan, _ = plan_for(make_body("custom", speech_active_wpm=230.0))
    assert plan.corrections[0].why == (
        "At this speed a listener has little time to take each phrase in."
    )
    # Shelby does have a view on pace, and its target is the unhurried band.
    plan, _ = plan_for(make_body("thomas_shelby", speech_active_wpm=230.0))
    assert plan.corrections[0].why.endswith(
        "The Thomas Shelby profile depends on an unhurried delivery."
    )
    assert plan.next_take[0] == "Bring your speaking pace down towards 140 WPM or below."


def test_a_finding_about_one_phrase_is_practised_on_that_phrase():
    plan, found = plan_for(make_body("custom"))
    fast = next(c for c in plan.corrections if found.details[c.finding_id].kind == "fast_segment")
    assert (fast.practise.id, fast.practise.start_seconds, fast.practise.end_seconds) == (
        "seg-3",
        9.3,
        12.3,
    )


def test_the_middle_band_moves_whichever_way_the_profile_leans():
    moderate = Found(kind="loudness_variation", role="issue", statement="", level="moderate")
    assert rules.direction(moderate, {"loudness_variation": "high"}) == "raise"
    assert rules.direction(moderate, {"loudness_variation": "low"}) == "lower"
    assert rules.template_for(moderate, {"loudness_variation": "high"}).title == (
        "Use more contrast in volume"
    )
    assert rules.template_for(moderate, {"loudness_variation": "low"}).title == (
        "Keep your volume level"
    )


def test_strengths_become_short_notes_about_what_to_keep():
    plan, found = plan_for(make_body("walter_white", pace_variation=9.0, median_pause_seconds=1.6))
    assert [(found.details[w.finding_id].kind, w.note) for w in plan.working] == [
        ("pace_variation", "Your phrases move at a steady, similar speed. Keep it."),
        ("pause_length", "Your pauses are long enough to register between thoughts. Keep them."),
    ]


def test_with_nothing_to_correct_there_are_no_corrections_and_one_plain_target():
    segments = make_body().segments
    segments[2].pace_vs_typical = None
    plan, _ = plan_for(make_body("custom", segments=segments))
    assert plan.corrections == []
    assert plan.next_take == [rules.NOTHING_TO_CORRECT]


def test_a_phrase_is_pointed_at_by_its_opening_words():
    long = make_segment(0, 0.0, 4.0, "one two three four five six seven eight nine ten")
    assert rules.quote(long) == "“one two three four five six seven eight…”"
    assert rules.quote(make_segment(0, 0.0, 2.0, "just three words")) == "“just three words”"
    assert rules.quote(make_segment(0, 0.0, 2.0, "")) == "this phrase"
    assert rules.quote(None) == "this phrase"


@pytest.mark.parametrize("profile", [profile.id for profile in profiles.PROFILES])
@pytest.mark.parametrize("key", sorted(rules.TEMPLATES))
def test_every_template_fills_in_completely_and_quotes_only_known_figures(profile, key):
    """No template may leave a {placeholder} behind or state a figure that is not a band."""
    template = rules.TEMPLATES[key]
    found = Found(kind=key[0], role="issue", statement="")
    values = rules.template_values(found, profile, SETTINGS, "“the line”")
    bands = "140 WPM 200 WPM 10% 25% 1 second 2 seconds 3 dB 6 dB 2 semitones 4 semitones"
    facts = collect_facts(bands, segment_count=1, pause_count=1, transcript="")
    for text in (
        template.title,
        template.why,
        template.why_profile,
        template.drill,
        template.target,
    ):
        filled = text.format(**values)
        assert "{" not in filled and "}" not in filled
        assert problems_in(filled, facts) == []
    assert template.technique and "{" not in template.technique
