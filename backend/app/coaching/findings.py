"""Turns the measurements of one recording into findings: plain statements of fact.

    measurements -> findings -> (language model or templates) -> coaching

Every number that reaches the user in the coaching comes from a statement written here, by
ordinary code. The language model is later asked to choose among these findings and to word
advice about them; it is never asked to work a number out.

Each finding also gets a role against the chosen delivery profile:

- "issue":    works against the profile (or is a common weakness when no profile is chosen)
- "strength": already fits the profile
- "context":  worth knowing, but neither

Where the voice sits (its pitch and its resonance) is judged against nothing unless the
speaker chose a goal: to keep their voice in the lower range, or in the higher one. With a
goal, the phrases that left that range become something to work on. Without one they are
stated and left alone. Either way the wording is about the sound, never about the speaker.

The user can label a pause as intentional or accidental. A label changes how a pause is read
here: an accidental pause is not praised as a held silence, and an intentional one is never
called a fault. It does not change what was measured. Every pause stays in the pause
figures, whatever its label.
"""

import statistics
from dataclasses import dataclass, field
from typing import Literal

from app import profiles, schemas
from app.coaching.settings import CoachingSettings

Level = Literal["low", "moderate", "high"]
Role = Literal["issue", "strength", "context"]
Want = Literal["low", "high"]

# Which aspect of delivery each profile focus metric speaks about.
DIMENSION_BY_METRIC = {
    "speechActiveWpm": "pace",
    "paceVariation": "pace_variation",
    "medianPauseSeconds": "pause_length",
    "longestPauseSeconds": "held_silence",
    "energyVariation": "loudness_variation",
    "pitchVariationSemitones": "pitch_variation",
}

# When a profile has no view on an aspect, these general speaking habits apply instead:
# a very fast pace and a flat pitch are worth mentioning to anyone.
DEFAULT_ROLES: dict[tuple[str, Level], tuple[Role, float]] = {
    ("pace", "high"): ("issue", 0.8),
    ("pitch_variation", "low"): ("issue", 0.6),
    ("pitch_variation", "high"): ("strength", 0.0),
}

# The two findings about where the voice sits, and the direction a goal moves them in.
VOICE_KINDS = ("voice_pitch", "voice_resonance")
VOICE_LEVEL: dict[str, Level] = {"lower": "low", "neutral": "moderate", "higher": "high"}
VOICE_HEARD = {
    "lower": "A voice in that range is typically heard as masculine.",
    "neutral": "A voice in that range could be heard either way.",
    "higher": "A voice in that range is typically heard as feminine.",
}
VOICE_CAVEAT = (
    "The voice ranges are this app's own rough ranges. They describe how a voice is typically "
    "heard, not who is speaking, and they are not a judgement of any voice. A voice changes "
    "through weeks of gentle practice: stop if your throat feels strained, and consider a "
    "voice coach or a speech therapist for guidance."
)

ESTIMATE_NOTE = " This rests on the recognised words, so treat it as an estimate."
# Fewer recognised words than this and "no word stood out" says nothing.
MIN_WORDS_FOR_EMPHASIS = 20
LISTED_EXAMPLES = 3


@dataclass
class Found:
    """A finding before it is given an ID. `data` carries values the templates need."""

    kind: str
    role: Role
    statement: str
    level: Level | None = None
    # How much an issue matters, 0 to 1. Only used to put issues in order.
    weight: float = 0.0
    evidence: list[schemas.Evidence] = field(default_factory=list)
    data: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FindingSet:
    findings: list[schemas.Finding]
    # The same findings by ID, with the extra values the templates use.
    details: dict[str, Found]
    summary: list[schemas.SummaryLine]
    caveats: list[str]

    @property
    def issues(self) -> list[schemas.Finding]:
        """Most important first."""
        found = [f for f in self.findings if f.role == "issue"]
        return sorted(found, key=lambda f: -self.details[f.id].weight)

    @property
    def strengths(self) -> list[schemas.Finding]:
        return [f for f in self.findings if f.role == "strength"]


# --- Formatting --------------------------------------------------------------------------


def timecode(seconds: float) -> str:
    """A position in the recording, written the way the screen writes it: 0:04.7."""
    tenths = round(max(0.0, seconds) * 10)
    return f"{tenths // 600}:{(tenths % 600) / 10:04.1f}"


def number(value: float, digits: int = 0) -> str:
    return f"{value:.{digits}f}"


def seconds_text(value: float) -> str:
    text = f"{value:.1f}".removesuffix(".0")
    return f"{text} second" if text == "1" else f"{text} seconds"


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def band(value: float, low_below: float, high_from: float) -> Level:
    if value < low_below:
        return "low"
    return "high" if value >= high_from else "moderate"


def segment_evidence(segment: schemas.SpeechSegment) -> schemas.Evidence:
    return schemas.Evidence(
        kind="segment",
        id=segment.id,
        label=f"Segment {segment.index + 1}",
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
    )


def pause_evidence(pause: schemas.PauseEvent) -> schemas.Evidence:
    return schemas.Evidence(
        kind="pause",
        id=pause.id,
        label=f"Pause at {timecode(pause.start_seconds)}",
        start_seconds=pause.start_seconds,
        end_seconds=pause.end_seconds,
    )


def metric_evidence(name: str, label: str) -> schemas.Evidence:
    return schemas.Evidence(kind="metric", id=name, label=label)


# --- Roles -------------------------------------------------------------------------------


def profile_wants(profile_id: str) -> dict[str, Want]:
    profile = profiles.get_profile(profile_id)
    return {DIMENSION_BY_METRIC[focus.metric]: focus.wants for focus in profile.focus}


def banded_role(dimension: str, level: Level, wants: dict[str, Want]) -> tuple[Role, float]:
    """The role of a banded measurement, and how much it matters if it is an issue."""
    want = wants.get(dimension)
    if want is None:
        return DEFAULT_ROLES.get((dimension, level), ("context", 0.0))
    if level == want:
        return "strength", 0.0
    # Partway there still leaves room to move; the opposite end matters most.
    return "issue", 0.5 if level == "moderate" else 1.0


# --- Building ----------------------------------------------------------------------------


def known_labels(body: schemas.AnalysisBody, labels: dict[str, str] | None) -> dict[str, str]:
    """The labels that belong to pauses this recording really has."""
    pause_ids = {pause.id for pause in body.pauses}
    return {
        pause_id: label
        for pause_id, label in (labels or {}).items()
        if pause_id in pause_ids and label in ("intentional", "accidental")
    }


def build_findings(
    body: schemas.AnalysisBody,
    settings: CoachingSettings,
    labels: dict[str, str] | None = None,
) -> FindingSet:
    """`labels` are the user's own labels on pauses: pause ID -> "intentional" / "accidental"."""
    wants = profile_wants(body.profile)
    metrics = body.metrics
    labels = known_labels(body, labels)
    found: list[Found] = []

    pace = _pace(metrics, settings, wants)
    variation = _pace_variation(body, settings, wants)
    pauses = _pauses(body, settings, wants, labels)
    longest = _longest_pause(body, settings, wants, labels)
    loudness = _loudness(metrics, settings, wants)
    pitch = _pitch(metrics, settings, wants)
    confidence = _recognition_confidence(body)

    found += [f for f in (pace, variation, pauses, longest) if f]
    found += _labelled_pauses(body, wants, labels)
    found += [f for f in (loudness, pitch) if f]
    voice = _voice(body)
    found += voice
    found += _segment_findings(body, settings, wants)
    found += [f for f in (_hesitations(body), _emphasis(body, wants), confidence) if f]

    findings: list[schemas.Finding] = []
    details: dict[str, Found] = {}
    for index, item in enumerate(found, start=1):
        # Feedback on corrections can move a kind of issue down the list. It only changes
        # the order issues are offered in; the finding itself is always still listed.
        item.weight *= settings.priority(item.kind)
        finding_id = f"f{index}"
        details[finding_id] = item
        findings.append(
            schemas.Finding(
                id=finding_id,
                kind=item.kind,
                level=item.level,
                role=item.role,
                statement=item.statement,
                evidence=item.evidence,
            )
        )

    def line(label: str, parts: list[Found | None], missing: str) -> schemas.SummaryLine:
        text = " ".join(part.statement for part in parts if part) or missing
        return schemas.SummaryLine(label=label, text=text)

    summary = [
        line(
            "Pace",
            [pace, variation],
            metrics.speech_active_wpm.note or "Pace could not be measured.",
        ),
        line("Pauses", [pauses, longest], "No pauses were detected."),
        line("Voice", [loudness, pitch], "Loudness and pitch could not be measured."),
        line(
            "Clarity",
            [confidence],
            "Clarity is not measured, and no words were recognised to judge it by.",
        ),
    ]
    # Where the voice sits is summed up only for a speaker who chose to work on it.
    if voice and _voice_goal(body) != "none":
        summary.insert(3, line("Voice range", list(voice), ""))
    return FindingSet(findings, details, summary, _caveats(body, variation is not None))


def _pace(metrics: schemas.Metrics, settings: CoachingSettings, wants) -> Found | None:
    metric = metrics.speech_active_wpm
    if metric.value is None:
        return None
    level = band(metric.value, settings.slow_wpm, settings.fast_wpm)
    described = {
        "low": f"That is unhurried: under {number(settings.slow_wpm)} WPM.",
        "moderate": (
            f"That is a moderate pace: between {number(settings.slow_wpm)} and "
            f"{number(settings.fast_wpm)} WPM."
        ),
        "high": f"That is fast: over {number(settings.fast_wpm)} WPM.",
    }[level]
    role, weight = banded_role("pace", level, wants)
    return Found(
        kind="pace",
        level=level,
        role=role,
        weight=weight,
        statement=(
            f"You spoke at {number(metric.value)} WPM while speaking (pauses left out). "
            f"{described}" + (ESTIMATE_NOTE if metric.quality == "estimated" else "")
        ),
        evidence=[metric_evidence("speechActiveWpm", "Speech-active WPM")],
    )


def _pace_variation(body: schemas.AnalysisBody, settings: CoachingSettings, wants) -> Found | None:
    spread = body.metrics.pace_variation
    typical = body.metrics.typical_segment_wpm
    # Without a typical pace there are too few measurable phrases to call the pace even or not.
    if spread.value is None or not typical.value:
        return None
    ratio = spread.value / typical.value
    level = band(ratio, settings.even_pace_ratio, settings.varied_pace_ratio)
    even, varied = round(settings.even_pace_ratio * 100), round(settings.varied_pace_ratio * 100)
    described = {
        "low": f"That is very even: under {even}%.",
        "moderate": f"That is moderately varied: between {even}% and {varied}%.",
        "high": f"That is widely varied: over {varied}%.",
    }[level]

    reliable = [s for s in body.segments if s.reliable and s.segment_wpm is not None]
    evidence = [metric_evidence("paceVariation", "Pace variation")]
    extremes = ""
    data: dict[str, str] = {}
    if len(reliable) >= 2:
        slowest = min(reliable, key=lambda s: s.segment_wpm)
        fastest = max(reliable, key=lambda s: s.segment_wpm)
        extremes = (
            f" Slowest: segment {slowest.index + 1} at {number(slowest.segment_wpm)} WPM. "
            f"Fastest: segment {fastest.index + 1} at {number(fastest.segment_wpm)} WPM."
        )
        evidence += [segment_evidence(slowest), segment_evidence(fastest)]
        data = {"slowest": slowest.id, "fastest": fastest.id}

    role, weight = banded_role("pace_variation", level, wants)
    return Found(
        kind="pace_variation",
        level=level,
        role=role,
        weight=weight,
        statement=(
            f"Your phrases varied by {number(spread.value)} WPM around your typical "
            f"{number(typical.value)} WPM, which is {round(ratio * 100)}%. {described}{extremes}"
            + (ESTIMATE_NOTE if spread.quality == "estimated" else "")
        ),
        evidence=evidence,
        data=data,
    )


def _pauses(
    body: schemas.AnalysisBody, settings: CoachingSettings, wants, labels: dict[str, str]
) -> Found | None:
    metrics = body.metrics
    if metrics.pause_count.value is None:
        return None
    count = int(metrics.pause_count.value)
    shortest_pause = seconds_text(body.settings.get("min_pause_ms", 500) / 1000)
    evidence = [metric_evidence("medianPauseSeconds", "Median pause")]

    if count == 0:
        speaking = metrics.speech_active_seconds.value or 0.0
        if speaking < settings.no_pause_min_speech_seconds:
            return None
        wanted = "high" in (wants.get("pause_length"), wants.get("held_silence"))
        return Found(
            kind="no_pauses",
            level="low",
            role="issue",
            weight=1.0 if wanted else 0.7,
            statement=(
                f"No pause of {shortest_pause} or more was detected in "
                f"{seconds_text(speaking)} of speech."
            ),
            evidence=evidence,
        )

    median = metrics.median_pause_seconds.value
    if median is None:
        return None
    measured = (
        f"{plural(count, 'pause')} of {shortest_pause} or more, with a median of "
        f"{seconds_text(median)}."
    )
    share = metrics.pause_ratio.value
    share_text = (
        f" Pauses make up {round(share * 100)}% of the recording." if share is not None else ""
    )
    threshold = settings.registering_pause_seconds

    # Pauses the user marked as accidental stay in the figures above, which describe the
    # recording as it is. They are left out only of the judgement of pause length: a slip
    # is not a pause the speaker chose to hold.
    accidental = [p for p in body.pauses if labels.get(p.id) == "accidental"]
    meant = [p for p in body.pauses if labels.get(p.id) != "accidental"]
    marked = ""
    if accidental and meant:
        # Rounded to the millisecond first: the mean of 0.6 and 0.7 must read as 0.65,
        # not as the 0.6499999 that floating-point arithmetic makes of it.
        median = round(statistics.median(pause.duration_seconds for pause in meant), 3)
        marked = (
            f" You marked {len(accidental)} as accidental. Leaving "
            f"{'it' if len(accidental) == 1 else 'them'} out, the other {len(meant)} "
            f"{'has' if len(meant) == 1 else 'have'} a median of {seconds_text(median)}."
        )
    elif accidental:
        return Found(
            kind="pause_length",
            level="low",
            role="issue"
            if "high" in (wants.get("pause_length"), wants.get("held_silence"))
            else "context",
            weight=1.0,
            statement=(
                f"{measured} You marked {'it' if count == 1 else 'all of them'} as "
                "accidental, so no pause in this take was one you chose to make."
                f"{share_text}"
            ),
            evidence=evidence,
        )

    level = band(median, threshold, threshold)
    described = (
        f"That is short: under {seconds_text(threshold)}."
        if level == "low"
        else f"That is long enough to register: {seconds_text(threshold)} or more."
    )
    role, weight = banded_role("pause_length", level, wants)
    return Found(
        kind="pause_length",
        level=level,
        role=role,
        weight=weight,
        statement=f"{measured}{marked} {described}{share_text}",
        evidence=evidence,
    )


def _longest_pause(
    body: schemas.AnalysisBody, settings: CoachingSettings, wants, labels: dict[str, str]
) -> Found | None:
    # An accidental pause is not a silence the speaker held, however long it lasted.
    meant = [p for p in body.pauses if labels.get(p.id) != "accidental"]
    if not meant:
        return None
    pause = max(meant, key=lambda p: p.duration_seconds)
    left_out = len(body.pauses) - len(meant)
    threshold = settings.held_silence_seconds
    level = band(pause.duration_seconds, threshold, threshold)
    described = (
        f"That is a held silence: {seconds_text(threshold)} or more."
        if level == "high"
        else f"No pause was held for {seconds_text(threshold)}."
    )
    if "held_silence" in wants:
        role, weight = banded_role("held_silence", level, wants)
    elif level == "high" and wants.get("pause_length") == "high":
        role, weight = "strength", 0.0
    else:
        role, weight = "context", 0.0
    opening = (
        f"Leaving out the {plural(left_out, 'pause')} you marked as accidental, the longest pause"
        if left_out
        else "The longest pause"
    )
    intended = " You marked it as intentional." if labels.get(pause.id) == "intentional" else ""
    return Found(
        kind="held_silence",
        level=level,
        role=role,
        weight=weight,
        statement=(
            f"{opening} is {seconds_text(pause.duration_seconds)}, at "
            f"{timecode(pause.start_seconds)}, between segments {pause.index + 1} and "
            f"{pause.index + 2}.{intended} {described}"
        ),
        evidence=[pause_evidence(pause)],
        data={"after": pause.after_segment_id, "before": pause.before_segment_id},
    )


def _labelled_pauses(body: schemas.AnalysisBody, wants, labels: dict[str, str]) -> list[Found]:
    """What the user said about their own pauses, as findings the coaching can build on."""

    def listed(pauses: list[schemas.PauseEvent]) -> str:
        shown = ", ".join(
            f"{seconds_text(pause.duration_seconds)} at {timecode(pause.start_seconds)}"
            for pause in pauses[:LISTED_EXAMPLES]
        )
        more = len(pauses) - LISTED_EXAMPLES
        return shown + (f", and {more} more" if more > 0 else "")

    found: list[Found] = []
    accidental = [p for p in body.pauses if labels.get(p.id) == "accidental"]
    if accidental:
        found.append(
            Found(
                kind="accidental_pauses",
                role="issue",
                weight=0.7,
                statement=(
                    f"You marked {plural(len(accidental), 'pause')} as accidental: "
                    f"{listed(accidental)}. "
                    f"{'It still counts' if len(accidental) == 1 else 'They still count'} in "
                    "the pause figures, which describe the recording as it is."
                ),
                evidence=[pause_evidence(pause) for pause in accidental[:LISTED_EXAMPLES]],
                # The phrase that ran into the first slip is the one to practise through.
                data={"segment": accidental[0].after_segment_id},
            )
        )
    intentional = [p for p in body.pauses if labels.get(p.id) == "intentional"]
    if intentional:
        wanted = "high" in (wants.get("pause_length"), wants.get("held_silence"))
        found.append(
            Found(
                kind="intentional_pauses",
                role="strength" if wanted else "context",
                statement=(
                    f"You marked {plural(len(intentional), 'pause')} as intentional: "
                    f"{listed(intentional)}."
                ),
                evidence=[pause_evidence(pause) for pause in intentional[:LISTED_EXAMPLES]],
            )
        )
    return found


def _loudness(metrics: schemas.Metrics, settings: CoachingSettings, wants) -> Found | None:
    value = metrics.energy_variation.value
    if value is None:
        return None
    low, high = settings.even_loudness_db, settings.varied_loudness_db
    level = band(value, low, high)
    described = {
        "low": f"That is even: under {number(low)} dB.",
        "moderate": f"That is moderate: between {number(low)} and {number(high)} dB.",
        "high": f"That is widely varied: over {number(high)} dB.",
    }[level]
    role, weight = banded_role("loudness_variation", level, wants)
    return Found(
        kind="loudness_variation",
        level=level,
        role=role,
        weight=weight,
        statement=f"Loudness varied by {number(value, 1)} dB across your speech. {described}",
        evidence=[metric_evidence("energyVariation", "Loudness variation")],
    )


def _pitch(metrics: schemas.Metrics, settings: CoachingSettings, wants) -> Found | None:
    value = metrics.pitch_variation_semitones.value
    if value is None:
        return None
    low, high = settings.narrow_pitch_semitones, settings.wide_pitch_semitones
    level = band(value, low, high)
    described = {
        "low": f"That is a narrow range: under {number(low)} semitones.",
        "moderate": f"That is moderate: between {number(low)} and {number(high)} semitones.",
        "high": f"That is a wide range: over {number(high)} semitones.",
    }[level]
    role, weight = banded_role("pitch_variation", level, wants)
    return Found(
        kind="pitch_variation",
        level=level,
        role=role,
        weight=weight,
        statement=(
            f"Pitch varied by {number(value, 1)} semitones around your own median. {described}"
        ),
        evidence=[metric_evidence("pitchVariationSemitones", "Pitch variation")],
    )


def _voice_goal(body: schemas.AnalysisBody) -> str:
    return body.voice_range.goal if body.voice_range else "none"


def _range_text(band: str, edges: tuple[float, float]) -> str:
    neutral_from, neutral_to = (number(edge) for edge in edges)
    return {
        "lower": f"the lower range (under {neutral_from} Hz)",
        "neutral": f"the neutral range ({neutral_from} to {neutral_to} Hz)",
        "higher": f"the higher range (over {neutral_to} Hz)",
    }[band]


def _voice(body: schemas.AnalysisBody) -> list[Found]:
    """Where the voice sat, in pitch and in resonance, and how that stands against the goal."""
    voice = body.voice_range
    if voice is None:
        return []
    goal = voice.goal
    scales = (
        ("pitch", "voice_pitch", voice.pitch, "Your pitch sat at a median of {value} Hz."),
        (
            "resonance",
            "voice_resonance",
            voice.resonance,
            (
                "The resonance of your voice measured {value} Hz: the average spacing of its "
                "formants, where lower is deeper and higher is brighter."
            ),
        ),
    )
    found: list[Found] = []
    for scale, kind, placed, opening in scales:
        if placed is None:
            continue
        edges = (
            float(voice.bands.get(f"{scale}_neutral_from_hz", 0)),
            float(voice.bands.get(f"{scale}_neutral_to_hz", 0)),
        )
        where = f"That is in {_range_text(placed.band, edges)}"
        if placed.band != "neutral":
            where += f", {placed.percent}% of the way into it"
        statement = f"{opening.format(value=number(placed.value_hz))} {where}. "
        statement += VOICE_HEARD[placed.band]
        if placed.quality == "estimated":
            statement += " " + (
                voice.resonance_note
                or "There was little clear sound to measure it from, so treat it as an estimate."
            )

        role: Role = "context"
        weight = 0.0
        evidence = [metric_evidence(f"voiceRange.{scale}", f"Voice range: {scale}")]
        data: dict[str, str] = {}
        if goal != "none":
            phrases = [
                (segment, getattr(segment.voice, scale))
                for segment in body.segments
                if segment.voice and getattr(segment.voice, scale) is not None
            ]
            outside = [(segment, part) for segment, part in phrases if part.band != goal]
            # The phrase furthest from the range the speaker is aiming for comes first.
            outside.sort(
                key=lambda item: -item[1].value_hz if goal == "lower" else item[1].value_hz
            )
            inside = len(phrases) - len(outside)
            if phrases:
                statement += (
                    f" Your goal is to keep your voice in the {goal} range: "
                    f"{inside} of {plural(len(phrases), 'phrase')} stayed in it for {scale}."
                )
            if outside:
                listed = ", ".join(
                    f"segment {segment.index + 1} at {number(part.value_hz)} Hz"
                    for segment, part in outside[:LISTED_EXAMPLES]
                )
                statement += f" Furthest from it: {listed}."
                evidence += [segment_evidence(segment) for segment, _ in outside[:LISTED_EXAMPLES]]
                data["segment"] = outside[0][0].id
            data["direction"] = "lower" if goal == "lower" else "raise"
            if placed.band == goal and not outside:
                role = "strength"
            else:
                role = "issue"
                # The whole recording outside the range matters most; a few stray phrases least.
                weight = (
                    0.3 + 0.4 * len(outside) / len(phrases)
                    if placed.band == goal
                    else 0.7
                    if placed.band == "neutral"
                    else 1.0
                )
        found.append(
            Found(
                kind=kind,
                level=VOICE_LEVEL[placed.band],
                role=role,
                weight=weight,
                statement=statement,
                evidence=evidence,
                data=data,
            )
        )
    return found


def _segment_findings(body: schemas.AnalysisBody, settings: CoachingSettings, wants) -> list[Found]:
    """Phrases well away from the speaker's own typical pace, the furthest first."""
    typical = body.metrics.typical_segment_wpm.value
    if not typical:
        return []
    variation_want = wants.get("pace_variation")
    found: list[Found] = []
    for direction, kind in (("faster", "fast_segment"), ("slower", "slow_segment")):
        matching = [
            s for s in body.segments if s.pace_vs_typical == direction and s.segment_wpm is not None
        ]
        matching.sort(key=lambda s: -abs(s.segment_wpm / typical - 1))
        for segment in matching[: settings.max_segment_findings]:
            deviation = abs(segment.segment_wpm / typical - 1)
            if variation_want == "high":
                # A profile built on contrast: a phrase that breaks the pattern is the point.
                role, weight = "strength", 0.0
            elif direction == "faster" or variation_want == "low":
                role, weight = "issue", min(0.8, 0.4 + deviation)
            else:
                role, weight = "context", 0.0
            found.append(
                Found(
                    kind=kind,
                    role=role,
                    weight=weight,
                    statement=(
                        f"Segment {segment.index + 1} ({timecode(segment.start_seconds)} to "
                        f"{timecode(segment.end_seconds)}) ran at {number(segment.segment_wpm)} "
                        f"WPM, {round(deviation * 100)}% {direction} than your typical "
                        f"{number(typical)} WPM."
                    ),
                    evidence=[segment_evidence(segment)],
                    data={"segment": segment.id},
                )
            )
    return found


def _segment_at(body: schemas.AnalysisBody, seconds: float) -> schemas.SpeechSegment | None:
    for segment in body.segments:
        if segment.start_seconds <= seconds <= segment.end_seconds:
            return segment
    return None


def _examples(items: list[tuple[str, float]]) -> str:
    listed = ", ".join(f'"{text}" at {timecode(start)}' for text, start in items[:LISTED_EXAMPLES])
    more = len(items) - LISTED_EXAMPLES
    return listed + (f", and {more} more" if more > 0 else "")


def _evidence_for_moments(body: schemas.AnalysisBody, moments: list[float]) -> list:
    segments: dict[str, schemas.SpeechSegment] = {}
    for moment in moments[:LISTED_EXAMPLES]:
        segment = _segment_at(body, moment)
        if segment:
            segments.setdefault(segment.id, segment)
    return [segment_evidence(segment) for segment in segments.values()]


def _hesitations(body: schemas.AnalysisBody) -> Found | None:
    if not body.hesitations:
        return None
    count = len(body.hesitations)
    evidence = _evidence_for_moments(body, [h.start_seconds for h in body.hesitations])
    return Found(
        kind="hesitations",
        role="issue",
        weight=min(0.6, 0.3 + 0.1 * count),
        statement=(
            f"{plural(count, 'hesitation sound')} recognised: "
            f"{_examples([(h.text, h.start_seconds) for h in body.hesitations])}. Speech "
            "recognition often leaves these out, so there may be more."
        ),
        evidence=evidence,
        data={"segment": evidence[0].id} if evidence else {},
    )


def _emphasis(body: schemas.AnalysisBody, wants) -> Found | None:
    candidates = body.emphasis_candidates
    leans_expressive = "high" in (wants.get("loudness_variation"), wants.get("pitch_variation"))
    if not candidates:
        if len(body.words) < MIN_WORDS_FOR_EMPHASIS:
            return None
        return Found(
            kind="no_emphasis",
            role="issue" if leans_expressive else "context",
            weight=0.4,
            statement=(
                "No word stood out as clearly louder or higher in pitch than your typical word."
            ),
        )
    count = len(candidates)
    # For a restrained profile, a louder word is neither a fault nor a goal.
    restrained = wants.get("loudness_variation") == "low"
    evidence = _evidence_for_moments(body, [c.start_seconds for c in candidates])
    return Found(
        kind="emphasis",
        role="context" if restrained else "strength",
        statement=(
            f"{plural(count, 'word')} stood out as louder or higher in pitch than your typical "
            f"word: {_examples([(c.text, c.start_seconds) for c in candidates])}. These are "
            "candidates for emphasis, not proof that the stress was intended."
        ),
        evidence=evidence,
    )


def _recognition_confidence(body: schemas.AnalysisBody) -> Found | None:
    values = [word.confidence for word in body.words if word.confidence is not None]
    if not values:
        return None
    return Found(
        kind="recognition_confidence",
        role="context",
        statement=(
            "Clarity itself is not measured. As a rough sign of it, the speech recogniser's "
            f"average confidence in your words was {round(sum(values) / len(values) * 100)}%; "
            "that also drops with background noise or a quiet recording."
        ),
    )


def _caveats(body: schemas.AnalysisBody, pace_compared: bool) -> list[str]:
    """What is uncertain or was not measured, said plainly. Written by code, not the model."""
    caveats = [warning.message for warning in body.warnings]
    if body.segments and body.metrics.speech_active_wpm.value is not None and not pace_compared:
        caveats.append(
            "There were too few phrases long enough to measure, so how even your pace is "
            "was not assessed."
        )
    not_measured = profiles.get_profile(body.profile).not_measured
    if not_measured:
        caveats.append(
            "Part of this profile that the app cannot measure: "
            + ", ".join(item.lower() for item in not_measured)
            + "."
        )
    caveats.append(
        "Breaths are not detected, so nothing here is based on breathing. Emotion and "
        "pronunciation are not measured either."
    )
    if _voice_goal(body) != "none":
        caveats.append(VOICE_CAVEAT)
    return caveats
