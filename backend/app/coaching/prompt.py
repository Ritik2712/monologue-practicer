"""Builds what is sent to the language model, and the shape its answer must take.

The model receives text only: the delivery profile in words, the transcript with timings,
and the findings written by `findings.py`. It never receives audio.

Its answer is constrained twice. The JSON schema lets it name only findings and segments
that exist, so it cannot point at a made-up one. Its free wording is then checked figure by
figure in `grounding.py`.
"""

import math
from dataclasses import dataclass

from app import profiles, schemas
from app.coaching import rules
from app.coaching.findings import FindingSet, number, seconds_text, timecode
from app.coaching.settings import CoachingSettings
from app.llm import Message

# Room kept free in the model's context for the instructions, the findings and its answer.
RESERVED_TOKENS = 2600
MIN_TRANSCRIPT_TOKENS = 600
MAX_ANSWER_TOKENS = 600
# Tried in order until the transcript fits: words kept per phrase. None means all of them.
WORD_LIMITS: tuple[int | None, ...] = (None, 40, 25, 15, 10, 6, 3)

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "hinglish": "Hinglish (Hindi and English)"}

SYSTEM = """You are a speaking coach helping an actor practise a monologue. Software measured \
one recording of the actor and wrote the findings you are given. You did not hear the recording.

Rules you must follow:
1. Use only the findings and the transcript. Never state a number, a time or a measurement \
that is not written in them. A figure with a unit (WPM, seconds, dB, Hz, semitones, %) must be \
copied exactly from a finding or from the bands.
2. The app prints each finding's own text beside your answer, so do not repeat its figures. \
Say what a listener would notice and what to change.
3. Do not mention breathing, emotion, pronunciation, accent or clarity of consonants. None \
of these were measured.
4. The delivery profile is a coaching target described in words. Never say or imply that the \
recording was compared with the character's real voice.
5. Write plain English in short sentences and address the actor as "you".
6. For each correction, choose the segment where the change matters most, judging by what \
the words mean. Use a different segment for each correction when you can.
7. In "why", talk about the chosen line: what it does in the speech, and what the listener \
loses the way it was delivered.
8. A drill is done right now on the chosen segment. Quote its first few words exactly as \
they appear on that one transcript line, say how to speak them, and how many times. Build \
the drill on the technique given with the issue.
9. The actor may have marked a pause as intentional or as accidental. Never advise shortening \
or removing a pause marked intentional, and never praise a pause marked accidental."""

TASK = """TASK
Write the coaching for the next take.
- corrections: {correction_task} For each one give the finding, the segment to practise on, \
a title, why it matters for this actor and profile in 1 or 2 sentences, and one drill in 1 or \
2 sentences. The title is an instruction of at most 6 words that starts with a verb and says \
what to do, not what went wrong.
- working: {working_task}
Answer in JSON."""


@dataclass(frozen=True)
class Prompt:
    messages: list[Message]
    schema: dict
    # The data the model was shown: any figure it quotes must appear in here.
    facts_text: str
    # True when phrases were cut short to fit the model's context.
    shortened: bool
    # IDs the answer may name.
    issue_ids: list[str]
    strength_ids: list[str]
    segment_ids: list[str]


def estimate_tokens(text: str) -> int:
    """A deliberately high guess at how many tokens the model will count.

    Measured on llama3.1:8b: English words run at about 4 characters per token and
    Devanagari at about 2, but digits and punctuation cost far more, and a transcript
    listing is full of them ("[0:15.7-0:17.8] 209 WPM"). Counting letters alone came out
    27% too low on such a listing. So letters and spaces are counted at 3.5 characters per
    token, every digit and punctuation mark as a whole token, and other scripts at 1.6
    characters per token. On every text measured, that came out above the real count.
    """
    letters = sum(1 for c in text if c.isascii() and (c.isalpha() or c == " "))
    marks = sum(1 for c in text if c.isascii() and not (c.isalpha() or c == " "))
    other_scripts = len(text) - letters - marks
    return math.ceil(letters / 3.5 + marks + other_scripts / 1.6)


def _shorten(text: str, limit: int | None) -> str:
    words = text.split()
    if limit is None or len(words) <= limit:
        return text
    return " ".join(words[:limit]) + " …"


def _transcript_lines(
    body: schemas.AnalysisBody,
    limit: int | None,
    only: set[str] | None = None,
    *,
    compact: bool = False,
    labels: dict[str, str] | None = None,
) -> list[str]:
    """One line per phrase, with the pauses between them, in order.

    The compact form is for long recordings. Timings and figures are costly for the model
    to read, so it gives each phrase's start time only, leaves out its WPM, and lists only
    the pauses long enough to register. That leaves room for more of the words.
    """
    pause_after = {pause.after_segment_id: pause for pause in body.pauses}
    lines: list[str] = []
    for segment in body.segments:
        if only is None or segment.id in only:
            said = (
                f'"{_shorten(segment.transcript, limit)}"'
                if segment.transcript
                else "(words not recognised)"
            )
            if compact:
                lines.append(f"{segment.id} [{timecode(segment.start_seconds)}]: {said}")
            else:
                pace = (
                    f" {number(segment.segment_wpm)} WPM"
                    if segment.reliable and segment.segment_wpm is not None
                    else ""
                )
                lines.append(
                    f"{segment.id} [{timecode(segment.start_seconds)}-"
                    f"{timecode(segment.end_seconds)}]{pace}: {said}"
                )
        pause = pause_after.get(segment.id)
        if pause is None or only is not None:
            continue
        label = (labels or {}).get(pause.id)
        marked = f", marked {label} by the actor" if label else ""
        if not compact:
            lines.append(f"({pause.id}: {seconds_text(pause.duration_seconds)} of silence{marked})")
        elif pause.significance != "short" or label:
            lines.append(f"(pause, {seconds_text(pause.duration_seconds)}{marked})")
    return lines


def _fit_transcript(
    body: schemas.AnalysisBody,
    finding_set: FindingSet,
    budget: int,
    labels: dict[str, str] | None = None,
) -> tuple[list[str], list[str], bool]:
    """The transcript lines that fit, the segments they cover, and whether words were cut."""
    all_ids = [segment.id for segment in body.segments]

    def fits(lines: list[str]) -> bool:
        return estimate_tokens("\n".join(lines)) <= budget

    full = _transcript_lines(body, None, labels=labels)
    if fits(full):
        return full, all_ids, False
    for limit in WORD_LIMITS:
        lines = _transcript_lines(body, limit, compact=True, labels=labels)
        if fits(lines):
            return lines, all_ids, limit is not None
    # Too many phrases even at three words each: keep only those the findings point at.
    named = {
        evidence.id
        for finding in finding_set.findings
        for evidence in finding.evidence
        if evidence.kind == "segment"
    }
    anchor = rules.anchor_segment(body)
    if anchor:
        named.add(anchor.id)
    kept = [segment_id for segment_id in all_ids if segment_id in named]
    return _transcript_lines(body, WORD_LIMITS[1], named, compact=True), kept, True


def _profile_text(profile_id: str) -> str:
    profile = profiles.get_profile(profile_id)
    if not profile.targets:
        return (
            "DELIVERY PROFILE: none chosen. Coach for clear, engaging delivery in general, and "
            "treat every suggestion as optional."
        )
    text = (
        f"DELIVERY PROFILE: {profile.name}. {profile.summary}\n"
        f"Targets: {'; '.join(target.lower() for target in profile.targets)}.\n"
        f"{profiles.PROFILE_NOTE}"
    )
    if profile.not_measured:
        text += (
            "\nNot measured by this app, so do not comment on it: "
            + ", ".join(item.lower() for item in profile.not_measured)
            + "."
        )
    return text


def _bands_text(settings: CoachingSettings) -> str:
    return (
        "BANDS (this app's rough bands, not targets taken from any actor): pace is unhurried "
        f"under {number(settings.slow_wpm)} WPM and fast over {number(settings.fast_wpm)} WPM. "
        f"A pause registers from {seconds_text(settings.registering_pause_seconds)}. A held "
        f"silence is {seconds_text(settings.held_silence_seconds)} or more."
    )


def _schema(issue_ids: list[str], strength_ids: list[str], segment_ids: list[str]) -> dict:
    text = {"type": "string"}
    correction_count = min(rules.MAX_CORRECTIONS, len(issue_ids))
    working: dict = {"type": "array", "maxItems": 0}
    if strength_ids:
        working = {
            "type": "array",
            "minItems": 1,
            "maxItems": min(rules.MAX_WORKING, len(strength_ids)),
            "items": {
                "type": "object",
                "properties": {"finding": {"type": "string", "enum": strength_ids}, "note": text},
                "required": ["finding", "note"],
            },
        }
    return {
        "type": "object",
        "properties": {
            "corrections": {
                "type": "array",
                "minItems": correction_count,
                "maxItems": correction_count,
                "items": {
                    "type": "object",
                    "properties": {
                        "finding": {"type": "string", "enum": issue_ids},
                        "segment": {"type": "string", "enum": segment_ids},
                        "title": text,
                        "why": text,
                        "drill": text,
                    },
                    "required": ["finding", "segment", "title", "why", "drill"],
                },
            },
            "working": working,
        },
        "required": ["corrections", "working"],
    }


def build_prompt(
    body: schemas.AnalysisBody,
    finding_set: FindingSet,
    wants: dict[str, str],
    settings: CoachingSettings,
    *,
    context_tokens: int,
    labels: dict[str, str] | None = None,
) -> Prompt:
    """`labels` are the user's own labels on pauses, shown to the model beside each pause."""
    budget = max(MIN_TRANSCRIPT_TOKENS, context_tokens - RESERVED_TOKENS)
    lines, segment_ids, shortened = _fit_transcript(body, finding_set, budget, labels)

    issues, strengths = finding_set.issues, finding_set.strengths
    context = [f for f in finding_set.findings if f.role == "context"]

    def listed(findings: list[schemas.Finding], *, with_aim: bool = False) -> str:
        rows = []
        for finding in findings:
            rows.append(f"{finding.id}: {finding.statement}")
            if with_aim:
                # The direction and the method come from the templates, so the model cannot
                # coach the wrong way round; it chooses the line and finds the words.
                template = rules.template_for(finding_set.details[finding.id], wants)
                rows.append(f"    Aim: {template.title}. Technique: {template.technique}.")
        return "\n".join(rows) or "(none)"

    language = LANGUAGE_NAMES.get(body.language.code, body.language.code)
    cautions = "".join(f"\n- {warning.message}" for warning in body.warnings)
    data = "\n\n".join(
        [
            _profile_text(body.profile),
            f"RECORDING: {seconds_text(body.duration_seconds)} long. Language: {language}."
            + (f"\nCautions about the measurements:{cautions}" if cautions else ""),
            "TRANSCRIPT, one line per segment. A segment is one phrase between pauses."
            + (" Long phrases are cut short with “…”." if shortened else "")
            + "\n"
            + "\n".join(lines),
            _bands_text(settings),
            (
                "FINDINGS\n"
                "Issues, most important first (corrections come only from these):\n"
                f"{listed(issues, with_aim=True)}\n"
                "Strengths (“working” comes only from these):\n"
                f"{listed(strengths)}\n"
                "Context (for your information; do not select these):\n"
                f"{listed(context)}"
            ),
        ]
    )

    count = min(rules.MAX_CORRECTIONS, len(issues))
    correction_task = (
        "there is 1 issue; write the correction for it."
        if count == 1
        else f"choose the {count} issues that would most improve the next take, the most "
        "important first."
        if len(issues) > count
        else f"write one for each of the {count} issues, the most important first."
    )
    working_task = (
        "for 1 or 2 of the strengths, write one sentence saying what to keep doing, with "
        "nothing in it about changing anything."
        if strengths
        else "leave this list empty, because there are no strengths listed."
    )
    task = TASK.format(correction_task=correction_task, working_task=working_task)

    return Prompt(
        messages=[Message("system", SYSTEM), Message("user", f"{data}\n\n{task}")],
        schema=_schema([f.id for f in issues], [f.id for f in strengths], segment_ids or ["seg-1"]),
        facts_text=data,
        shortened=shortened,
        issue_ids=[f.id for f in issues],
        strength_ids=[f.id for f in strengths],
        segment_ids=segment_ids,
    )
