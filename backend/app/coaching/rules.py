"""Coaching written by fixed templates, with no language model involved.

Used whenever the language model cannot be (Ollama not running, model not installed, answer
rejected), so a result always carries usable advice. The same templates also give the
language model a starting idea for each drill.
"""

from dataclasses import dataclass

from app import profiles, schemas
from app.coaching.findings import FindingSet, Found, number, seconds_text, segment_evidence
from app.coaching.settings import CoachingSettings

MAX_CORRECTIONS = 3
MAX_WORKING = 2
# How many words of a phrase are quoted when pointing at it.
QUOTED_WORDS = 8


@dataclass(frozen=True)
class Template:
    title: str
    why: str
    drill: str
    target: str
    # The drill's method in a few words, given to the language model as a starting point.
    technique: str
    # Added to `why` when the chosen profile has a view on this aspect of delivery.
    why_profile: str = ""


# Keyed by what the finding is about and which way the measurement should move.
TEMPLATES: dict[tuple[str, str], Template] = {
    ("pace", "lower"): Template(
        title="Slow your overall pace",
        why="At this speed a listener has little time to take each phrase in.",
        why_profile="The {profile} profile depends on an unhurried delivery.",
        drill=(
            "Say {line} at about half your normal speed, stretching the vowels. Then say it "
            "once more at a speed between that and normal. Do both 3 times."
        ),
        target="Bring your speaking pace down towards {pace_target} WPM or below.",
        technique="half speed with stretched vowels, then a speed between that and normal",
    ),
    ("pace_variation", "lower"): Template(
        title="Even out your pace",
        why="Your phrases move at noticeably different speeds, which sounds less controlled.",
        why_profile="The {profile} profile calls for a similar speed from phrase to phrase.",
        drill=(
            "Tap a slow, steady beat on the table and say {line} with one word on each beat. "
            "Repeat 3 times, then say the phrase before it on the same beat."
        ),
        target="Keep phrase speeds within {even_pct}% of your typical pace.",
        technique="one word on each beat of a slow, steady tap",
    ),
    ("pace_variation", "raise"): Template(
        title="Vary your pace more",
        why="Your phrases all move at close to the same speed, so none of them stands out.",
        why_profile="The {profile} profile needs clear differences in speed between phrases.",
        drill=(
            "Say {line} as fast as you can while staying clear, then at half speed. Decide "
            "which suits the meaning and repeat that version 3 times."
        ),
        target="Let phrase speeds differ by more than {varied_pct}% of your typical pace.",
        technique="the same line very fast, then at half speed, then choosing one",
    ),
    ("pause_length", "raise"): Template(
        title="Hold your pauses longer",
        why="Most of your pauses are over before a listener notices them.",
        why_profile="For the {profile} profile, the silence between thoughts is part of the delivery.",
        drill=("After {line}, count “one thousand one” silently before you go on. Repeat 3 times."),
        target="Bring your median pause up to {registering} or more.",
        technique="a silent count of “one thousand one” after the line",
    ),
    ("no_pauses", "raise"): Template(
        title="Add pauses between thoughts",
        why="With no pause, one thought runs into the next and none of them lands.",
        why_profile="For the {profile} profile, the silence between thoughts is part of the delivery.",
        drill=(
            "Mark the end of each thought in your script with a slash. Say {line}, stop at the "
            "slash, count “one thousand one” silently, then go on. Repeat 3 times."
        ),
        target="Leave at least one pause of {registering} or more.",
        technique="a slash in the script at the end of each thought, and a silent count there",
    ),
    ("held_silence", "raise"): Template(
        title="Hold one full silence",
        why="No pause lasted long enough to carry weight on its own.",
        why_profile="The {profile} profile uses deliberate silence.",
        drill=(
            "Before {line}, stop completely and count “one thousand one, one thousand two” "
            "silently, then speak. Repeat 3 times."
        ),
        target="Hold at least one silence for {held} or more.",
        technique="a full stop before the line, with a silent count of “one thousand one, one thousand two”",
    ),
    ("loudness_variation", "lower"): Template(
        title="Keep your volume level",
        why="Your loudness rises and falls noticeably across the piece.",
        why_profile="The {profile} profile keeps its intensity restrained.",
        drill=(
            "Say {line} at one steady volume, as if to someone sitting across a table. Repeat "
            "3 times without letting any word jump out."
        ),
        target="Keep loudness variation under {even_db} dB.",
        technique="one steady volume, as if to someone across a table, with no word jumping out",
    ),
    ("loudness_variation", "raise"): Template(
        title="Use more contrast in volume",
        why="Your loudness stays close to one level throughout.",
        why_profile="The {profile} profile sets quiet passages against loud ones.",
        drill=(
            "Say {line} once almost in a whisper and once at full voice. Then pick one phrase "
            "of the piece for each and run them back to back."
        ),
        target="Let loudness variation rise above {varied_db} dB.",
        technique="the line almost whispered, then at full voice",
    ),
    ("pitch_variation", "raise"): Template(
        title="Move your pitch more",
        why="Your pitch stays within a narrow band, which can sound flat.",
        why_profile="The {profile} profile calls for wide swings in pitch.",
        drill=(
            "Say {line} three ways: as a question, as an order, and as a secret. Keep the "
            "version that fits and repeat it 3 times."
        ),
        target="Let pitch variation rise above {pitch_target} semitones.",
        technique="the line as a question, as an order and as a secret",
    ),
    ("fast_segment", "lower"): Template(
        title="Slow down this phrase",
        why="This phrase ran well ahead of your own typical pace, so it stands out as rushed.",
        why_profile="The {profile} profile calls for a similar speed from phrase to phrase.",
        drill=(
            "Say {line} on its own at your typical pace, one clear beat per word, 3 times. "
            "Then say it together with the phrase before it."
        ),
        target="Bring the rushed phrase back to your typical pace.",
        technique="the phrase alone at the typical pace, one clear beat per word",
    ),
    ("slow_segment", "raise"): Template(
        title="Bring this phrase up to pace",
        why="This phrase ran well behind your own typical pace.",
        why_profile="The {profile} profile calls for a similar speed from phrase to phrase.",
        drill=(
            "Say {line} on its own, slightly quicker each time, until it matches the phrases "
            "around it. Repeat 3 times."
        ),
        target="Bring the slow phrase up to your typical pace.",
        technique="the phrase alone, slightly quicker each time, until it matches its neighbours",
    ),
    ("hesitations", "lower"): Template(
        title="Replace hesitation sounds with silence",
        why="Sounds such as “um” fill the space where a clean pause would carry more weight.",
        drill=(
            "Say {line} again. Wherever a hesitation sound wants to come out, close your mouth "
            "and pause instead. Repeat 3 times."
        ),
        target="Leave a silent pause wherever a hesitation sound came out.",
        technique="closing the mouth and pausing wherever a hesitation sound wants to come out",
    ),
    ("no_emphasis", "raise"): Template(
        title="Make one word in each phrase stand out",
        why="No word rose clearly above the rest in loudness or pitch.",
        why_profile="The {profile} profile depends on contrast.",
        drill=(
            "In {line}, choose the one word that matters most. Say the phrase 3 times, lifting "
            "only that word in pitch or volume."
        ),
        target="Give each phrase one word that clearly stands out.",
        technique="choosing the one word that matters most and lifting only that word",
    ),
}

FALLBACK_TEMPLATE = Template(
    title="Work on this measurement",
    why="This measurement works against the chosen profile.",
    drill="Say {line} again with this in mind, 3 times, and compare the new recording.",
    target="Move this measurement towards the profile.",
    technique="the phrase again with this one change in mind",
)

# What to say about something that already fits, by finding kind and level.
STRENGTH_NOTES: dict[tuple[str, str | None], str] = {
    ("pace", "low"): "Your pace is unhurried. Keep it.",
    ("pace_variation", "low"): "Your phrases move at a steady, similar speed. Keep it.",
    ("pace_variation", "high"): (
        "Your pace clearly changes from phrase to phrase. Keep that contrast."
    ),
    ("pause_length", "high"): (
        "Your pauses are long enough to register between thoughts. Keep them."
    ),
    ("held_silence", "high"): "You held a real silence. Keep using it where it matters.",
    ("loudness_variation", "low"): "Your volume stays level. Keep that restraint.",
    ("loudness_variation", "high"): ("Loud and quiet passages clearly differ. Keep that contrast."),
    ("pitch_variation", "high"): "Your pitch moves across a wide range. Keep it.",
    ("emphasis", None): "Some words clearly stand out. Keep choosing them on purpose.",
    ("fast_segment", None): "This change of pace gives contrast. Keep it if it was intended.",
    ("slow_segment", None): "This change of pace gives contrast. Keep it if it was intended.",
}
FALLBACK_STRENGTH_NOTE = "This already works. Keep it."

NOTHING_TO_CORRECT = "Record the same passage again and see whether the measurements hold."


def direction(found: Found, wants: dict[str, str]) -> str:
    """Which way the measurement should move for this issue: "raise" or "lower"."""
    if found.kind in ("fast_segment", "hesitations"):
        return "lower"
    if found.kind in ("slow_segment", "no_emphasis", "no_pauses"):
        return "raise"
    if found.level == "low":
        return "raise"
    if found.level == "high":
        return "lower"
    # In the middle band, the profile decides which way is "further".
    return "raise" if wants.get(found.kind) == "high" else "lower"


# The aspects of delivery a finding touches, when that is not simply its own kind.
ASPECTS = {
    "no_pauses": ("pause_length", "held_silence"),
    "fast_segment": ("pace_variation",),
    "slow_segment": ("pace_variation",),
    "no_emphasis": ("loudness_variation", "pitch_variation"),
}


def profile_has_view(found: Found, wants: dict[str, str]) -> bool:
    return any(aspect in wants for aspect in ASPECTS.get(found.kind, (found.kind,)))


def template_for(found: Found, wants: dict[str, str]) -> Template:
    return TEMPLATES.get((found.kind, direction(found, wants)), FALLBACK_TEMPLATE)


def quote(segment: schemas.SpeechSegment | None) -> str:
    """The opening words of a phrase, in quotation marks, to point at it."""
    if segment is None or not segment.transcript:
        return "this phrase"
    words = segment.transcript.split()
    shown = " ".join(words[:QUOTED_WORDS]) + ("…" if len(words) > QUOTED_WORDS else "")
    return f"“{shown}”"


def anchor_segment(body: schemas.AnalysisBody) -> schemas.SpeechSegment | None:
    """A phrase to practise on when a finding is about the whole recording: the longest one."""
    if not body.segments:
        return None
    spoken = [s for s in body.segments if s.transcript] or body.segments
    return max(spoken, key=lambda s: s.speech_active_seconds)


def practise_segment(
    body: schemas.AnalysisBody, found: Found, wants: dict[str, str]
) -> schemas.SpeechSegment | None:
    by_id = {segment.id: segment for segment in body.segments}
    if "segment" in found.data:
        return by_id.get(found.data["segment"])
    if found.kind == "pace_variation":
        # The phrase furthest in the unwanted direction is the one to work on.
        key = "slowest" if wants.get("pace_variation") == "high" else "fastest"
        return by_id.get(found.data.get(key, "")) or anchor_segment(body)
    if found.kind == "held_silence" and "before" in found.data:
        # The phrase that follows the longest pause: the natural place to hold it longer.
        return by_id.get(found.data["before"]) or anchor_segment(body)
    return anchor_segment(body)


def template_values(
    found: Found, profile_id: str, settings: CoachingSettings, line: str
) -> dict[str, str]:
    profile = profiles.get_profile(profile_id)
    wants_low_pace = any(f.metric == "speechActiveWpm" and f.wants == "low" for f in profile.focus)
    wants_wide_pitch = any(
        f.metric == "pitchVariationSemitones" and f.wants == "high" for f in profile.focus
    )
    return {
        "line": line,
        "profile": profile.name,
        "pace_target": number(settings.slow_wpm if wants_low_pace else settings.fast_wpm),
        "even_pct": str(round(settings.even_pace_ratio * 100)),
        "varied_pct": str(round(settings.varied_pace_ratio * 100)),
        "registering": seconds_text(settings.registering_pause_seconds),
        "held": seconds_text(settings.held_silence_seconds),
        "even_db": number(settings.even_loudness_db),
        "varied_db": number(settings.varied_loudness_db),
        "pitch_target": number(
            settings.wide_pitch_semitones if wants_wide_pitch else settings.narrow_pitch_semitones
        ),
    }


def targets_for(
    finding_ids: list[str],
    body: schemas.AnalysisBody,
    finding_set: FindingSet,
    wants: dict[str, str],
    settings: CoachingSettings,
) -> list[str]:
    """One measurable target for the next take per correction, in the same order.

    Always written by template, even when the language model worded the corrections: a
    target should be something the next recording can be checked against.
    """
    targets = []
    for finding_id in finding_ids:
        found = finding_set.details[finding_id]
        values = template_values(found, body.profile, settings, "the phrase")
        targets.append(template_for(found, wants).target.format(**values))
    return list(dict.fromkeys(targets)) or [NOTHING_TO_CORRECT]


@dataclass(frozen=True)
class Plan:
    corrections: list[schemas.Correction]
    working: list[schemas.Strength]
    next_take: list[str]


def strength_note(found: Found) -> str:
    return STRENGTH_NOTES.get(
        (found.kind, found.level), STRENGTH_NOTES.get((found.kind, None), FALLBACK_STRENGTH_NOTE)
    )


def plan(
    body: schemas.AnalysisBody,
    finding_set: FindingSet,
    wants: dict[str, str],
    settings: CoachingSettings,
) -> Plan:
    """The whole coaching, from templates alone."""
    corrections: list[schemas.Correction] = []
    for finding in finding_set.issues[:MAX_CORRECTIONS]:
        found = finding_set.details[finding.id]
        template = template_for(found, wants)
        segment = practise_segment(body, found, wants)
        values = template_values(found, body.profile, settings, quote(segment))
        why = template.why
        if template.why_profile and profile_has_view(found, wants):
            why = f"{why} {template.why_profile}"
        corrections.append(
            schemas.Correction(
                finding_id=finding.id,
                title=template.title,
                why=why.format(**values),
                drill=template.drill.format(**values),
                practise=segment_evidence(segment) if segment else None,
            )
        )

    working = [
        schemas.Strength(finding_id=f.id, note=strength_note(finding_set.details[f.id]))
        for f in finding_set.strengths[:MAX_WORKING]
    ]
    chosen = [correction.finding_id for correction in corrections]
    return Plan(corrections, working, targets_for(chosen, body, finding_set, wants, settings))
